"""
Relatório Diário — orquestra tudo:
  1. Roda o screener na watchlist, avaliando cada ativo de 0 a 10
  2. Manda TODOS os gráficos juntos, num álbum só
  3. Manda um resumo em texto, ranqueado do nível mais alto pro mais baixo
  4. Para os ativos com nível alto (>= nivel_detalhe) que sejam alerta NOVO:
       - Checa notícias de risco + calendário de resultados
       - Calcula stop/alvo + tamanho de posição + opção sugerida
  5. APÓS TUDO: IA analisa os melhores ativos visualmente (gráfico) e manda
     uma mensagem separada com "por que entrar" e "por que NÃO entrar" —
     roda sempre, não depende de estado ou filtros de score.
"""

import html
import os
import time
import logging
from datetime import date

import config
from screener import rodar_screener
from noticias import checar_risco_noticias
from opcoes import sugerir_parametros_opcao_com_preco
from calendario import checar_resultado_proximo
from gestao_risco import calcular_tamanho_posicao
from estado import carregar_estado, salvar_estado, atualizar_estado, score_suavizado
from ai_analyzer import AIAnalyzer
from posicoes import carregar_posicoes, formatar_gestao_todas, salvar_proposta_entrada
from b3_swing_analyzer import sugerir_stop_alvo, plotar_grafico, determinar_veredito
from trava import montar_trava, formatar_trava
from telegram_utils import enviar_mensagem, enviar_album

# Garante que os logs de erro do ai_analyzer.py (status HTTP, mensagem,
# stacktrace) apareçam no console/log do GitHub Actions. Não interfere em
# nenhum print() já existente no projeto.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

PASTA_GRAFICOS = "graficos_tmp"
SCORE_MINIMO_IA = 8  # IA analisa todos os ativos com score >= esse valor


def validar_configuracao() -> None:
    """
    Valida as configurações essenciais ANTES de rodar o relatório.
    Falha rápido com mensagem clara em vez de deixar uma chave ausente
    ser descoberta no meio do processamento (ex: enviar gráfico sem token).
    """
    faltando = []

    # Telegram é obrigatório — sem ele nada é entregue
    if not getattr(config, "TELEGRAM_TOKEN", "") or "COLOQUE" in str(getattr(config, "TELEGRAM_TOKEN", "")):
        faltando.append("TELEGRAM_TOKEN (crie um bot no BotFather e configure o secret)")
    if not getattr(config, "TELEGRAM_CHAT_ID", "") or "COLOQUE" in str(getattr(config, "TELEGRAM_CHAT_ID", "")):
        faltando.append("TELEGRAM_CHAT_ID (seu chat id no Telegram)")

    # Gemini é obrigatório para a análise de IA; sem ele o relatório ainda roda,
    # mas a segunda opinião fica indisponível — avisamos mas não bloqueamos.
    sem_gemini = not getattr(config, "GEMINI_API_KEY", "")
    if sem_gemini:
        logging.warning("GEMINI_API_KEY ausente — a análise de IA (segunda opinião) ficará indisponível.")

    # Nemotron (CARLOS) é opcional — fallback silencioso para Gemini puro.
    sem_nemotron = not getattr(config, "CARLOS", "")
    if sem_nemotron:
        logging.info("CARLOS (Nemotron) ausente — a análise usará Gemini puro.")

    if faltando:
        mensagem = (
            "❌ Configuração incompleta — o relatório não pode rodar.\n"
            + "\n".join(f"  • {item}" for item in faltando)
            + "\nConfigure os secrets no GitHub: Settings → Secrets and variables → Actions."
        )
        logging.error("%s", mensagem)
        raise SystemExit(mensagem)


def montar_bloco_resumo(resultado: dict, estado: dict, nivel_detalhe: int,
                         atr_mult: float = 1.5, risco_retorno: float = 2.0,
                         risco_maximo_atr_mult: float = 3.0,
                         margem_saida_estado: int = 2,
                         caminho_imagem: str = None) -> str:
    ticker = resultado["ticker"]
    score = resultado["score"]
    direcao = resultado["direcao"]

    veredito = determinar_veredito(score, direcao)

    if direcao == "neutro":
        palavra = "NEUTRO"
    elif direcao == "compra":
        palavra = "COMPRA"
    else:
        palavra = "VENDA"

    cabecalho = (
        f"{veredito['emoji']} <b>{veredito['veredito']}</b> — {ticker} "
        f"({score}/10 {palavra})\n"
        f"<i>{veredito['descricao']}</i>"
    )
    motivos_txt = "\n".join(f"  • {m}" for m in resultado["motivos"])

    if direcao == "neutro" or score < nivel_detalhe:
        return f"{cabecalho}\n{motivos_txt}"

    # --- Alerta NOVO: checa notícias e calendário ---
    nome_empresa = config.NOME_EMPRESA.get(ticker, ticker)
    risco_noticias = checar_risco_noticias(nome_empresa)

    if risco_noticias["bloquear_entrada"]:
        motivo = risco_noticias["alertas"][0]["motivo"]
        return (
            f"{cabecalho}\n{motivos_txt}\n"
            f"  🚫 <b>CANCELADO</b> — notícia de risco: {motivo}"
        )

    resultado_trimestral = checar_resultado_proximo(ticker, config.DIAS_MINIMOS_ANTES_RESULTADO)
    if resultado_trimestral["tem_resultado_proximo"]:
        return (
            f"{cabecalho}\n{motivos_txt}\n"
            f"  🚫 <b>CANCELADO</b> — resultado trimestral em "
            f"{resultado_trimestral['dias_ate_resultado']} dia(s) ({resultado_trimestral['data_resultado']})"
        )

    df = resultado["df"]
    stop_alvo = sugerir_stop_alvo(df, direcao, atr_mult=atr_mult,
                                   risco_retorno=risco_retorno,
                                   risco_maximo_atr_mult=risco_maximo_atr_mult)

    # Guarda a proposta de entrada: você decide se registra (respondendo
    # "/registrar TICKER" no Telegram) ou ignora. Nada é registrado sozinho.
    try:
        salvar_proposta_entrada(ticker, direcao, resultado["preco"],
                                stop_alvo["stop"], stop_alvo["alvo"])
    except Exception as e:
        logging.warning("Falha ao salvar proposta de %s: %s", ticker, e)

    opcao = sugerir_parametros_opcao_com_preco(
        resultado["preco"], direcao, ticker,
        token=getattr(config, "OPLAB_TOKEN", ""),
    )
    posicao = calcular_tamanho_posicao(
        config.CAPITAL_DISPONIVEL, config.RISCO_POR_OPERACAO_PCT,
        stop_alvo["preco_entrada"], stop_alvo["stop"]
    )

    explicacao_opcao = (
        "CALL lucra se o ativo SOBE"
        if opcao["tipo_opcao"] == "CALL"
        else "PUT lucra se o ativo CAI"
    )

    plano = (
        f"{cabecalho}\n{motivos_txt}\n"
        f"  <b>Preço:</b> R$ {resultado['preco']:.2f}\n"
        f"  <b>Entrada</b> R$ {stop_alvo['preco_entrada']} · "
        f"<b>Stop</b> R$ {stop_alvo['stop']} · "
        f"<b>Alvo</b> R$ {stop_alvo['alvo']}\n"
    )

    if posicao.get("quantidade_acoes", 0) > 0:
        plano += (
            f"  <b>Tamanho:</b> {posicao['quantidade_acoes']} ações "
            f"(≈ R$ {posicao['valor_posicao']}), risco R$ {posicao['valor_em_risco']} "
            f"({posicao['pct_capital_em_risco']}% do capital)\n"
        )

    if opcao.get("premio"):
        linha_premio = f"R$ {opcao['premio']:.2f} (preço real)"
        if opcao.get("fonte") == "oplab":
            linha_premio += " — OpLab"
        else:
            linha_premio += " — estimativa teórica"
    else:
        linha_premio = "estimativa teórica (sem cotação real)"

    plano += (
        f"  <b>Opção:</b> {opcao['tipo_opcao']} strike ~R$ {opcao['strike_sugerido_aprox']}, "
        f"venc. {opcao['vencimento_sugerido']} — {explicacao_opcao}\n"
        f"  <i>Prêmio: {linha_premio}</i>\n"
        f"  ⚠️ Confirme liquidez antes de operar.\n"
        f"  ✅ Se ENTRAR, registre: responda <b>/registrar {ticker}</b> no chat."
    )

    if risco_noticias.get("positivas"):
        plano += f"\n  ✅ {risco_noticias['positivas'][0]['titulo']}"

    return plano


def _montar_analisador_ia() -> AIAnalyzer | None:
    """Cria o AIAnalyzer (Gemini) se USAR_IA_ANALISE e GEMINI_API_KEY estiverem configurados."""
    if not getattr(config, "USAR_IA_ANALISE", True):
        return None

    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key:
        return None

    nemotron_key = getattr(config, "CARLOS", "")
    logging.info("CARLOS (chave Nemotron) configurada: %s", "sim" if nemotron_key else "não")
    
    return AIAnalyzer(
        api_key=api_key,
        model=getattr(config, "GEMINI_MODEL", None),
        timeout_seconds=getattr(config, "GEMINI_TIMEOUT_SECONDS", 45),
        max_retries=getattr(config, "GEMINI_MAX_RETRIES", 3),
        CARLOS=getattr(config, "CARLOS", ""),
        CARLOS_model=getattr(config, "CARLOS_model", "nemotron-3-ultra-free"),
        CARLOS_base_url=getattr(config, "CARLOS_base_url", "https://opencode.ai/zen/v1"),
    )


def rodar_analise_ia(resultados: list, arquivo_estado: str) -> str:
    """
    Roda a IA (Gemini) em todos os ativos com score >= SCORE_MINIMO_IA e monta
    uma mensagem consolidada de segunda opinião. Sempre roda, independente de
    estado ou alertas anteriores.

    A IA recebe: ticker, preço, EMA/SMA21, EMA/SMA200, RSI, MACD, ATR, volume,
    suporte, resistência, score, direção, motivos do score, notícias completas
    (título de cada manchete, não só palavras-chave) e a imagem do gráfico
    candlestick. Ela NÃO recalcula nada e NÃO decide entrada — só interpreta.

    Se o Gemini falhar (rede, chave, limite de uso, etc.) o relatório técnico
    principal já foi enviado antes desta função ser chamada, então o robô
    nunca é interrompido por causa da IA.
    """
    analisador = _montar_analisador_ia()
    if analisador is None:
        return ""

    candidatos = [
        r for r in resultados
        if r.get("score_bruto", r["score"]) >= SCORE_MINIMO_IA and r["direcao"] != "neutro"
    ]
    if not candidatos:
        return "🤖 <b>Análise da IA:</b> Nenhum ativo com sinal suficiente para análise hoje."

    sufixo = arquivo_estado.replace(".json", "")
    blocos_ia = []

    for r in candidatos[:6]:  # máximo 6 pra não estourar o limite gratuito do Gemini
        ticker = r["ticker"]
        caminho = os.path.join(PASTA_GRAFICOS, f"{ticker}_{sufixo}.png")
        if not os.path.exists(caminho):
            caminho = None  # a IA continua a análise só com os dados técnicos, sem a imagem

        try:
            ultimo = r["df"].iloc[-1]
            nome_empresa = config.NOME_EMPRESA.get(ticker, ticker)

            try:
                noticias_ativo = checar_risco_noticias(nome_empresa).get("noticias", [])
            except Exception as e:
                logging.warning("Falha ao buscar notícias de %s para a IA: %s", ticker, e, exc_info=True)
                noticias_ativo = []

            logging.info("Analisando IA do ativo %s", ticker)
            resultado_ia = analisador.analyze_asset(
                ticker=ticker,
                current_price=float(r["preco"]),
                ema21=float(ultimo["ema21"] if "ema21" in ultimo else ultimo["sma21"]),
                ema200=float(ultimo["ema200"] if "ema200" in ultimo else ultimo["sma200"]),
                rsi=float(ultimo["rsi"]),
                macd=float(ultimo["macd"]),
                volume=float(ultimo["volume"]),
                atr=float(ultimo["atr"]),
                support=float(ultimo["suporte"]),
                resistance=float(ultimo["resistencia"]),
                score=r.get("score_bruto", r["score"]),
                direction=r["direcao"],
                reasons=r["motivos"],
                news=noticias_ativo,
                chart_path=caminho,
            )
        except Exception as e:
            # Nunca deixa uma falha inesperada da IA derrubar o relatório.
            logging.error("Falha inesperada na análise de IA de %s: %s", ticker, e, exc_info=True)
            resultado_ia = None

        if resultado_ia is None:
            motivo = getattr(analisador, "ultimo_erro", None) or "motivo desconhecido"
            motivo_esc = html.escape(str(motivo), quote=False)
            blocos_ia.append(
                f"⚠️ <b>{ticker}</b> — IA indisponível ({motivo_esc}).\n"
                f"O placar técnico acima já é válido e não depende da IA."
            )
        else:
            provedor = getattr(analisador, "ultimo_provedor", "gemini")
            etiqueta_ia = "Nemotron 3 Ultra Free" if provedor == "nemotron" else "Gemini"
            linha_ia = f"{ticker}</b> — R$ {r['preco']:.2f} · <i>IA: {etiqueta_ia}</i>"
            if provedor == "gemini":
                motivo_nemotron = getattr(analisador, "ultimo_erro_nemotron", None)
                if motivo_nemotron:
                    motivo_curto = motivo_nemotron.split("): ")[-1][:120]
                    linha_ia += f"\n<i>(Nemotron: {motivo_curto})</i>"
            blocos_ia.append(
                f"<b>{linha_ia}\n"
                f"{analisador.format_telegram_message(resultado_ia)}"
            )

        time.sleep(8)  # respeita o limite de requisições/minuto do plano gratuito

    if not blocos_ia:
        return ""

    hoje = date.today().strftime("%d/%m/%Y")
    cabecalho = (
        f"🤖 <b>Análise da IA — {hoje}</b>\n"
        f"Segunda opinião do Gemini sobre os ativos com sinal técnico mais forte hoje "
        f"(interpreta o que o robô já calculou — não substitui o placar técnico).\n\n"
    )
    return cabecalho + "\n\n".join(blocos_ia)


def _formatar_veredito_trava(resposta_ia) -> str:
    """
    Extrai o veredito da IA sobre a trava e formata em texto claro.
    resposta_ia pode ser um dict (JSON parseado) — extrai os campos
    fazer_trava, nivel_certeza, recomendacao, explicacao, cuidados.
    """
    if not resposta_ia or not isinstance(resposta_ia, dict):
        return ""

    fazer = resposta_ia.get("fazer_trava")
    certeza = resposta_ia.get("nivel_certeza", "")
    recomendacao = resposta_ia.get("recomendacao", "")
    explicacao = resposta_ia.get("explicacao", "")
    cuidados = resposta_ia.get("cuidados", "")

    # Veredito com emoji
    if fazer is True:
        veredito = "✅ MONTA A TRAVA"
    elif fazer is False:
        veredito = "❌ NÃO MONTA"
    else:
        veredito = "⚠️ AVALIAR"

    certeza_txt = f" (certeza {certeza}%)" if certeza else ""
    linhas = [f"  <b>{veredito}</b>{certeza_txt}"]
    if recomendacao:
        linhas.append(f"  📋 {html.escape(str(recomendacao), quote=False)}")
    if explicacao:
        linhas.append(f"  💡 {html.escape(str(explicacao), quote=False)}")
    if cuidados:
        linhas.append(f"  ⚠️ {html.escape(str(cuidados), quote=False)}")
    return "\n".join(linhas)


def rodar_analise_trava_ia(resultados: list) -> str:
    """
    Monta a TRAVA (Bull/Bear Spread) com preços REAIS do opcoes.net.br para
    os ativos com score >= 8, e pede à IA (Nemotron/Gemini) uma leitura
    EXCLUSIVA sobre a estrutura — com certeza do que comprar/vender.

    Retorna string formatada para envio em mensagem separada, DEPOIS da
    análise de IA geral. Vazio se não houver ativos com score suficiente.
    """
    from fonte_opcoes import buscar_cadeia_estruturada
    from trava import montar_trava, formatar_trava

    candidatos = [
        r for r in resultados
        if r.get("score_bruto", r["score"]) >= 8 and r["direcao"] in ("compra", "venda")
    ]
    if not candidatos:
        return ""

    analisador = _montar_analisador_ia()
    blocos = []
    hoje = date.today().strftime("%d/%m/%Y")

    for r in candidatos[:4]:  # máximo 4 pra não estourar limite da IA
        ticker = r["ticker"]
        direcao = r["direcao"]
        preco = float(r["preco"])

        try:
            cadeia = buscar_cadeia_estruturada(ticker)
            trava = montar_trava(preco, direcao, cadeia_real=cadeia, ticker=ticker)
        except Exception as e:
            logging.warning("Falha ao montar trava real de %s: %s", ticker, e)
            continue

        bloco_trava = formatar_trava(trava, preco)

        # --- IA exclusiva sobre a trava ---
        opiniao_ia = ""
        provedor = ""
        if analisador is not None:
            try:
                venc_data = trava.get("vencimento_data") or "N/A"
                dias_uteis = trava.get("dias_vencimento") or "N/A"
                prompt_trava = (
                    f"Você é um especialista em opções da B3. Avalie EXCLUSIVAMENTE esta TRAVA "
                    f"para {ticker}.\n\n"
                    f"CONTEXTO (importante — não confunda a data):\n"
                    f"- Hoje é {hoje}.\n"
                    f"- O vencimento desta trava é {venc_data}, que fica a "
                    f"{dias_uteis} DIAS ÚTEIS da data de hoje (cerca de 1-2 meses, "
                    f"o próximo vencimento mensal normal da B3 — NÃO são anos).\n"
                    f"- Preço atual do ativo: R$ {preco:.2f}. Direção do robô: {direcao}.\n\n"
                    f"{bloco_trava}\n\n"
                    "Avalie se a trava vale a pena: custo, risco/retorno, liquidez e "
                    "realismo do prazo (confirme que o vencimento é o próximo mensal).\n"
                    "Responda APENAS com JSON, com os campos exatos:\n"
                    '{"fazer_trava": true/false, '
                    '"nivel_certeza": "0 a 100", '
                    '"recomendacao": "ex: comprar CALL 10.86 e vender CALL 11.31", '
                    '"explicacao": "por que sim ou por que nao", '
                    '"cuidados": "liquidez, vencimento, risco"}'
                )
                opiniao_ia = analisador._call_nemotron(prompt_trava)
                provedor = "Nemotron"
                if opiniao_ia:
                    opiniao_ia = _formatar_veredito_trava(opiniao_ia)
                else:
                    opiniao_ia = ""
                if not opiniao_ia:
                    resposta_g = analisador._call_gemini(
                        analisador._get_client(), prompt_trava, None,
                        modelo=analisador.model,
                    )
                    if resposta_g:
                        opiniao_ia = _formatar_veredito_trava(resposta_g)
                        provedor = "Gemini"
            except Exception as e:
                logging.warning("Falha na IA exclusiva da trava de %s: %s", ticker, e)
                opiniao_ia = ""

        if opiniao_ia:
            bloco_trava += (
                f"\n\n  🧠 <b>Veredito da IA ({provedor}):</b>\n"
                f"{opiniao_ia}"
            )

        blocos.append(f"🔒 <b>{ticker}</b> — R$ {preco:.2f} ({direcao.upper()})\n{bloco_trava}")
        time.sleep(6)

    if not blocos:
        return ""

    cabecalho = (
        f"🔒 <b>Trava de opções com preços reais — {hoje}</b>\n"
        f"Estrutura de duas pernas (risco limitado) para os ativos com sinal forte, "
        f"com prêmios do último pregão (opcoes.net.br) e leitura exclusiva da IA.\n\n"
    )
    return cabecalho + "\n\n".join(blocos)


def montar_gestao_posicoes(resultados: list) -> str:
    """
    Monta o bloco "GESTÃO DE POSIÇÕES ABERTAS" usando os preços do screener
    (quando o ativo está na watchlist) e baixando os demais via yfinance.
    Retorna string vazia se não houver posições abertas registradas.
    """
    posicoes = carregar_posicoes()
    if not posicoes:
        return ""

    precos = {r["ticker"]: float(r["preco"]) for r in resultados}

    faltantes = [t for t in posicoes if t not in precos]
    if faltantes:
        try:
            import pandas as pd
            import yfinance as yf

            df = yf.download(
                [f"{t}.SA" for t in faltantes], period="5d", interval="1d",
                auto_adjust=True, progress=False, group_by="ticker",
            )
            for t in faltantes:
                try:
                    d = df.get(t) or df.get(f"{t}.SA")
                    if d is None:
                        continue
                    if isinstance(d.columns, pd.MultiIndex):
                        d.columns = d.columns.get_level_values(0)
                    d = d.rename(columns=str.lower)
                    precos[t] = float(d["close"].iloc[-1])
                except Exception:
                    precos[t] = None
        except Exception as e:
            logging.warning("Falha ao buscar preços das posições abertas: %s", e)

    return formatar_gestao_todas(posicoes, precos)


def gerar_e_enviar_relatorio(watchlist=None, periodo=None, nivel_detalhe=None,
                              arquivo_estado="estado.json", atr_mult: float = 1.5,
                              risco_retorno: float = 2.0, titulo: str = "Relatório B3",
                              nota_extra: str = "", usar_curto_prazo: bool = False,
                              projetar_volume: bool = False, confirmar_intradiario: bool = False,
                              risco_maximo_atr_mult: float = None,
                              margem_saida_estado: int = None):

    validar_configuracao()

    watchlist = watchlist or config.WATCHLIST
    periodo = periodo or config.PERIODO_HISTORICO
    nivel_detalhe = nivel_detalhe if nivel_detalhe is not None else config.NIVEL_DETALHE
    risco_maximo_atr_mult = risco_maximo_atr_mult if risco_maximo_atr_mult is not None else config.RISCO_MAXIMO_ATR_MULT
    margem_saida_estado = margem_saida_estado if margem_saida_estado is not None else config.MARGEM_SAIDA_ESTADO

    logging.info("%s — Rodando screener...", titulo)
    resultados = rodar_screener(
        watchlist=watchlist, periodo=periodo,
        usar_curto_prazo=usar_curto_prazo, projetar_volume=projetar_volume,
        confirmar_intradiario=confirmar_intradiario,
    )
    hoje = date.today().strftime("%d/%m/%Y")

    if not resultados:
        enviar_mensagem(
            config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID,
            f"📊 <b>{titulo} — {hoje}</b>\nNão consegui baixar dados de nenhum ativo hoje."
        )
        return

    logging.info("Gerando gráficos...")
    os.makedirs(PASTA_GRAFICOS, exist_ok=True)
    caminhos_graficos = []
    for r in resultados:
        caminho = os.path.join(PASTA_GRAFICOS, f"{r['ticker']}_{arquivo_estado.replace('.json','')}.png")
        plotar_grafico(r["df"], r["ticker"], caminho)
        caminhos_graficos.append(caminho)

    logging.info("Montando resumo técnico...")
    estado = carregar_estado(arquivo_estado)
    blocos = []
    for r in resultados:
        # Guarda o score bruto do dia (usado pela IA) antes da suavização
        r["score_bruto"] = r["score"]
        # Suaviza o score com os últimos dias (evita sinal 10/10 virar 4/10
        # no dia seguinte por oscilação comum do mercado)
        score_estavel = score_suavizado(estado, r["ticker"], r["score"])
        r["score"] = score_estavel

        caminho = os.path.join(PASTA_GRAFICOS, f"{r['ticker']}_{arquivo_estado.replace('.json','')}.png")
        blocos.append(montar_bloco_resumo(
            r, estado, nivel_detalhe,
            atr_mult=atr_mult, risco_retorno=risco_retorno,
            risco_maximo_atr_mult=risco_maximo_atr_mult,
            margem_saida_estado=margem_saida_estado,
            caminho_imagem=caminho,
        ))
        estado = atualizar_estado(
            estado, r["ticker"], r["score"], r["direcao"],
            nivel_detalhe, margem_saida=margem_saida_estado,
        )
    salvar_estado(estado, arquivo_estado)

    # --- Diário de sinais: registra ENTRAR emitido e atualiza sinais antigos ---
    try:
        from diario_sinais import registrar_sinal, atualizar_resultados
        for r in resultados:
            if r["score"] >= 8 and r["direcao"] in ("compra", "venda"):
                registrar_sinal(r["ticker"], r["direcao"], r["score"], r["preco"])
        # Busca preços atuais dos ativos da watchlist para avaliar sinais antigos
        precos_diario = {}
        for t in config.WATCHLIST:
            try:
                preco = float(rodar_screener([t], periodo="5d")[0]["preco"])
                precos_diario[t] = preco
            except Exception:
                pass
        atualizar_resultados(precos_diario)
    except Exception as e:
        logging.warning("Falha ao atualizar diário de sinais: %s", e)


    cabecalho_msg = f"📊 <b>{titulo} — {hoje}</b>\n"
    if nota_extra:
        cabecalho_msg += f"{nota_extra}\n"

    # --- Resumo executivo de vereditos no topo ---
    contagem = {"ENTRAR": [], "AGUARDAR": [], "EVITAR": [], "SEM SINAL": []}
    for r in resultados:
        v = determinar_veredito(r["score"], r["direcao"])["veredito"]
        contagem[v].append(r["ticker"])

    resumo_vereditos = []
    if contagem["ENTRAR"]:
        resumo_vereditos.append(f"🟢 <b>ENTRAR:</b> {', '.join(contagem['ENTRAR'])}")
    if contagem["AGUARDAR"]:
        resumo_vereditos.append(f"🟡 <b>AGUARDAR:</b> {', '.join(contagem['AGUARDAR'])}")
    if contagem["EVITAR"]:
        resumo_vereditos.append(f"🔴 <b>EVITAR:</b> {', '.join(contagem['EVITAR'])}")
    if contagem["SEM SINAL"]:
        resumo_vereditos.append(f"⚪ <b>SEM SINAL:</b> {', '.join(contagem['SEM SINAL'])}")
    if resumo_vereditos:
        cabecalho_msg += "\n" + "\n".join(resumo_vereditos) + "\n"

    # --- Gestão de posições abertas: o que fazer com o que já está operando ---
    logging.info("Montando gestão de posições abertas...")
    gestao_posicoes = montar_gestao_posicoes(resultados)
    if gestao_posicoes:
        cabecalho_msg += "\n" + gestao_posicoes + "\n"

    cabecalho_msg += (
        f"\nRanking de {len(resultados)} ativo(s) — do maior sinal pro menor.\n\n"
    )

    mensagem_final = cabecalho_msg + "\n\n".join(blocos)

    logging.info("Enviando álbum de gráficos...")
    enviar_album(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, caminhos_graficos)

    logging.info("Enviando resumo técnico...")
    LIMITE = 3800
    if len(mensagem_final) <= LIMITE:
        enviar_mensagem(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, mensagem_final)
    else:
        partes = []
        atual = ""
        for bloco in mensagem_final.split("\n\n"):
            if len(atual) + len(bloco) + 2 > LIMITE:
                partes.append(atual)
                atual = bloco
            else:
                atual = f"{atual}\n\n{bloco}" if atual else bloco
        if atual:
            partes.append(atual)
        for parte in partes:
            enviar_mensagem(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, parte)

    # --- IA analisa visualmente e manda mensagem separada no final ---
    logging.info("Rodando análise visual da IA...")
    mensagem_ia = rodar_analise_ia(resultados, arquivo_estado)
    if mensagem_ia:
        LIMITE_IA = 3800
        if len(mensagem_ia) <= LIMITE_IA:
            enviar_mensagem(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, mensagem_ia)
        else:
            partes_ia = []
            atual = ""
            for bloco in mensagem_ia.split("\n\n"):
                if len(atual) + len(bloco) + 2 > LIMITE_IA:
                    partes_ia.append(atual)
                    atual = bloco
                else:
                    atual = f"{atual}\n\n{bloco}" if atual else bloco
            if atual:
                partes_ia.append(atual)
            for parte in partes_ia:
                enviar_mensagem(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, parte)

    # --- TRAVA com preços reais + IA exclusiva: mensagem separada depois da IA ---
    logging.info("Montando travas com preços reais...")
    mensagem_trava = rodar_analise_trava_ia(resultados)
    if mensagem_trava:
        LIMITE_TRAVA = 3800
        if len(mensagem_trava) <= LIMITE_TRAVA:
            enviar_mensagem(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, mensagem_trava)
        else:
            partes_tr = []
            atual = ""
            for bloco in mensagem_trava.split("\n\n"):
                if len(atual) + len(bloco) + 2 > LIMITE_TRAVA:
                    partes_tr.append(atual)
                    atual = bloco
                else:
                    atual = f"{atual}\n\n{bloco}" if atual else bloco
            if atual:
                partes_tr.append(atual)
            for parte in partes_tr:
                enviar_mensagem(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, parte)

    logging.info("%s — Concluído.", titulo)


if __name__ == "__main__":
    gerar_e_enviar_relatorio(
        watchlist=config.WATCHLIST,
        periodo=config.PERIODO_HISTORICO,
        nivel_detalhe=config.NIVEL_DETALHE,
        arquivo_estado="estado.json",
        titulo="Relatório B3 — Manhã",
    )
