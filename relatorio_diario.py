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
from datetime import date

import config
from screener import rodar_screener
from noticias import checar_risco_noticias
from opcoes import sugerir_parametros_opcao
from calendario import checar_resultado_proximo
from gestao_risco import calcular_tamanho_posicao
from estado import carregar_estado, salvar_estado, eh_alerta_novo, atualizar_estado
from ia_analise import analisar_ativo_visualmente, formatar_analise_ia
from b3_swing_analyzer import sugerir_stop_alvo, plotar_grafico
from telegram_utils import enviar_mensagem, enviar_album

PASTA_GRAFICOS = "graficos_tmp"
SCORE_MINIMO_IA = 4  # IA analisa todos os ativos com score >= esse valor


def montar_bloco_resumo(resultado: dict, estado: dict, nivel_detalhe: int,
                         atr_mult: float = 1.5, risco_retorno: float = 2.0,
                         risco_maximo_atr_mult: float = 3.0,
                         margem_saida_estado: int = 2,
                         caminho_imagem: str = None) -> str:
    ticker = resultado["ticker"]
    score = resultado["score"]
    direcao = resultado["direcao"]

    if direcao == "neutro":
        emoji, palavra = "⚪", "NEUTRO"
    elif direcao == "compra":
        emoji, palavra = "🟢", "COMPRA"
    else:
        emoji, palavra = "🔴", "VENDA"

    cabecalho = f"{emoji} <b>{ticker} — {score}/10 ({palavra})</b>"
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
        f"  ⚠️ Confirme liquidez antes de operar."
    )

    if risco_noticias.get("positivas"):
        plano += f"\n  ✅ {risco_noticias['positivas'][0]['titulo']}"

    return plano


def rodar_analise_ia(resultados: list, arquivo_estado: str) -> str:
    """
    Roda a IA em todos os ativos com score >= SCORE_MINIMO_IA e monta
    uma mensagem consolidada com "por que entrar / por que não entrar".
    Sempre roda, independente de estado ou alertas anteriores.
    """
    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key:
        return ""

    candidatos = [r for r in resultados if r["score"] >= SCORE_MINIMO_IA and r["direcao"] != "neutro"]
    if not candidatos:
        return "🤖 <b>Análise da IA:</b> Nenhum ativo com sinal suficiente para análise visual hoje."

    sufixo = arquivo_estado.replace(".json", "")
    blocos_ia = []

    for r in candidatos[:6]:  # máximo 6 pra não estourar o limite gratuito do Gemini
        ticker = r["ticker"]
        caminho = os.path.join(PASTA_GRAFICOS, f"{ticker}_{sufixo}.png")

        if not os.path.exists(caminho):
            continue

        print(f"  [IA] Analisando {ticker}...")
        analise = analisar_ativo_visualmente(
            ticker=ticker,
            score=r["score"],
            direcao=r["direcao"],
            motivos=r["motivos"],
            preco=r["preco"],
            caminho_imagem=caminho,
            api_key=api_key,
        )
        blocos_ia.append(formatar_analise_ia(ticker, r["preco"], analise))

        import time
        time.sleep(4)  # respeita o limite de 15 chamadas/minuto do plano gratuito

    if not blocos_ia:
        return ""

    hoje = date.today().strftime("%d/%m/%Y")
    cabecalho = (
        f"🤖 <b>Análise da IA — {hoje}</b>\n"
        f"Leitura visual dos gráficos com mais força hoje.\n\n"
    )
    return cabecalho + "\n\n".join(blocos_ia)


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
    cabecalho_msg += (
        f"Ranking de {len(resultados)} ativo(s) — do maior sinal pro menor.\n\n"
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
