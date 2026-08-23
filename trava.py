"""
Módulo de TRAVAS — estruturas de duas pernas (compra + venda) com risco
limitado. Usa a mesma lógica de opções do projeto:

- TRAVA DE ALTA (Bull Call Spread): COMPRA uma CALL OTM + VENDE uma CALL
  mais longe. Custa menos que comprar a CALL sozinha e limita o ganho.
- TRAVA DE BAIXA (Bear Put Spread): COMPRA uma PUT OTM + VENDE uma PUT
  mais longe. Custa menos que comprar a PUT sozinha e limita o ganho.

ESTRATÉGIA DO USUÁRIO (swing trade com opções OTM):
  - Compra a perna OTM perto do preço atual (ex: ativo em R$ 45, compra
    strike ~46-47) — paga barato.
  - Vende a perna mais longe (strike ~+5%) pra reduzir o custo.
  - Encerra quando o preço do ativo se aproxima do strike comprado (a opção
    OTM valoriza forte com o gamma) — não espera o vencimento.

IMPORTANTE: sem OpLab conectada, o prêmio é ESTIMATIVA teórica
(Black-Scholes com volatilidade histórica) — nunca cotação real de mercado.
"""

import logging
import math

logger = logging.getLogger(__name__)


def _premio_bs_europeu(S, K, T, r, sigma, tipo):
    """
    Black-Scholes para opção europeia (sem dividendos, aproximação).
    S: preço do ativo | K: strike | T: anos até vencimento
    r: taxa livre de risco | sigma: volatilidade anualizada
    tipo: 'call' ou 'put'
    """
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    from math import erf, sqrt

    def _n(x):
        return 0.5 * (1 + erf(x / sqrt(2)))

    if tipo == "call":
        return S * _n(d1) - K * math.exp(-r * T) * _n(d2)
    else:
        return K * math.exp(-r * T) * _n(-d2) - S * _n(-d1)


def estimar_premio(preco_atual: float, strike: float, dias_venc: int,
                   tipo: str, sigma: float = 0.30, taxa_juros: float = 0.105) -> float:
    """
    Estima o prêmio de uma opção via Black-Scholes.
    sigma default 0.30 (volatilidade anual histórica típica de ações B3),
    taxa default 10.5% a.a. (Selic aproximada).
    """
    T = dias_venc / 365.0
    premio = _premio_bs_europeu(preco_atual, strike, T, taxa_juros, sigma, tipo.lower())
    return round(premio, 2)


def _lotes_strikes(preco_atual: float, pct_perna1: float, pct_perna2: float):
    """
    Ajusta os strikes para a grade real da B3 (múltiplos de 0.50 até 10,
    múltiplos de 1.00 acima de 10). Retorna strikes "de mercado".
    """
    def _arredondar(valor):
        if valor <= 10:
            return round(valor * 2) / 2.0  # múltiplo de 0.50
        return round(valor)  # múltiplo de 1.00

    perna1 = _arredondar(preco_atual * pct_perna1)
    perna2 = _arredondar(preco_atual * pct_perna2)

    # Garante ordem correta (perna1 mais perto do preço, perna2 mais longe)
    if perna1 == perna2:
        perna2 = _arredondar(perna1 + 1.0)
    return perna1, perna2


def montar_trava(preco_atual: float, direcao: str,
                 pct_perna1: float = None, pct_perna2: float = None,
                 dias_venc: int = 35, sigma: float = 0.30) -> dict:
    """
    Monta uma trava (Bull Call Spread ou Bear Put Spread) com base no preço
    atual e na direção do sinal.

    pct_perna1: % sobre o preço para a perna COMPRADA (default compra 3% OTM,
                venda 3% ITM — na prática o usuário gosta de OTM: ~2-4%).
    pct_perna2: % sobre o preço para a perna VENDIDA (mais longe).

    Retorna dict com as duas pernas, prêmios, risco máx, ganho máx e breakeven.
    """
    direcao = direcao.lower()
    if direcao not in ("compra", "venda"):
        raise ValueError("direcao deve ser 'compra' ou 'venda'")

    # Padrões: perna comprada ~2-4% OTM, perna vendida ~6-8% OTM
    if direcao == "compra":
        pct_perna1 = pct_perna1 or 1.03   # CALL strike +3% (OTM)
        pct_perna2 = pct_perna2 or 1.08   # CALL strike +8%
        tipo_perna1 = "call"
        tipo_perna2 = "call"
        nome = "TRAVA DE ALTA (Bull Call Spread)"
    else:
        pct_perna1 = pct_perna1 or 0.97   # PUT strike -3% (OTM)
        pct_perna2 = pct_perna2 or 0.92   # PUT strike -8%
        tipo_perna1 = "put"
        tipo_perna2 = "put"
        nome = "TRAVA DE BAIXA (Bear Put Spread)"

    strike_perna1, strike_perna2 = _lotes_strikes(preco_atual, pct_perna1, pct_perna2)

    # Garante que a perna comprada é a mais próxima do preço atual
    if direcao == "compra":
        strike_comprado, strike_vendido = min(strike_perna1, strike_perna2), max(strike_perna1, strike_perna2)
    else:
        strike_comprado, strike_vendido = max(strike_perna1, strike_perna2), min(strike_perna1, strike_perna2)

    premio_comprado = estimar_premio(preco_atual, strike_comprado, dias_venc, tipo_perna1, sigma)
    premio_vendido = estimar_premio(preco_atual, strike_vendido, dias_venc, tipo_perna2, sigma)

    custo_liquido = round(premio_comprado - premio_vendido, 2)

    # Risco máximo e ganho máximo
    if direcao == "compra":
        risco_max = custo_liquido
        ganho_max = round((strike_vendido - strike_comprado) - custo_liquido, 2)
        breakeven = round(strike_comprado + custo_liquido, 2)
        encerrar_quando = strike_comprado  # perto do strike comprado = sair
    else:
        risco_max = custo_liquido
        ganho_max = round((strike_comprado - strike_vendido) - custo_liquido, 2)
        breakeven = round(strike_comprado - custo_liquido, 2)
        encerrar_quando = strike_comprado

    return {
        "nome": nome,
        "direcao": direcao,
        "tipo_perna1": tipo_perna1,
        "tipo_perna2": tipo_perna2,
        "strike_comprado": strike_comprado,
        "strike_vendido": strike_vendido,
        "premio_comprado": premio_comprado,
        "premio_vendido": premio_vendido,
        "custo_liquido": custo_liquido,
        "risco_maximo": risco_max,
        "ganho_maximo": ganho_max,
        "breakeven": breakeven,
        "encerrar_quando": encerrar_quando,
        "dias_vencimento": dias_venc,
        "fonte": "estimativa",
        "observacao": (
            "Prêmios estimados por Black-Scholes (volatilidade histórica) — "
            "NÃO é cotação real. Confirme os prêmios e a liquidez das duas "
            "pernas no seu home broker ou OpLab antes de operar."
        ),
    }


def formatar_trava(trava: dict, preco_atual: float) -> str:
    """
    Formata a trava para exibição no Telegram, com o plano de encerramento.
    """
    linhas = [
        f"  📈 <b>{trava['nome']}</b> (ativo R$ {preco_atual:.2f})",
        f"  ➕ Comprar {trava['tipo_perna1'].upper()} strike R$ {trava['strike_comprado']:.2f} "
        f"— prêmio R$ {trava['premio_comprado']:.2f}",
        f"  ➖ Vender {trava['tipo_perna2'].upper()} strike R$ {trava['strike_vendido']:.2f} "
        f"— prêmio R$ {trava['premio_vendido']:.2f}",
        f"  💰 Custo líquido: R$ {trava['custo_liquido']:.2f}",
        f"  🛑 Risco máx: R$ {trava['risco_maximo']:.2f} | "
        f"🎯 Ganho máx: R$ {trava['ganho_maximo']:.2f}",
        f"  ⚖️ Breakeven: R$ {trava['breakeven']:.2f}",
        f"  ⏳ Saia quando o ativo chegar perto de R$ {trava['encerrar_quando']:.2f} "
        f"(a opção OTM valoriza forte nesse ponto)",
    ]
    return "\n".join(linhas)
