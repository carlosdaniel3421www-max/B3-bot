"""
Relatório da Tarde — versão focada em prazo mais curto (tipo "até o fim
da semana"), rodando numa watchlist menor (PETR4, VALE3, ITUB4, WEGE3).

Diferenças pro relatório da manhã (relatorio_diario.py):
- Watchlist menor (config.WATCHLIST_TARDE)
- Stop mais apertado (ATR_MULT_TARDE) e alvo mais próximo (RISCO_RETORNO_TARDE)
  — faz sentido pra prazo curto: você quer um alvo alcançável em poucos dias,
  não um alvo de swing de semanas
- Estado separado (estado_tarde.json) — não interfere no rastreamento do
  relatório da manhã, mesmo repetindo ativos (ex: PETR4 nas duas listas)

USO:
    python relatorio_tarde.py

Roda às 13h (horário de Brasília) via GitHub Actions — veja
.github/workflows/relatorio_tarde.yml
"""

import config
from relatorio_diario import gerar_e_enviar_relatorio

if __name__ == "__main__":
    gerar_e_enviar_relatorio(
        watchlist=config.WATCHLIST_TARDE,
        periodo=config.PERIODO_HISTORICO,
        nivel_detalhe=config.NIVEL_DETALHE_TARDE,
        arquivo_estado="estado_tarde.json",
        atr_mult=config.ATR_MULT_TARDE,
        risco_retorno=config.RISCO_RETORNO_TARDE,
        titulo="Relatório B3 — Tarde (prazo curto)",
        nota_extra=(
            f"Foco em operações de prazo mais curto (~{config.MAX_DIAS_HOLDING_TARDE} dias úteis, "
            f"tipo até o fim da semana). Indicadores mais rápidos (SMA5/10/20, RSI7, MACD 5/13/5) "
            f"no gráfico diário, confirmados (ou não) pelo gráfico de 1 hora."
        ),
        usar_curto_prazo=True,
        projetar_volume=True,
        confirmar_intradiario=True,
    )
