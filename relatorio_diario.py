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

import os
import time
import logging
from datetime import date

import config
from screener import rodar_screener
from noticias import checar_risco_noticias
from opcoes import sugerir_parametros_opcao
from calendario import checar_resultado_proximo
from gestao_risco import calcular_tamanho_posicao
from estado import carregar_estado, salvar_estado, eh_alerta_novo, atualizar_estado
from ai_analyzer import AIAnalyzer
from posicoes import carregar_posicoes, formatar_gestao_todas, salvar_proposta_entrada
from b3_swing_analyzer import sugerir_stop_alvo, plotar_grafico, determinar_veredito
from telegram_utils import enviar_mensagem, enviar_album

# Garante que os logs de erro do ai_analyzer.py (status HTTP, mensagem,
# stacktrace) apareçam no console/log do GitHub Actions. Não interfere em
# nenhum print() já existente no projeto.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

PASTA_GRAFICOS = "graficos_tmp"
SCORE_MINIMO_IA = 7  # IA analisa todos os ativos com score >= esse valor


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

    if not eh_alerta_novo(estado, ticker, score, direcao, nivel_detalhe):
        data_alerta = estado.get(ticker, {}).get("data_primeiro_alerta", "?")
        return f"{cabecalho}\n{motivos_txt}\n  ↻ Sinal mantido desde {data_alerta} — plano já enviado."

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

    opcao = sugerir_parametros_opcao(resultado["preco"], direcao)
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

    plano += (
        f"  <b>Opção:</b> {opcao['tipo_opcao']} strike ~R$ {opcao['strike_sugerido_aprox']}, "
        f"venc. {opcao['vencimento_sugerido']} — {explicacao_opcao}\n"
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

    return AIAnalyzer(
        api_key=api_key,
        model=getattr(config, "GEMINI_MODEL", None),
        timeout_seconds=getattr(config, "GEMINI_TIMEOUT_SECONDS", 45),
        max_retries=getattr(config, "GEMINI_MAX_RETRIES", 3),
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

    candidatos = [r for r in resultados if r["score"] >= SCORE_MINIMO_IA and r["direcao"] != "neutro"]
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

            print(f"  [IA] Analisando {ticker}...")
            resultado_ia = analisador.analyze_asset(
                ticker=ticker,
                current_price=float(r["preco"]),
                ema21=float(ultimo["sma21"]),      # média móvel curta já calculada pelo robô (SMA21)
                ema200=float(ultimo["sma200"]),    # média móvel longa já calculada pelo robô (SMA200)
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
            )
        except Exception as e:
            # Nunca deixa uma falha inesperada da IA derrubar o relatório.
            logging.error("Falha inesperada na análise de IA de %s: %s", ticker, e, exc_info=True)
            resultado_ia = None

        if resultado_ia is None:
            motivo = getattr(analisador, "ultimo_erro", None) or "motivo desconhecido"
            blocos_ia.append(
                f"⚠️ <b>{ticker}</b> — IA indisponível ({motivo}).\n"
                f"O placar técnico acima já é válido e não depende da IA."
            )
        else:
            blocos_ia.append(
                f"<b>{ticker}</b> — R$ {r['preco']:.2f}\n"
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

    watchlist = watchlist or config.WATCHLIST
    periodo = periodo or config.PERIODO_HISTORICO
    nivel_detalhe = nivel_detalhe if nivel_detalhe is not None else config.NIVEL_DETALHE
    risco_maximo_atr_mult = risco_maximo_atr_mult if risco_maximo_atr_mult is not None else config.RISCO_MAXIMO_ATR_MULT
    margem_saida_estado = margem_saida_estado if margem_saida_estado is not None else config.MARGEM_SAIDA_ESTADO

    print(f"[{titulo}] Rodando screener...")
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

    print("Gerando gráficos...")
    os.makedirs(PASTA_GRAFICOS, exist_ok=True)
    caminhos_graficos = []
    for r in resultados:
        caminho = os.path.join(PASTA_GRAFICOS, f"{r['ticker']}_{arquivo_estado.replace('.json','')}.png")
        plotar_grafico(r["df"], r["ticker"], caminho)
        caminhos_graficos.append(caminho)

    print("Montando resumo técnico...")
    estado = carregar_estado(arquivo_estado)
    blocos = []
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
    print("Montando gestão de posições abertas...")
    gestao_posicoes = montar_gestao_posicoes(resultados)
    if gestao_posicoes:
        cabecalho_msg += "\n" + gestao_posicoes + "\n"

    cabecalho_msg += (
        f"\nRanking de {len(resultados)} ativo(s) — do maior sinal pro menor.\n\n"
    )

    mensagem_final = cabecalho_msg + "\n\n".join(blocos)

    print("Enviando álbum de gráficos...")
    enviar_album(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, caminhos_graficos)

    print("Enviando resumo técnico...")
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
    print("Rodando análise visual da IA...")
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

    print(f"[{titulo}] Concluído.")


if __name__ == "__main__":
    gerar_e_enviar_relatorio(
        watchlist=config.WATCHLIST,
        periodo=config.PERIODO_HISTORICO,
        nivel_detalhe=config.NIVEL_DETALHE,
        arquivo_estado="estado.json",
        titulo="Relatório B3 — Manhã",
    )
