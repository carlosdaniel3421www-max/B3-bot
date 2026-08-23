"""
Módulo de TRAVAS — estruturas de duas pernas (compra + venda) com risco
limitado. Usa a mesma lógica de opções do projeto:

- TRAVA DE ALTA (Bull Call Spread): COMPRA uma CALL OTM + VENDE uma CALL
  mais longe. Custa menos que comprar a CALL sozinha e limita o ganho.
- TRAVA DE BAIXA (Bear Put Spread): COMPRA uma PUT OTM + VENDE uma PUT
  mais longe. Custa menos que comprar a PUT sozinha e limita o ganho.

ESTRATÉGIA REAL DO USUÁRIO (opções BEM OTM, baratas):
  - Compra opções FORA do dinheiro com prêmio pequeno (~R$ 0,20-0,30 por
    contrato) — não usa percentual fixo de strike, busca o prêmio barato.
  - Opera ~100 contratos: gasto total ~R$ 20-40 no máximo.
  - Encerra quando o preço do ativo se aproxima do strike comprado (a opção
    OTM valoriza forte com o gamma) — não espera o vencimento.
  - A perna vendida (mais longe) reduz ainda mais o custo líquido.

IMPORTANTE: sem OpLab conectada, o prêmio é ESTIMATIVA teórica
(Black-Scholes com volatilidade histórica) — nunca cotação real de mercado.
"""

import logging
import math

logger = logging.getLogger(__name__)

# Teto de gasto total padrão do usuário (100 contratos)
CONTRATOS_PADRAO = 100
GASTO_MAXIMO_PADRAO = 40.0
PREMI0_ALVO_PERNA1 = 0.25   # prêmio-alvo da perna comprada (~R$ 0,25)
PREMI0_ALVO_PERNA2 = 0.08   # prêmio-alvo da perna vendida (~R$ 0,08)


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


def _arredondar_strike(valor):
    """Ajusta strike para a grade real da B3 (0.50 até R$10, 1.00 acima)."""
    if valor <= 10:
        return round(valor * 2) / 2.0
    return round(valor)


def _proximo_strike(strike, direcao):
    """
    Retorna o próximo strike da grade da B3, SEMPRE avançando na direção.
    Para strikes > R$ 10 a grade é de R$ 1.00; para <= R$ 10 é R$ 0.50.
    """
    if strike <= 10:
        passo = 0.5
    else:
        passo = 1.0
    if direcao == "cima":
        novo = strike + passo
    else:
        novo = strike - passo
    arredondado = _arredondar_strike(novo)
    # Garante que sempre avança (round do Python pode empacar em .5)
    if direcao == "cima" and arredondado <= strike:
        arredondado = _arredondar_strike(strike + passo + passo)
    elif direcao == "baixo" and arredondado >= strike:
        arredondado = _arredondar_strike(strike - passo - passo)
    return arredondado


def _encontrar_strike_por_premio(preco_atual, dias_venc, tipo, premio_alvo,
                                 sigma, max_passos=80):
    """
    Encontra o strike cujo prêmio estimado fica MAIS PRÓXIMO do premio_alvo.
    Caminha progressivamente OTM (afastando do preço atual) e escolhe o
    strike com o menor |prêmio - alvo|.
    """
    if tipo == "call":
        melhor = None
        melhor_dist = float("inf")
        strike = _arredondar_strike(preco_atual)
        for _ in range(max_passos):
            premio = estimar_premio(preco_atual, strike, dias_venc, "call", sigma)
            dist = abs(premio - premio_alvo)
            if dist < melhor_dist:
                melhor_dist = dist
                melhor = strike
            # Se o prêmio chegou a zero, parou de afastar
            if premio <= 0.01:
                break
            strike = _proximo_strike(strike, "cima")
        return melhor if melhor is not None else _arredondar_strike(preco_atual + 1.0)
    else:
        melhor = None
        melhor_dist = float("inf")
        strike = _arredondar_strike(preco_atual)
        for _ in range(max_passos):
            premio = estimar_premio(preco_atual, strike, dias_venc, "put", sigma)
            dist = abs(premio - premio_alvo)
            if dist < melhor_dist:
                melhor_dist = dist
                melhor = strike
            if premio <= 0.01:
                break
            strike = _proximo_strike(strike, "baixo")
        return melhor if melhor is not None else _arredondar_strike(preco_atual - 1.0)


def montar_trava(preco_atual: float, direcao: str,
                 premio_alvo_perna1: float = None, premio_alvo_perna2: float = None,
                 contratos: int = CONTRATOS_PADRAO,
                 gasto_maximo: float = GASTO_MAXIMO_PADRAO,
                 dias_venc: int = 35, sigma: float = 0.30,
                 cadeia_real: dict = None, ticker: str = None) -> dict:
    """
    Monta uma trava baseada em PRÊMIO-ALVO.
    Se `cadeia_real` for fornecido, busca os strikes e prêmios na cadeia
    real do opcoes.net.br em vez de usar Black-Scholes.
    `ticker` é necessário para buscar dados reais na cadeia.
    """
    direcao = direcao.lower()
    if direcao not in ("compra", "venda"):
        raise ValueError("direcao deve ser 'compra' ou 'venda'")

    premio_alvo_perna1 = premio_alvo_perna1 or PREMI0_ALVO_PERNA1
    premio_alvo_perna2 = premio_alvo_perna2 or PREMI0_ALVO_PERNA2

    if direcao == "compra":
        tipo = "call"
        nome = "TRAVA DE ALTA (Bull Call Spread)"
    else:
        tipo = "put"
        nome = "TRAVA DE BAIXA (Bear Put Spread)"

    # Inicializa as variáveis antes de tentar dados reais (evita UnboundLocalError)
    premio_comprado = None
    strike_comprado = None
    premio_vendido = None
    strike_vendido = None

    # Tenta usar dados reais da cadeia se disponível
    fonte = "estimativa"
    if cadeia_real and ticker:
        from fonte_opcoes import buscar_melhor_vencimento, buscar_premio_real
        venc = buscar_melhor_vencimento(cadeia_real)
        if venc:
            dias_venc = venc["du"]
            lado = venc.get("calls" if tipo == "call" else "puts", {})
            if lado:
                # Acha strike com prêmio mais próximo do alvo
                melhor_strike = None
                melhor_dist = float("inf")
                for strike, info in lado.items():
                    if info["preco"] is None:
                        continue
                    dist = abs(info["preco"] - premio_alvo_perna1)
                    if dist < melhor_dist:
                        melhor_dist = dist
                        melhor_strike = strike
                if melhor_strike:
                    premio_comprado = round(lado[melhor_strike]["preco"], 2)
                    strike_comprado = melhor_strike
                    fonte = "real"

                    # Perna vendida: próximo strike com prêmio ~premio_alvo_perna2
                    strike_vendido = None
                    melhor_dist2 = float("inf")
                    for strike, info in sorted(lado.items()):
                        if info["preco"] is None:
                            continue
                        if direcao == "compra" and strike <= strike_comprado:
                            continue
                        if direcao == "venda" and strike >= strike_comprado:
                            continue
                        dist = abs(info["preco"] - premio_alvo_perna2)
                        if dist < melhor_dist2:
                            melhor_dist2 = dist
                            strike_vendido = strike
                    if strike_vendido:
                        premio_vendido = round(lado[strike_vendido]["preco"], 2)
                    else:
                        # Fallback: strike mais distante disponível
                        strikes_ordenados = sorted(lado.keys())
                        strike_vendido = strikes_ordenados[-1] if direcao == "compra" else strikes_ordenados[0]
                        premio_vendido = round(lado[strike_vendido]["preco"], 2) if strike_vendido in lado and lado[strike_vendido]["preco"] else 0.0
                else:
                    strike_comprado = None
                    premio_comprado = None

    # Se não conseguiu com dados reais, usa Black-Scholes
    if not premio_comprado or fonte == "estimativa":
        fonte = "estimativa"
        strike_comprado = _encontrar_strike_por_premio(
            preco_atual, dias_venc, tipo, premio_alvo_perna1, sigma)
        premio_comprado = estimar_premio(preco_atual, strike_comprado, dias_venc, tipo, sigma)

        strike_vendido = _encontrar_strike_por_premio(
            preco_atual, dias_venc, tipo, premio_alvo_perna2, sigma)
        premio_vendido = estimar_premio(preco_atual, strike_vendido, dias_venc, tipo, sigma)

        # Garante que a perna vendida está do lado correto
        if direcao == "compra":
            if strike_vendido <= strike_comprado:
                strike_vendido = _proximo_strike(strike_comprado, "cima")
                premio_vendido = estimar_premio(preco_atual, strike_vendido, dias_venc, tipo, sigma)
        else:
            if strike_vendido >= strike_comprado:
                strike_vendido = _proximo_strike(strike_comprado, "baixo")
                premio_vendido = estimar_premio(preco_atual, strike_vendido, dias_venc, tipo, sigma)

    premio_vendido = max(premio_vendido, 0.0)
    custo_liquido = round(premio_comprado - premio_vendido, 2)
    if custo_liquido < 0.05:
        custo_liquido = round(premio_comprado, 2)

    # Custo total pelo número de contratos
    custo_total = round(custo_liquido * contratos, 2)
    premio_comprado_total = round(premio_comprado * contratos, 2)

    # Risco máximo = o que você paga. Ganho máximo = largura do spread - custo.
    if direcao == "compra":
        risco_max = custo_total
        ganho_max = round((strike_vendido - strike_comprado - custo_liquido) * contratos, 2)
        breakeven = round(strike_comprado + custo_liquido, 2)
        encerrar_quando = strike_comprado
    else:
        risco_max = custo_total
        ganho_max = round((strike_comprado - strike_vendido - custo_liquido) * contratos, 2)
        breakeven = round(strike_comprado - custo_liquido, 2)
        encerrar_quando = strike_comprado

    dentro_orcamento = custo_total <= gasto_maximo

    return {
        "nome": nome,
        "direcao": direcao,
        "tipo": tipo,
        "strike_comprado": strike_comprado,
        "strike_vendido": strike_vendido,
        "premio_comprado": premio_comprado,
        "premio_vendido": premio_vendido,
        "custo_liquido": custo_liquido,
        "contratos": contratos,
        "custo_total": custo_total,
        "premio_comprado_total": premio_comprado_total,
        "risco_maximo": risco_max,
        "ganho_maximo": ganho_max,
        "breakeven": breakeven,
        "encerrar_quando": encerrar_quando,
        "gasto_maximo": gasto_maximo,
        "dentro_orcamento": dentro_orcamento,
        "dias_vencimento": dias_venc,
        "fonte": fonte,
        "observacao": (
            "Prêmios reais do último pregão (opcoes.net.br). Confirme a "
            "liquidez (volume/negócios) antes de operar."
            if fonte == "real" else
            "Prêmios estimados por Black-Scholes (volatilidade histórica) — "
            "NÃO é cotação real. Confirme os prêmios e a liquidez das duas "
            "pernas no seu home broker ou OpLab antes de operar."
        ),
    }


def formatar_trava(trava: dict, preco_atual: float) -> str:
    """
    Formata a trava para exibição no Telegram, com o plano de encerramento,
    focando no custo total em REAIS (não só por contrato).
    """
    tipo = trava["tipo"].upper()
    orcamento = "✅ dentro do orçamento" if trava.get("dentro_orcamento") else "⚠️ acima do orçamento de R$ {:.0f}".format(trava.get("gasto_maximo", GASTO_MAXIMO_PADRAO))
    fonte_txt = "📡 prêmio real (último pregão)" if trava.get("fonte") == "real" else "🧮 estimativa Black-Scholes"

    linhas = [
        f"  📈 <b>{trava['nome']}</b> (ativo R$ {preco_atual:.2f})",
        f"  ➕ Comprar {tipo} strike R$ {trava['strike_comprado']:.2f} "
        f"— prêmio R$ {trava['premio_comprado']:.2f}",
        f"  ➖ Vender {tipo} strike R$ {trava['strike_vendido']:.2f} "
        f"— prêmio R$ {trava['premio_vendido']:.2f}",
        f"  💰 Custo por contrato: R$ {trava['custo_liquido']:.2f}",
        f"  💵 Gasto total ({trava['contratos']} contratos): R$ {trava['custo_total']:.2f} "
        f"— {orcamento}",
        f"  🛑 Risco máx: R$ {trava['risco_maximo']:.2f} | "
        f"🎯 Ganho máx: R$ {trava['ganho_maximo']:.2f}",
        f"  ⚖️ Breakeven: R$ {trava['breakeven']:.2f}",
        f"  ⏳ Saia quando o ativo chegar perto de R$ {trava['encerrar_quando']:.2f} "
        f"(a opção OTM valoriza forte nesse ponto)",
        f"  <i>{fonte_txt}</i>",
    ]
    return "\n".join(linhas)
