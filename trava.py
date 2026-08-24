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
    vencimento_data = None
    sufixo_comprado = None
    sufixo_vendido = None
    vol_impl_comprado = None
    vol_impl_vendido = None
    delta_comprado = None
    delta_vendido = None
    negocios_comprado = None
    negocios_vendido = None
    volume_comprado = None
    volume_vendido = None

    # Tenta usar dados reais da cadeia se disponível
    fonte = "estimativa"
    sigma_real = sigma
    if cadeia_real and ticker:
        from fonte_opcoes import buscar_melhor_vencimento, buscar_premio_real, vol_impl_mediana
        # Usa a volatilidade implícita mediana real da cadeia (melhor que 30% fixo)
        vi_mediana = vol_impl_mediana(cadeia_real, tipo=tipo)
        if vi_mediana and vi_mediana > 0:
            sigma_real = vi_mediana / 100.0  # API retorna percentual (ex: 35.2 = 35.2%)
        venc = buscar_melhor_vencimento(cadeia_real)
        if venc:
            dias_venc = venc["du"]
            vencimento_data = venc["dt"]
            lado = venc.get("calls" if tipo == "call" else "puts", {})
            if lado:
                # Acha strike com prêmio mais próximo do alvo, exigindo
                # LIQUIDEZ: preço disponível E pelo menos 1 negócio (evita
                # pegar opção sem negócio recente com preço desatualizado).
                def _tem_liquidez(info):
                    return (info["preco"] is not None
                            and info.get("negocios") is not None
                            and info["negocios"] > 0)

                melhor_strike = None
                melhor_dist = float("inf")
                for strike, info in lado.items():
                    if not _tem_liquidez(info):
                        continue
                    dist = abs(info["preco"] - premio_alvo_perna1)
                    if dist < melhor_dist:
                        melhor_dist = dist
                        melhor_strike = strike
                if melhor_strike:
                    premio_comprado = round(lado[melhor_strike]["preco"], 2)
                    strike_comprado = melhor_strike
                    sufixo_comprado = lado[melhor_strike].get("sufixo") or ""
                    vol_impl_comprado = lado[melhor_strike].get("vol_impl")
                    delta_comprado = lado[melhor_strike].get("delta")
                    negocios_comprado = lado[melhor_strike].get("negocios")
                    volume_comprado = lado[melhor_strike].get("volume")
                    fonte = "real"

                    # Perna vendida: próximo strike com prêmio ~premio_alvo_perna2
                    strike_vendido = None
                    melhor_dist2 = float("inf")
                    for strike, info in sorted(lado.items()):
                        if not _tem_liquidez(info):
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
                        sufixo_vendido = lado[strike_vendido].get("sufixo") or ""
                        vol_impl_vendido = lado[strike_vendido].get("vol_impl")
                        delta_vendido = lado[strike_vendido].get("delta")
                        negocios_vendido = lado[strike_vendido].get("negocios")
                        volume_vendido = lado[strike_vendido].get("volume")
                    else:
                        # Fallback: strike mais distante com liquidez
                        strikes_ordenados = sorted(
                            [s for s, i in lado.items() if _tem_liquidez(i)]
                        )
                        if strikes_ordenados:
                            strike_vendido = strikes_ordenados[-1] if direcao == "compra" else strikes_ordenados[0]
                            premio_vendido = round(lado[strike_vendido]["preco"], 2)
                            sufixo_vendido = lado[strike_vendido].get("sufixo") or ""
                            negocios_vendido = lado[strike_vendido].get("negocios")
                            volume_vendido = lado[strike_vendido].get("volume")
                        else:
                            strike_vendido = None
                else:
                    strike_comprado = None
                    premio_comprado = None

    # Se não conseguiu com dados reais (falta perna comprada OU vendida), usa Black-Scholes
    if not premio_comprado or not premio_vendido or fonte == "estimativa":
        fonte = "estimativa"
        strike_comprado = _encontrar_strike_por_premio(
            preco_atual, dias_venc, tipo, premio_alvo_perna1, sigma_real)
        premio_comprado = estimar_premio(preco_atual, strike_comprado, dias_venc, tipo, sigma_real)

        strike_vendido = _encontrar_strike_por_premio(
            preco_atual, dias_venc, tipo, premio_alvo_perna2, sigma_real)
        premio_vendido = estimar_premio(preco_atual, strike_vendido, dias_venc, tipo, sigma_real)

        # Garante que a perna vendida está do lado correto
        if direcao == "compra":
            if strike_vendido <= strike_comprado:
                strike_vendido = _proximo_strike(strike_comprado, "cima")
                premio_vendido = estimar_premio(preco_atual, strike_vendido, dias_venc, tipo, sigma_real)
        else:
            if strike_vendido >= strike_comprado:
                strike_vendido = _proximo_strike(strike_comprado, "baixo")
                premio_vendido = estimar_premio(preco_atual, strike_vendido, dias_venc, tipo, sigma_real)

    premio_vendido = max(premio_vendido or 0.0, 0.0)
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

    # --- Plano de saída ---
    # Stop no prêmio: se a trava perder 50% do valor, sai (perda máxima recomendada)
    stop_premio_por_contrato = round(custo_liquido * 0.5, 2)
    stop_premio_total = round(stop_premio_por_contrato * contratos, 2)
    # Alvo: quando o ativo chegar perto do strike comprado, a trava valoriza forte
    # Lucro sugerido = 50% do ganho máximo (fechamento parcial conservador)
    lucro_alvo_total = round(ganho_max * 0.5, 2)
    # Tempo máximo: sair até 15 dias úteis antes do vencimento (theta acelera)
    dias_max_holding = max(dias_venc - 15, 5)

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
        "vencimento_data": vencimento_data,
        "sufixo_comprado": sufixo_comprado,
        "sufixo_vendido": sufixo_vendido,
        "vol_impl_comprado": vol_impl_comprado,
        "vol_impl_vendido": vol_impl_vendido,
        "delta_comprado": delta_comprado,
        "delta_vendido": delta_vendido,
        "negocios_comprado": negocios_comprado,
        "negocios_vendido": negocios_vendido,
        "volume_comprado": volume_comprado,
        "volume_vendido": volume_vendido,
        "stop_premio_por_contrato": stop_premio_por_contrato,
        "stop_premio_total": stop_premio_total,
        "lucro_alvo_total": lucro_alvo_total,
        "dias_max_holding": dias_max_holding,
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

    # Código do strike (sufixo) entre parênteses, se disponível (dados reais)
    sufixo1 = trava.get("sufixo_comprado")
    sufixo2 = trava.get("sufixo_vendido")
    cod1 = f" ({sufixo1})" if sufixo1 else ""
    cod2 = f" ({sufixo2})" if sufixo2 else ""

    # Data de vencimento: real (vencimento_data) ou estimativa (dias úteis)
    if trava.get("vencimento_data"):
        venc_txt = f"Vencimento: {trava['vencimento_data']} ({trava['dias_vencimento']} dias úteis)"
    else:
        venc_txt = f"Vencimento: ~{trava['dias_vencimento']} dias úteis (estimativa)"

    linhas = [
        f"  📈 <b>{trava['nome']}</b> (ativo R$ {preco_atual:.2f})",
        f"  📅 {venc_txt}",
        f"  ➕ Comprar {tipo} strike R$ {trava['strike_comprado']:.2f}{cod1} "
        f"— prêmio R$ {trava['premio_comprado']:.2f}",
        f"  ➖ Vender {tipo} strike R$ {trava['strike_vendido']:.2f}{cod2} "
        f"— prêmio R$ {trava['premio_vendido']:.2f}",
        f"  💰 Custo por contrato: R$ {trava['custo_liquido']:.2f}",
        f"  💵 Gasto total ({trava['contratos']} contratos): R$ {trava['custo_total']:.2f} "
        f"— {orcamento}",
        f"  🛑 Risco máx: R$ {trava['risco_maximo']:.2f} | "
        f"🎯 Ganho máx: R$ {trava['ganho_maximo']:.2f}",
        f"  ⚖️ Breakeven: R$ {trava['breakeven']:.2f}",
        f"  <i>{fonte_txt}</i>",
    ]

    # Plano de saída claro (o que o usuário pediu)
    linhas.append("  📋 <b>Plano de saída:</b>")
    lucro = trava.get("lucro_alvo_total")
    if lucro:
        linhas.append(f"  ✅ <b>Lucro:</b> saia quando a trava render ~R$ {lucro:.2f} (metade do ganho máx)")
    stop = trava.get("stop_premio_total")
    if stop:
        linhas.append(f"  🛑 <b>Stop no prêmio:</b> se a trava cair pra R$ {stop:.2f} total, saia (perda de 50%)")
    encerrar = trava.get("encerrar_quando")
    if encerrar:
        linhas.append(f"  🎯 <b>Quando o ativo chegar perto de R$ {encerrar:.2f}</b> — a opção OTM valoriza forte, encerre")
    dias = trava.get("dias_max_holding")
    venc = trava.get("vencimento_data")
    if dias:
        info_venc = f" (venc. {venc})" if venc else ""
        linhas.append(f"  ⏳ <b>Prazo máx:</b> segure até ~{dias} dias úteis{info_venc} — depois o tempo come a trava (theta)")

    # Vol implícita e delta, se disponíveis (dados reais)
    extras = []
    vi1 = trava.get("vol_impl_comprado")
    vi2 = trava.get("vol_impl_vendido")
    if vi1 is not None:
        extras.append(f"  📊 Vol impl.: {vi1*100:.1f}% / {vi2*100:.1f}%" if vi2 is not None else f"  📊 Vol impl.: {vi1*100:.1f}%")
    d1 = trava.get("delta_comprado")
    d2 = trava.get("delta_vendido")
    if d1 is not None:
        extras.append(f"  🎯 Delta: {d1:.2f} / {d2:.2f}" if d2 is not None else f"  🎯 Delta: {d1:.2f}")
    # Liquidez real (negócios e volume do último pregão) — mostra que os
    # strikes SÃO negociados, desmentindo possível alegação de "sem liquidez"
    n1 = trava.get("negocios_comprado")
    n2 = trava.get("negocios_vendido")
    v1 = trava.get("volume_comprado")
    v2 = trava.get("volume_vendido")
    if n1 is not None:
        extras.append(
            f"  💧 Liquidez: {n1:.0f} neg. / {v1:.0f} vol (compra) · "
            f"{n2:.0f} neg. / {v2:.0f} vol (venda)"
            if n2 is not None else
            f"  💧 Liquidez: {n1:.0f} neg. / {v1:.0f} vol"
        )
    return "\n".join(linhas + extras)


def calcular_trava_manual(direcao: str, strike_comprado: float, premio_comprado: float,
                          strike_vendido: float, premio_vendido: float,
                          contratos: int = CONTRATOS_PADRAO,
                          gasto_maximo: float = GASTO_MAXIMO_PADRAO) -> dict:
    """
    Calcula a trava usando os PRÊMIOS REAIS que o usuário vê no home broker
    (os preços do último pregão podem oscilar antes de executar).

    direcao: "compra" (Bull Call Spread) ou "venda" (Bear Put Spread)
    strike_comprado: strike da perna COMPRADA
    premio_comprado: prêmio atual da perna comprada (o que você pagaria)
    strike_vendido: strike da perna VENDIDA
    premio_vendido: prêmio atual da perna vendida (o que você receberia)

    Retorna dict com custo líquido, risco, ganho, breakeven e se compensa.
    """
    direcao = direcao.lower()
    if direcao not in ("compra", "venda"):
        raise ValueError("direcao deve ser 'compra' ou 'venda'")

    tipo = "call" if direcao == "compra" else "put"
    nome = "TRAVA DE ALTA (Bull Call Spread)" if direcao == "compra" else "TRAVA DE BAIXA (Bear Put Spread)"

    premio_comprado = max(float(premio_comprado), 0.0)
    premio_vendido = max(float(premio_vendido), 0.0)
    custo_liquido = round(premio_comprado - premio_vendido, 2)
    if custo_liquido < 0.05:
        custo_liquido = round(premio_comprado, 2)  # não pode ficar de graça

    custo_total = round(custo_liquido * contratos, 2)

    if direcao == "compra":
        if strike_vendido <= strike_comprado:
            raise ValueError("Na compra, o strike vendido deve ser MAIOR que o comprado")
        largura = strike_vendido - strike_comprado
        ganho_max = round((largura - custo_liquido) * contratos, 2)
        breakeven = round(strike_comprado + custo_liquido, 2)
        encerrar_quando = strike_comprado
    else:
        if strike_vendido >= strike_comprado:
            raise ValueError("Na venda, o strike vendido deve ser MENOR que o comprado")
        largura = strike_comprado - strike_vendido
        ganho_max = round((largura - custo_liquido) * contratos, 2)
        breakeven = round(strike_comprado - custo_liquido, 2)
        encerrar_quando = strike_comprado

    risco_max = custo_total
    dentro_orcamento = custo_total <= gasto_maximo

    # Relação risco/retorno (quantas vezes o ganho cobre o risco)
    if risco_max > 0:
        relacao_rr = round(ganho_max / risco_max, 2)
    else:
        relacao_rr = 0.0

    compensa = (
        dentro_orcamento
        and custo_liquido > 0
        and relacao_rr >= 2.0
        and ganho_max > risco_max
    )

    return {
        "nome": nome,
        "direcao": direcao,
        "tipo": tipo,
        "strike_comprado": strike_comprado,
        "strike_vendido": strike_vendido,
        "premio_comprado": round(premio_comprado, 2),
        "premio_vendido": round(premio_vendido, 2),
        "custo_liquido": custo_liquido,
        "contratos": contratos,
        "custo_total": custo_total,
        "risco_maximo": risco_max,
        "ganho_maximo": ganho_max,
        "relacao_risco_retorno": relacao_rr,
        "breakeven": breakeven,
        "encerrar_quando": encerrar_quando,
        "gasto_maximo": gasto_maximo,
        "dentro_orcamento": dentro_orcamento,
        "compensa": compensa,
        "fonte": "preco_real_manual",
        "observacao": (
            "Cálculo com os PREÇOS ATUAIS que você informou. Confirme a "
            "liquidez (bid/ask e volume) das duas pernas antes de executar."
        ),
    }


def formatar_trava_manual(trava: dict) -> str:
    """
    Formata o resultado da trava com preços manuais para envio no Telegram,
    com veredito claro se compensa operar com os preços atuais.
    """
    tipo = trava["tipo"].upper()

    if trava.get("compensa"):
        veredito = "✅ COMPENSA OPERAR"
    else:
        veredito = "⚠️ AVALIAR (relação risco/retorno baixa ou fora do orçamento)"

    orcamento = "✅ dentro do orçamento" if trava.get("dentro_orcamento") else "❌ acima do orçamento de R$ {:.0f}".format(trava.get("gasto_maximo", GASTO_MAXIMO_PADRAO))

    linhas = [
        f"  📈 <b>{trava['nome']}</b>",
        f"  ➕ Comprar {tipo} {trava['strike_comprado']:.2f} — prêmio R$ {trava['premio_comprado']:.2f}",
        f"  ➖ Vender {tipo} {trava['strike_vendido']:.2f} — prêmio R$ {trava['premio_vendido']:.2f}",
        f"  💰 Custo líquido por contrato: R$ {trava['custo_liquido']:.2f}",
        f"  💵 Gasto total ({trava['contratos']} contratos): R$ {trava['custo_total']:.2f} — {orcamento}",
        f"  🛑 Risco máx: R$ {trava['risco_maximo']:.2f} | 🎯 Ganho máx: R$ {trava['ganho_maximo']:.2f}",
        f"  ⚖️ Relação risco/retorno: 1:{trava['relacao_risco_retorno']} | Breakeven: R$ {trava['breakeven']:.2f}",
        f"  🏁 <b>{veredito}</b>",
    ]
    return "\n".join(linhas)
