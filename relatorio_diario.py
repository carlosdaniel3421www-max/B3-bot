"""
Relatório Diário — orquestra tudo:
  1. Roda o screener na watchlist, avaliando cada ativo de 0 a 10
  2. Manda TODOS os gráficos juntos, num álbum só
  3. Manda um resumo em texto, ranqueado do nível mais alto pro mais baixo
  4. Para os ativos com nível alto (>= nivel_detalhe) que sejam alerta NOVO
     (não repete o mesmo plano todo dia — veja estado.py):
       - Checa notícias de risco
       - Checa calendário de resultados (evita véspera de balanço)
       - Calcula stop/alvo (ATR + suporte/resistência, com teto de risco)
       - Calcula tamanho de posição sugerido (gestão de risco)
       - Sugere parâmetros de opção (strike/vencimento)

A lógica principal (gerar_e_enviar_relatorio) é parametrizável, pra poder
ser reaproveitada por outros relatórios (ex: relatorio_tarde.py, com
watchlist, prazo e motor de indicadores diferentes) sem duplicar código.

USO (relatório da manhã, padrão):
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
from calendario import checar_resultado_proximo
from gestao_risco import calcular_tamanho_posicao
from estado import carregar_estado, salvar_estado, eh_alerta_novo, atualizar_estado
from b3_swing_analyzer import sugerir_stop_alvo, plotar_grafico
from telegram_utils import enviar_mensagem, enviar_album

PASTA_GRAFICOS = "graficos_tmp"


def montar_bloco_resumo(resultado: dict, estado: dict, nivel_detalhe: int,
                         atr_mult: float = 1.5, risco_retorno: float = 2.0,
                         risco_maximo_atr_mult: float = 3.0, margem_saida_estado: int = 2) -> str:
    """
    Monta o bloco de texto para UM ativo no resumo final.
    - Direção "neutro" (sinais empatados/conflitantes): só mostra o placar, nunca plano completo.
    - Nível < nivel_detalhe: só mostra placar e motivos.
    - Nível >= nivel_detalhe e já alertado antes (mesma direção): versão curta.
    - Nível >= nivel_detalhe e é alerta NOVO: plano completo.
    """
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
        return f"{cabecalho}\n{motivos_txt}\n  ↻ Sinal mantido desde {data_alerta} — plano já enviado, sem novidade."

    # --- A partir daqui: é um alerta NOVO, monta o plano completo ---
    nome_empresa = config.NOME_EMPRESA.get(ticker, ticker)
    risco_noticias = checar_risco_noticias(nome_empresa)

    if risco_noticias["bloquear_entrada"]:
        motivo_bloqueio = risco_noticias["alertas"][0]["motivo"]
        return (
            f"{cabecalho}\n{motivos_txt}\n"
            f"  🚫 <b>Plano de entrada CANCELADO</b> — notícia de risco encontrada: {motivo_bloqueio}"
        )

    resultado_trimestral = checar_resultado_proximo(ticker, config.DIAS_MINIMOS_ANTES_RESULTADO)
    if resultado_trimestral["tem_resultado_proximo"]:
        return (
            f"{cabecalho}\n{motivos_txt}\n"
            f"  🚫 <b>Plano de entrada CANCELADO</b> — resultado trimestral em "
            f"{resultado_trimestral['dias_ate_resultado']} dia(s) ({resultado_trimestral['data_resultado']}). "
            f"Volatilidade imprevisível na véspera/pós-balanço."
        )

    df = resultado["df"]
    stop_alvo = sugerir_stop_alvo(df, direcao, atr_mult=atr_mult, risco_retorno=risco_retorno,
                                   risco_maximo_atr_mult=risco_maximo_atr_mult)
    opcao = sugerir_parametros_opcao(resultado["preco"], direcao)
    posicao = calcular_tamanho_posicao(config.CAPITAL_DISPONIVEL, config.RISCO_POR_OPERACAO_PCT,
                                        stop_alvo["preco_entrada"], stop_alvo["stop"])

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
    )

    if posicao.get("quantidade_acoes", 0) > 0:
        plano += (
            f"  <b>Tamanho sugerido:</b> {posicao['quantidade_acoes']} ações "
            f"(≈ R$ {posicao['valor_posicao']}), arriscando R$ {posicao['valor_em_risco']} "
            f"({posicao['pct_capital_em_risco']}% do capital)\n"
        )
    else:
        plano += "  <b>Tamanho sugerido:</b> risco por ação muito alto pro seu capital/risco configurado — reveja o setup.\n"

    plano += (
        f"  <b>Opção sugerida:</b> {opcao['tipo_opcao']}, strike próximo de "
        f"R$ {opcao['strike_sugerido_aprox']}, vencimento {opcao['vencimento_sugerido']} "
        f"— {explicacao_opcao}.\n"
        f"  ⚠️ Confira a liquidez dessa opção no seu home broker antes de operar."
    )

    if risco_noticias["positivas"]:
        plano += f"\n  ✅ Notícia recente favorável: {risco_noticias['positivas'][0]['titulo']}"

    return plano


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
    resultados = rodar_screener(watchlist=watchlist, periodo=periodo,
                                 usar_curto_prazo=usar_curto_prazo, projetar_volume=projetar_volume,
                                 confirmar_intradiario=confirmar_intradiario)
    hoje = date.today().strftime("%d/%m/%Y")

    if not resultados:
        enviar_mensagem(
            config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID,
            f"📊 <b>{titulo} — {hoje}</b>\nNão consegui baixar dados de nenhum ativo hoje."
        )
        print("Nenhum resultado. Mensagem enviada.")
        return

    print("Gerando gráficos...")
    os.makedirs(PASTA_GRAFICOS, exist_ok=True)
    caminhos_graficos = []
    for r in resultados:
        caminho = os.path.join(PASTA_GRAFICOS, f"{r['ticker']}_{arquivo_estado.replace('.json','')}.png")
        plotar_grafico(r["df"], r["ticker"], caminho)
        caminhos_graficos.append(caminho)

    print("Carregando estado (histórico de alertas)...")
    estado = carregar_estado(arquivo_estado)

    print("Checando notícias/calendário e montando resumo...")
    blocos = []
    for r in resultados:
        blocos.append(montar_bloco_resumo(r, estado, nivel_detalhe, atr_mult=atr_mult,
                                           risco_retorno=risco_retorno,
                                           risco_maximo_atr_mult=risco_maximo_atr_mult,
                                           margem_saida_estado=margem_saida_estado))
        estado = atualizar_estado(estado, r["ticker"], r["score"], r["direcao"], nivel_detalhe,
                                   margem_saida=margem_saida_estado)

    salvar_estado(estado, arquivo_estado)

    cabecalho_msg = f"📊 <b>{titulo} — {hoje}</b>\n"
    if nota_extra:
        cabecalho_msg += f"{nota_extra}\n"
    cabecalho_msg += (
        f"Ranking de {len(resultados)} ativo(s), do nível mais alto pro mais baixo.\n"
        f"Plano de entrada completo só a partir de {nivel_detalhe}/10, e só na primeira "
        f"vez que o sinal aparece (sem repetir todo dia).\n\n"
    )

    mensagem_final = (
        cabecalho_msg
        + "\n\n".join(blocos)
        + "\n\n⚠️ Apoio técnico automatizado, não é recomendação de investimento. "
          "Confirme liquidez da opção e valide com sua própria gestão de risco."
    )

    print("Enviando álbum de gráficos...")
    enviar_album(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, caminhos_graficos)

    print("Enviando resumo em texto...")
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

    print(f"[{titulo}] Relatório enviado com sucesso.")


if __name__ == "__main__":
    gerar_e_enviar_relatorio(
        watchlist=config.WATCHLIST,
        periodo=config.PERIODO_HISTORICO,
        nivel_detalhe=config.NIVEL_DETALHE,
        arquivo_estado="estado.json",
        titulo="Relatório B3 — Manhã",
    )
