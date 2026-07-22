"""
Relatório Diário — orquestra tudo:
  1. Roda o screener em toda a watchlist, avaliando cada ativo de 0 a 10
  2. Manda TODOS os gráficos juntos, num álbum só
  3. Manda um resumo em texto, ranqueado do nível mais alto pro mais baixo
  4. Para os ativos com nível alto (>= NIVEL_DETALHE), checa notícias de
     risco, calcula stop/alvo e sugere strike/vencimento de opção

USO:
    python relatorio_diario.py

Agende isso pra rodar todo dia de manhã usando GitHub Actions (veja o
README), cron (Linux/Mac) ou o Agendador de Tarefas (Windows).
"""

import os
from datetime import date

import config
from screener import rodar_screener
from noticias import checar_risco_noticias
from opcoes import sugerir_parametros_opcao
from b3_swing_analyzer import sugerir_stop_alvo, plotar_grafico
from telegram_utils import enviar_mensagem, enviar_album

PASTA_GRAFICOS = "graficos_tmp"


def montar_bloco_resumo(resultado: dict) -> str:
    """
    Monta o bloco de texto para UM ativo no resumo final.
    Ativos com nível >= NIVEL_DETALHE ganham plano de entrada completo
    (stop, alvo, opção sugerida). Os demais ficam só com o nível e os motivos,
    pra você ver o panorama geral sem poluir a leitura.
    """
    ticker = resultado["ticker"]
    score = resultado["score"]
    direcao = resultado["direcao"]
    emoji = "🟢" if direcao == "compra" else "🔴"
    palavra = "COMPRA" if direcao == "compra" else "VENDA"

    cabecalho = f"{emoji} <b>{ticker} — {score}/10 ({palavra})</b>"
    motivos_txt = "\n".join(f"  • {m}" for m in resultado["motivos"])

    if score < config.NIVEL_DETALHE:
        # Nível baixo: só mostra o panorama, sem plano de entrada
        return f"{cabecalho}\n{motivos_txt}"

    # Nível alto: checa notícias antes de dar o plano completo
    nome_empresa = config.NOME_EMPRESA.get(ticker, ticker)
    risco_noticias = checar_risco_noticias(nome_empresa)

    if risco_noticias["bloquear_entrada"]:
        motivo_bloqueio = risco_noticias["alertas"][0]["motivo"]
        return (
            f"{cabecalho}\n{motivos_txt}\n"
            f"  🚫 <b>Plano de entrada CANCELADO</b> — notícia de risco encontrada: {motivo_bloqueio}"
        )

    df = resultado["df"]
    stop_alvo = sugerir_stop_alvo(df, direcao)
    opcao = sugerir_parametros_opcao(resultado["preco"], direcao)

    explicacao_opcao = (
        "uma CALL é a opção que lucra se o ativo SOBE"
        if opcao["tipo_opcao"] == "CALL"
        else "uma PUT é a opção que lucra se o ativo CAI"
    )

    plano = (
        f"{cabecalho}\n{motivos_txt}\n"
        f"  <b>Preço atual:</b> R$ {resultado['preco']:.2f}\n"
        f"  <b>Plano sugerido:</b> entrar perto de R$ {stop_alvo['preco_entrada']} · "
        f"sair no prejuízo (stop) se cair a R$ {stop_alvo['stop']} · "
        f"realizar lucro (alvo) perto de R$ {stop_alvo['alvo']}\n"
        f"  <b>Opção sugerida:</b> {opcao['tipo_opcao']}, strike próximo de "
        f"R$ {opcao['strike_sugerido_aprox']}, vencimento {opcao['vencimento_sugerido']} "
        f"— {explicacao_opcao}.\n"
        f"  ⚠️ Confira a liquidez dessa opção no seu home broker antes de operar."
    )

    if risco_noticias["positivas"]:
        plano += f"\n  ✅ Notícia recente favorável: {risco_noticias['positivas'][0]['titulo']}"

    return plano


def gerar_e_enviar_relatorio():
    print("Rodando screener em toda a watchlist...")
    resultados = rodar_screener(watchlist=config.WATCHLIST, periodo=config.PERIODO_HISTORICO)
    hoje = date.today().strftime("%d/%m/%Y")

    if not resultados:
        enviar_mensagem(
            config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID,
            f"📊 <b>Relatório {hoje}</b>\nNão consegui baixar dados de nenhum ativo hoje. Verifique a watchlist."
        )
        print("Nenhum resultado. Mensagem enviada.")
        return

    print("Gerando gráficos...")
    os.makedirs(PASTA_GRAFICOS, exist_ok=True)
    caminhos_graficos = []
    for r in resultados:
        caminho = os.path.join(PASTA_GRAFICOS, f"{r['ticker']}.png")
        plotar_grafico(r["df"], r["ticker"], caminho)
        caminhos_graficos.append(caminho)

    print("Checando notícias e montando resumo...")
    blocos = [montar_bloco_resumo(r) for r in resultados]

    mensagem_final = (
        f"📊 <b>Relatório B3 — {hoje}</b>\n"
        f"Ranking de {len(resultados)} ativo(s), do nível mais alto pro mais baixo.\n"
        f"Plano de entrada completo só a partir de {config.NIVEL_DETALHE}/10 "
        f"(confluência mais forte de indicadores).\n\n"
        + "\n\n".join(blocos)
        + "\n\n⚠️ Apoio técnico automatizado, não é recomendação de investimento. "
          "Confirme liquidez da opção e valide com sua própria gestão de risco."
    )

    print("Enviando álbum de gráficos...")
    enviar_album(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, caminhos_graficos)

    print("Enviando resumo em texto...")
    # Telegram limita ~4096 caracteres por mensagem; quebra em partes se precisar
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

    print("Relatório enviado com sucesso.")


if __name__ == "__main__":
    gerar_e_enviar_relatorio()
