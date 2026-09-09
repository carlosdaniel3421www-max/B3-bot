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
     respeita o score final e os bloqueios de entrada.
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
from posicoes import (
    carregar_posicoes, formatar_gestao_todas, salvar_proposta_entrada,
    carregar_propostas, salvar_propostas,
)
from b3_swing_analyzer import sugerir_stop_alvo, plotar_grafico, determinar_veredito, avaliar_regime_ibov
from trava import montar_trava, formatar_trava
from telegram_utils import enviar_mensagem, enviar_album
from setups import _data, classificar_setup, reutilizar_candidato
from carteira import avaliar_carteira, avaliar_nova_operacao, formatar_resumo_carteira

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

    # Sem Gemini, o Nemotron ainda pode analisar o contexto textual.
    sem_gemini = not getattr(config, "GEMINI_API_KEY", "")
    if sem_gemini:
        logging.warning("GEMINI_API_KEY ausente: leitura visual indisponivel; Nemotron textual depende de CARLOS.")

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
    resultado["entrada_permitida"] = veredito["veredito"] == "ENTRAR"
    resultado["motivo_bloqueio"] = "" if resultado["entrada_permitida"] else veredito["descricao"]
    risco_noticias = {}
    aviso_calendario = ""
    cancelamento = ""
    resultado["estado_entrada"] = "aguardar"
    plano_setup = None
    plano_reutilizado = False
    if direcao in ("compra", "venda") and (score >= nivel_detalhe or resultado["entrada_permitida"]):
        nome_empresa = config.NOME_EMPRESA.get(ticker, ticker)
        risco_noticias = checar_risco_noticias(nome_empresa)
        if risco_noticias["bloquear_entrada"]:
            cancelamento = f"notícia de risco: {risco_noticias['alertas'][0]['motivo']}"
        else:
            resultado_trimestral = checar_resultado_proximo(ticker, config.DIAS_MINIMOS_ANTES_RESULTADO)
            if resultado_trimestral.get("info_disponivel") is False:
                aviso_calendario = "Calendario de resultados indisponivel: confirme a agenda antes de operar."
            if resultado_trimestral["tem_resultado_proximo"]:
                cancelamento = (
                    f"resultado trimestral em {resultado_trimestral['dias_ate_resultado']} dia(s) "
                    f"({resultado_trimestral['data_resultado']})"
                )
    if resultado["entrada_permitida"] and not cancelamento and config.EXIGIR_SETUP:
        plano_setup = classificar_setup(resultado["df"], direcao)
        if plano_setup["estado"] != "candidato":
            proposta = carregar_propostas().get(ticker.upper(), {})
            if (isinstance(proposta, dict) and proposta.get("estado_entrada") == "candidato"
                    and proposta.get("direcao") == direcao):
                anterior = reutilizar_candidato(
                    proposta.get("plano_setup"), resultado["df"], direcao, date.today(),
                )
                if anterior is not None:
                    plano_setup = anterior
                    plano_reutilizado = True
        if plano_setup["estado"] == "candidato":
            try:
                idade = (date.today() - _data(plano_setup.get("data_sinal"))).days
                if not 0 <= idade <= 4:
                    cancelamento = "Setup expirado ou com data de sinal futura."
            except (ValueError, TypeError, OverflowError):
                cancelamento = "Setup com data de sinal invalida."
        resultado["plano_setup"] = plano_setup
        if plano_setup["estado"] != "candidato":
            cancelamento = "Setup: " + plano_setup["motivo"]
        elif not cancelamento:
            carteira_atual = carregar_posicoes()
            resultado["carteira_atual"] = carteira_atual
            risco_carteira = avaliar_carteira(
                carteira_atual, config.CAPITAL_DISPONIVEL,
                config.RISCO_MAX_CARTEIRA_PCT, config.EXPOSICAO_MAX_SETOR_PCT,
                config.SETORES, date.today().isoformat(),
            )
            if not risco_carteira["permite_nova_operacao"]:
                cancelamento = "Carteira incompleta ou fora dos limites; consulte /carteira."
            elif ticker in carteira_atual:
                cancelamento = "Ja existe posicao neste ativo; nao acumular uma segunda proposta."
            else:
                resultado["estado_entrada"] = "candidato"
                veredito = {"veredito": "CANDIDATO", "emoji": "🟡",
                            "descricao": "Setup identificado: aguarde gatilho e valide risco antes de operar."}
    if cancelamento:
        resultado["entrada_permitida"] = False
        resultado["motivo_bloqueio"] = cancelamento
        veredito = {"veredito": "EVITAR", "emoji": "🔴", "descricao": "Entrada cancelada pelos filtros de risco."}
    resultado["veredito"] = veredito
    resultado["noticias"] = risco_noticias.get("noticias", [])

    if not resultado["entrada_permitida"]:
        try:
            propostas = carregar_propostas()
            if ticker.upper() in propostas:
                del propostas[ticker.upper()]
                salvar_propostas(propostas)
        except Exception as e:
            logging.warning("Falha ao remover proposta de %s: %s", ticker, e)

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
    if aviso_calendario:
        motivos_txt += "\n  " + aviso_calendario

    if cancelamento:
        return (
            f"{cabecalho}\n{motivos_txt}\n"
            f"  🚫 <b>CANCELADO</b> — {html.escape(cancelamento, quote=False)}"
        )

    # Candidato precisa persistir o plano mesmo com detalhes visuais reduzidos.
    if direcao == "neutro" or (score < nivel_detalhe and not plano_setup):
        return f"{cabecalho}\n{motivos_txt}"

    df = resultado["df"]
    stop_alvo = ({"preco_entrada": plano_setup["gatilho"], "stop": plano_setup["stop"], "alvo": plano_setup["alvo"]}
                 if plano_setup and plano_setup["estado"] == "candidato" else sugerir_stop_alvo(df, direcao, atr_mult=atr_mult,
                                    risco_retorno=risco_retorno,
                                    risco_maximo_atr_mult=risco_maximo_atr_mult))
    resultado["plano_tecnico"] = stop_alvo

    # Guarda a proposta de entrada: você decide se registra (respondendo
    # "/registrar TICKER" no Telegram) ou ignora. Nada é registrado sozinho.
    if resultado["entrada_permitida"] and not plano_reutilizado:
        try:
            if plano_setup:
                salvar_proposta_entrada(ticker, direcao, stop_alvo["preco_entrada"],
                                        stop_alvo["stop"], stop_alvo["alvo"], plano_setup=plano_setup)
            else:
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

    if opcao.get("premio") is not None:
        origem = "cotacao OpLab; confirme execucao" if opcao.get("fonte") == "oplab" else "estimativa teorica, nao cotacao"
        linha_premio = f"R$ {opcao['premio']:.2f} — {origem}"
    else:
        linha_premio = "estimativa teórica (sem cotação real)"

    plano += (
        f"  <b>Opção:</b> {opcao['tipo_opcao']} strike ~R$ {opcao['strike_sugerido_aprox']}, "
        f"venc. {opcao['vencimento_sugerido']} — {explicacao_opcao}\n"
        f"  <i>Prêmio: {linha_premio}</i>\n"
        f"  ⚠️ Confirme liquidez antes de operar.\n"
    )
    if plano_setup:
        plano += (f"  Setup: {plano_setup['setup']} | Gatilho: R$ {plano_setup['gatilho']:.2f}\n"
                  f"  Data do sinal: {plano_setup['data_sinal']} | Alvo "
                  f"{'teorico 2R' if plano_setup['alvo_teorico'] else 'em barreira historica'}\n"
                  "  Validade: ate 4 dias corridos apos o sinal, somente sessao negociavel.\n")
        risco_novo = avaliar_nova_operacao(
            resultado["carteira_atual"],
            {"ticker": ticker, "direcao": direcao, "preco_entrada": stop_alvo["preco_entrada"],
             "stop": stop_alvo["stop"], "quantidade": posicao.get("quantidade_acoes", 0),
             "data_entrada": date.today().isoformat()},
            config.CAPITAL_DISPONIVEL, config.RISCO_MAX_CARTEIRA_PCT,
            config.EXPOSICAO_MAX_SETOR_PCT, config.SETORES, date.today().isoformat(),
        )
        if not risco_novo["permite_nova_operacao"]:
            plano += "  Acao com a quantidade sugerida excede limites ou tem dados incompletos; reduza/reavalie antes de operar.\n"
    if resultado["estado_entrada"] == "candidato":
        plano += (f"  Confira gatilho com /gatilho {ticker} PRECO_ATUAL ATR DATA_COTACAO.\n"
                  "  Preco informado manualmente nao comprova execucao nem atualidade.\n")
    elif resultado["entrada_permitida"]:
        plano += f"  ✅ Se ENTRAR, registre: responda <b>/registrar {ticker}</b> no chat."
    else:
        plano += "  ⏳ Plano de referência: aguarde confirmação antes de entrar."

    if risco_noticias.get("positivas"):
        plano += f"\n  ✅ {html.escape(risco_noticias['positivas'][0]['titulo'], quote=False)}"

    return plano


def _montar_analisador_ia() -> AIAnalyzer | None:
    """Cria o AIAnalyzer (Gemini) se USAR_IA_ANALISE e GEMINI_API_KEY estiverem configurados."""
    if not getattr(config, "USAR_IA_ANALISE", True):
        return None

    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key and not getattr(config, "CARLOS", ""):
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


def rodar_analise_ia(resultados: list, arquivo_estado: str, regime_ibov: dict = None) -> str:
    """
    Roda a IA (Gemini) em todos os ativos com score >= SCORE_MINIMO_IA e monta
    uma mensagem consolidada de segunda opinião, respeitando os bloqueios de
    entrada, independente de estado ou alertas anteriores.

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
        if r["score"] >= SCORE_MINIMO_IA and r["direcao"] != "neutro"
        and r.get("entrada_permitida", True)
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
                noticias_ativo = (r["noticias"] if "noticias" in r
                                  else checar_risco_noticias(nome_empresa).get("noticias", []))
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
                score=r["score"],
                direction=r["direcao"],
                reasons=r["motivos"],
                news=noticias_ativo,
                chart_path=caminho,
                extra_context={
                    "regime_ibov": (regime_ibov or {}).get("texto_curto", ""),
                    "aviso_ibov": (regime_ibov or {}).get("texto_aviso", ""),
                    "estado_entrada": r.get("estado_entrada", "sinal_tecnico"),
                    "setup": r.get("plano_setup"),
                    "forca_relativa": r.get("forca_relativa"),
                    "prazo_opcoes_dias_corridos": [config.OPCOES_MIN_DIAS_CORRIDOS, config.OPCOES_MAX_DIAS_CORRIDOS],
                    "instrucao": "Candidato nao e entrada executada. Nao libere compra/venda a mercado antes do gatilho e da conferencia da carteira.",
                },
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
                    linha_ia += f"\n<i>(Nemotron: {html.escape(motivo_curto, quote=False)})</i>"
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
        veredito = "✅ IA FAVORAVEL (opiniao, nao ordem)"
    elif fazer is False:
        veredito = "❌ NÃO MONTA"
    else:
        veredito = "⚠️ AVALIAR"

    certeza_txt = ""
    try:
        valor = float(certeza)
        if not isinstance(certeza, bool) and 0 <= valor <= 100:
            certeza_txt = f" (confianca subjetiva {valor:g}%, nao calibrada)"
    except (TypeError, ValueError):
        pass
    linhas = [f"  <b>{veredito}</b>{certeza_txt}"]
    if recomendacao:
        linhas.append(f"  📋 {html.escape(str(recomendacao), quote=False)}")
    if explicacao:
        linhas.append(f"  💡 {html.escape(str(explicacao), quote=False)}")
    if cuidados:
        linhas.append(f"  ⚠️ {html.escape(str(cuidados), quote=False)}")
    return "\n".join(linhas)


def rodar_analise_trava_ia(resultados: list, regime_ibov: dict = None) -> str:
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
        if r["score"] >= 8 and r["direcao"] in ("compra", "venda")
        and r.get("entrada_permitida", True)
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
            if config.EXIGIR_SETUP:
                from selecao_trava import selecionar_trava_por_tese
                selecao = selecionar_trava_por_tese(
                    cadeia, preco, direcao, r["plano_tecnico"]["alvo"],
                )
                trava = selecao["trava"]
                if trava is None:
                    blocos.append(f"{html.escape(ticker)}: sem trava adequada a tese. {html.escape(selecao['motivo'])}")
                    continue
                candidato = {"ticker": ticker, "tipo_operacao": "trava", "direcao": direcao,
                             "preco_entrada": trava["custo_liquido"], "quantidade": trava["contratos"],
                             "vencimento": trava["vencimento_data"], "data_entrada": date.today().isoformat()}
                risco = avaliar_nova_operacao(
                    carregar_posicoes(), candidato, config.CAPITAL_DISPONIVEL,
                    config.RISCO_MAX_CARTEIRA_PCT, config.EXPOSICAO_MAX_SETOR_PCT,
                    config.SETORES, date.today().isoformat(),
                )
                if not risco["permite_nova_operacao"]:
                    blocos.append(f"{html.escape(ticker)}: trava bloqueada pelos limites/dados da carteira; consulte /carteira.")
                    continue
            else:
                trava = montar_trava(preco, direcao, cadeia_real=cadeia, ticker=ticker,
                                    permitir_estimativa=False)
        except Exception as e:
            logging.warning("Falha ao montar trava real de %s: %s", ticker, e)
            blocos.append(f"{html.escape(ticker)}: sem estrutura real elegivel entre "
                          f"{config.OPCOES_MIN_DIAS_CORRIDOS} e {config.OPCOES_MAX_DIAS_CORRIDOS} dias corridos. "
                          "Nao substituir por vencimento mais distante ou simulacao.")
            continue

        bloco_trava = formatar_trava(trava, preco)
        if config.EXIGIR_SETUP:
            from cenarios_trava import analisar_cenarios_trava, formatar_cenarios_trava
            bloco_trava += "\n" + formatar_cenarios_trava(analisar_cenarios_trava(
                trava, preco, r["plano_tecnico"]["alvo"], r["plano_tecnico"]["stop"],
            ))
            bloco_trava += "\nEstrutura candidata: depende do gatilho na acao e de novas cotacoes das duas pernas."

        # --- IA exclusiva sobre a trava ---
        opiniao_ia = ""
        provedor = ""
        if analisador is not None:
            try:
                venc_data = trava.get("vencimento_data") or "N/A"
                dias_uteis = trava.get("dias_vencimento") or "N/A"
                contexto_ibov = ""
                if regime_ibov and regime_ibov.get("regime") != "indisponivel":
                    contexto_ibov = (
                        f"- Regime do Ibovespa: {regime_ibov.get('texto_curto', '')}. "
                        f"{regime_ibov.get('texto_aviso', '')}\n"
                    )
                prompt_trava = (
                    f"Você é um especialista em opções da B3. Avalie EXCLUSIVAMENTE esta TRAVA "
                    f"para {ticker}.\n\n"
                    "Estrutura CANDIDATA: nao e autorizacao de ordem. "
                    "Depende de gatilho, cotacoes atualizadas e limites da carteira.\n"
                    f"CONTEXTO (importante — não confunda a data):\n"
                    f"- Hoje é {hoje}.\n"
                    f"- O vencimento desta trava é {venc_data}, que fica a "
                    f"{dias_uteis} dias uteis segundo os dados da estrutura. "
                    f"Dias CORRIDOS ate o vencimento: {trava.get('dias_corridos', 'N/A')}. "
                    f"Politica de novas entradas: {config.OPCOES_MIN_DIAS_CORRIDOS} a "
                    f"{config.OPCOES_MAX_DIAS_CORRIDOS} dias corridos, nunca mais de um mes. "
                    "O horizonte da tese deve ser menor que o prazo restante; nao recomendar esperar meses. "
                    f"Se a data nao estiver informada, nao deduza um vencimento.\n"
                    f"{contexto_ibov}"
                    f"- Preço atual do ativo: R$ {preco:.2f}. Direção do robô: {direcao}.\n\n"
                    f"{bloco_trava}\n\n"
                    "Avalie se a trava vale a pena: custo, risco/retorno, liquidez e "
                    "realismo do prazo informado, sem presumir que seja o proximo mensal.\n"
                    "REGRAS IMPORTANTES:\n"
                    "- Sobre LIQUIDEZ: use APENAS os dados de negócios/volume que aparecem "
                    "na trava acima. Negocios historicos nao garantem liquidez ou execucao atual.\n"
                    "- Exija conferencia de bid/ask, quantidade e ambas as pernas. "
                    "Premios estimados nao sao ofertas executaveis; risco limitado nao e risco baixo.\n"
                    "- Considere também o REGIME DO IBOVESPA acima: se o mercado está "
                    "lateral/choppy, pondere que rompimentos tendem a falhar.\n"
                    "- Baseie o veredito principalmente em: custo vs ganho máximo, "
                    "relação risco/retorno, e se o preço está perto da zona de lucro.\n"
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
                    motivo = getattr(analisador, "ultimo_erro", "motivo desconhecido")
                    logging.info("Nemotron na trava de %s falhou (%s) — usando Gemini", ticker, motivo)
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
        f"🔒 <b>Trava de opções — {hoje}</b>\n"
        f"Estrutura de duas pernas (risco limitado) para os ativos com sinal forte, "
        f"com referencia de fechamento quando disponivel, ou estimativa teorica identificada. "
        f"Nao sao precos executaveis garantidos.\n\n"
    )
    return cabecalho + "\n\n".join(blocos)


def montar_gestao_posicoes(resultados: list) -> str:
    """
    Monta a gestao com fechamentos nao ajustados, como /status e /posicoes.
    Historico ajustado do screener nao e cotacao para limites registrados.
    Retorna string vazia se não houver posições abertas registradas.
    """
    posicoes = carregar_posicoes()
    if not posicoes:
        return ""

    acoes = {t: p for t, p in posicoes.items() if p.get("tipo_operacao") != "trava"}
    precos = {}
    if acoes:
        from telegram_bot import _precos_posicoes
        precos = _precos_posicoes(acoes)

    return formatar_gestao_todas(posicoes, precos)


def gerar_e_enviar_relatorio(watchlist=None, periodo=None, nivel_detalhe=None,
                              arquivo_estado="estado.json", atr_mult: float = 1.5,
                              risco_retorno: float = 2.0, titulo: str = "Relatório B3",
                              nota_extra: str = "", usar_curto_prazo: bool = False,
                              projetar_volume: bool = False, confirmar_intradiario: bool = False,
                              risco_maximo_atr_mult: float = None,
                              margem_saida_estado: int = None):

    validar_configuracao()

    watchlist = config.WATCHLIST if watchlist is None else watchlist
    periodo = periodo or config.PERIODO_HISTORICO
    nivel_detalhe = nivel_detalhe if nivel_detalhe is not None else config.NIVEL_DETALHE
    risco_maximo_atr_mult = risco_maximo_atr_mult if risco_maximo_atr_mult is not None else config.RISCO_MAXIMO_ATR_MULT
    margem_saida_estado = margem_saida_estado if margem_saida_estado is not None else config.MARGEM_SAIDA_ESTADO

    logging.info("%s — Rodando screener...", titulo)
    regime_ibov = avaliar_regime_ibov()
    resultados = rodar_screener(
        watchlist=watchlist, periodo=periodo,
        usar_curto_prazo=usar_curto_prazo, projetar_volume=projetar_volume,
        confirmar_intradiario=confirmar_intradiario,
        regime_ibov=regime_ibov,
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
        # Score atual do screener, já com os filtros, antes da média.
        r["score_bruto"] = r["score"]
        score_estavel = score_suavizado(estado, r["ticker"], r["score_bruto"], r["direcao"])
        # A média nunca pode desfazer tetos de risco ou promover um sinal fraco.
        r["score"] = min(score_estavel, r["score_bruto"])
        r["motivos"] = r.get("motivos", [])

    # Reordena pelo score SUAVIZADO (decrescente), com tiebreaker pelo bruto
    resultados.sort(key=lambda r: (r["score"], r.get("score_bruto", r["score"])), reverse=True)

    for r in resultados:
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
            if r["entrada_permitida"] and r.get("estado_entrada") != "candidato":
                registrar_sinal(r["ticker"], r["direcao"], r["score"], r["preco"])
        # O diario busca o fechamento da sessao-alvo, nao a cotacao atual.
        atualizar_resultados({})
    except Exception as e:
        logging.warning("Falha ao atualizar diário de sinais: %s", e)


    cabecalho_msg = f"📊 <b>{titulo} — {hoje}</b>\n"
    cabecalho_msg += (f"Novas opcoes: {config.OPCOES_MIN_DIAS_CORRIDOS} a "
                     f"{config.OPCOES_MAX_DIAS_CORRIDOS} dias corridos ate vencimento.\n")
    if nota_extra:
        cabecalho_msg += f"{nota_extra}\n"

    # --- Status do Ibovespa (regime de mercado) no topo ---
    if regime_ibov.get("regime") != "indisponivel":
        cabecalho_msg += f"📊 <b>Ibovespa:</b> {regime_ibov.get('texto_curto', '')}\n"
        aviso_ibov = regime_ibov.get("texto_aviso", "")
        if aviso_ibov:
            cabecalho_msg += f"⚠️ {aviso_ibov}\n"
    else:
        cabecalho_msg += "Ibovespa indisponivel: filtro de mercado nao aplicado nesta leitura.\n"

    # --- Resumo executivo de vereditos no topo ---
    contagem = {"ENTRAR": [], "CANDIDATO": [], "AGUARDAR": [], "EVITAR": [], "SEM SINAL": []}
    for r in resultados:
        v = r["veredito"]["veredito"]
        contagem[v].append(r["ticker"])

    resumo_vereditos = []
    if contagem["CANDIDATO"]:
        resumo_vereditos.append(f"🟡 <b>CANDIDATOS (aguardar gatilho):</b> {', '.join(contagem['CANDIDATO'])}")
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
    if config.EXIGIR_SETUP:
        cabecalho_msg += "\n" + formatar_resumo_carteira(avaliar_carteira(
            carregar_posicoes(), config.CAPITAL_DISPONIVEL, config.RISCO_MAX_CARTEIRA_PCT,
            config.EXPOSICAO_MAX_SETOR_PCT, config.SETORES, date.today().isoformat(),
        )) + "\n"
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
    mensagem_ia = rodar_analise_ia(resultados, arquivo_estado, regime_ibov)
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
    mensagem_trava = rodar_analise_trava_ia(resultados, regime_ibov)
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
