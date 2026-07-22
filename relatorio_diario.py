"""
Relatório Diário — orquestra tudo:
  1. Roda o screener na watchlist
  2. Para os melhores setups, checa notícias de risco (pode cancelar o sinal)
  3. Calcula stop/alvo (ATR + suporte/resistência)
  4. Sugere parâmetros de opção (strike/vencimento)
  5. Monta o relatório e envia no Telegram (texto + gráfico)

USO:
    python relatorio_diario.py

Agende isso pra rodar todo dia de manhã (antes ou logo após a abertura do
pregão) usando cron (Linux/Mac) ou o Agendador de Tarefas (Windows).
Exemplo de cron, rodando 10:15 em dias úteis:
    15 10 * * 1-5 cd /caminho/do/projeto && /usr/bin/python3 relatorio_diario.py
"""

import os
import config
from screener import rodar_screener, melhores_setups
from noticias import checar_risco_noticias
from opcoes import sugerir_parametros_opcao
from b3_swing_analyzer import sugerir_stop_alvo, plotar_grafico
from telegram_utils import enviar_mensagem, enviar_imagem

PASTA_GRAFICOS = "graficos_tmp"


def tag_curta(motivo: str) -> str:
    """Reduz uma frase de motivo ao termo curto entre parênteses, se houver."""
    if "(" in motivo and ")" in motivo:
        return motivo.split("(")[-1].rstrip(")")
    return motivo


def montar_relatorio_ativo(resultado: dict, direcao: str) -> tuple:
    """Monta um bloco CURTO e prático para um ativo. Retorna (texto, caminho_grafico)."""
    ticker = resultado["ticker"]
    df = resultado["df"]

    # 1. Checa notícias de risco
    nome_empresa = config.NOME_EMPRESA.get(ticker, ticker)
    risco_noticias = checar_risco_noticias(nome_empresa)

    if risco_noticias["bloquear_entrada"]:
        motivo_bloqueio = risco_noticias["alertas"][0]["motivo"]
        texto = f"🚫 <b>{ticker}</b> — sinal de {direcao.upper()} cancelado (notícia: {motivo_bloqueio})"
        return texto, None

    # 2. Stop e alvo
    stop_alvo = sugerir_stop_alvo(df, direcao)

    # 3. Sugestão de opção
    opcao = sugerir_parametros_opcao(resultado["preco"], direcao)

    palavra = "COMPRAR" if direcao == "compra" else "VENDER"
    emoji = "🟢" if direcao == "compra" else "🔴"
    tags = [tag_curta(m) for m in resultado["motivos"][:3]]

    texto = (
        f"{emoji} <b>{palavra} {ticker}</b>  |  R$ {resultado['preco']:.2f}\n"
        f"Entrada {stop_alvo['preco_entrada']} → Stop {stop_alvo['stop']} → Alvo {stop_alvo['alvo']}\n"
        f"Opção: {opcao['tipo_opcao']} strike ~{opcao['strike_sugerido_aprox']}, "
        f"venc. {opcao['vencimento_sugerido']}\n"
        f"Motivo: {' + '.join(tags)}"
    )

    if risco_noticias["positivas"]:
        texto += f"\n✅ Notícia favorável: {risco_noticias['positivas'][0]['titulo']}"

    # Gera gráfico
    os.makedirs(PASTA_GRAFICOS, exist_ok=True)
    caminho_grafico = os.path.join(PASTA_GRAFICOS, f"{ticker}.png")
    plotar_grafico(df, ticker, caminho_grafico)

    return texto, caminho_grafico


def gerar_e_enviar_relatorio(enviar_graficos: bool = True):
    from datetime import date

    print("Rodando screener...")
    resultados = rodar_screener(periodo=config.PERIODO_HISTORICO)
    melhores = melhores_setups(resultados, top_n=config.TOP_N_SETUPS)

    total_setups = len(melhores["compras"]) + len(melhores["vendas"])
    hoje = date.today().strftime("%d/%m/%Y")

    if total_setups == 0:
        enviar_mensagem(
            config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID,
            f"📊 <b>Relatório {hoje}</b>\nNenhum setup com confluência forte hoje. Sem operações sugeridas."
        )
        print("Nenhum setup encontrado. Mensagem enviada.")
        return

    print("Checando notícias e montando blocos...")
    blocos = []
    graficos = []
    for r in melhores["compras"] + melhores["vendas"]:
        direcao = "compra" if r["pontos"] > 0 else "venda"
        texto, grafico = montar_relatorio_ativo(r, direcao)
        blocos.append(texto)
        if grafico:
            graficos.append((r["ticker"], grafico))

    mensagem_final = f"📊 <b>Relatório B3 — {hoje}</b>\n\n" + "\n\n".join(blocos)
    mensagem_final += (
        "\n\n⚠️ Apoio técnico automatizado, não é recomendação de investimento. "
        "Confirme liquidez da opção e valide com sua gestão de risco."
    )

    enviar_mensagem(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, mensagem_final)

    if enviar_graficos:
        for ticker, grafico in graficos:
            enviar_imagem(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, grafico, legenda=ticker)

    print("Relatório enviado com sucesso.")


if __name__ == "__main__":
    gerar_e_enviar_relatorio()
