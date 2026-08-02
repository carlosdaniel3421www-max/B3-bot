"""
Relatório da Tarde — versão de curtíssimo prazo ("até o fim da semana")
Reaproveita a lógica principal do relatorio_diario.py, mas com:
  - Watchlist e período próprios (configuráveis em config.py)
  - Indicadores de curto prazo (SMA5/10/20, RSI7, MACD 5/13/5, etc.)
  - Foco em decisões de poucos dias
  - Confirmação intradiária (gráfico de 1 hora) opcional

USO:
    python relatorio_tarde.py

Agende pra rodar todo dia à tarde (ex: 13h BRT) via GitHub Actions,
cron ou Agendador de Tarefas.
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
from ia_analise import montar_resumo_tecnico, analisar_com_ia
from b3_swing_analyzer import sugerir_stop_alvo, plotar_grafico
from telegram_utils import enviar_mensagem, enviar_album

# Reimporta a função do relatório diário (que agora retorna tupla)
from relatorio_diario import montar_bloco_resumo

PASTA_GRAFICOS = "graficos_tmp_tarde"


def gerar_e_enviar_relatorio_tarde():
    """
    Versão da tarde: foco em curtíssimo prazo, com indicadores mais rápidos
    e confirmação intradiária opcional.
    """
    watchlist = getattr(config, "WATCHLIST_TARDE", config.WATCHLIST)
    periodo = getattr(config, "PERIODO_HISTORICO_TARDE", "3mo")
    nivel_detalhe = getattr(config, "NIVEL_DETALHE_TARDE", config.NIVEL_DETALHE)
    arquivo_estado = "estado_tarde.json"
    titulo = "Relatório B3 — Tarde (Curto Prazo)"
    
    # Parâmetros de gestão de risco (pode ter seus próprios valores)
    atr_mult = getattr(config, "ATR_MULT_TARDE", 1.0)  # Stop mais apertado pra curto prazo
    risco_retorno = getattr(config, "RISCO_RETORNO_TARDE", 1.5)  # Alvo mais próximo
    risco_maximo_atr_mult = getattr(config, "RISCO_MAXIMO_ATR_MULT_TARDE", config.RISCO_MAXIMO_ATR_MULT)
    margem_saida_estado = getattr(config, "MARGEM_SAIDA_ESTADO_TARDE", config.MARGEM_SAIDA_ESTADO)
    
    # Usa indicadores de curto prazo e projeta volume (importante pra tarde)
    usar_curto_prazo = True
    projetar_volume = True
    confirmar_intradiario = getattr(config, "CONFIRMAR_INTRADIARIO_TARDE", True)
    
    print(f"[{titulo}] Rodando screener com indicadores de curto prazo...")
    resultados = rodar_screener(
        watchlist=watchlist,
        periodo=periodo,
        usar_curto_prazo=usar_curto_prazo,
        projetar_volume=projetar_volume,
        confirmar_intradiario=confirmar_intradiario
    )
    
    hoje = date.today().strftime("%d/%m/%Y")
    
    if not resultados:
        enviar_mensagem(
            config.TELEGRAM_TOKEN,
            config.TELEGRAM_CHAT_ID,
            f"📊 <b>{titulo} — {hoje}</b>\nNão consegui baixar dados de nenhum ativo hoje."
        )
        print("Nenhum resultado. Mensagem enviada.")
        return
    
    print("Gerando gráficos...")
    os.makedirs(PASTA_GRAFICOS, exist_ok=True)
    caminhos_graficos = []
    for r in resultados:
        caminho = os.path.join(PASTA_GRAFICOS, f"{r['ticker']}_tarde.png")
        plotar_grafico(r["df"], r["ticker"], caminho)
        caminhos_graficos.append(caminho)
    
    print("Carregando estado (histórico de alertas)...")
    estado = carregar_estado(arquivo_estado)
    
    print("Checando notícias/calendário e montando resumo...")
    blocos = []
    blocos_ia = []  # Lista separada pra mensagens da IA
    for r in resultados:
        caminho = os.path.join(PASTA_GRAFICOS, f"{r['ticker']}_tarde.png")
        bloco_principal, bloco_ia = montar_bloco_resumo(
            r, estado, nivel_detalhe,
            atr_mult=atr_mult,
            risco_retorno=risco_retorno,
            risco_maximo_atr_mult=risco_maximo_atr_mult,
            margem_saida_estado=margem_saida_estado,
            caminho_imagem=caminho
        )
        blocos.append(bloco_principal)
        if bloco_ia:  # Se tiver análise da IA, guarda pra enviar depois
            blocos_ia.append(bloco_ia)
        estado = atualizar_estado(
            estado, r["ticker"], r["score"], r["direcao"], nivel_detalhe,
            margem_saida=margem_saida_estado
        )
    
    salvar_estado(estado, arquivo_estado)
    
    nota_extra = getattr(config, "NOTA_EXTRA_TARDE", "Foco: operações de curtíssimo prazo (até o fim da semana).")
    
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
    
    # Envia as análises da IA como mensagens separadas (uma por ativo)
    if blocos_ia:
        print(f"Enviando {len(blocos_ia)} análise(s) da IA...")
        for bloco_ia in blocos_ia:
            enviar_mensagem(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, bloco_ia)
    
    print(f"[{titulo}] Relatório enviado com sucesso.")


if __name__ == "__main__":
    gerar_e_enviar_relatorio_tarde()
