"""
Módulo de opções — sugere strike e vencimento a partir do sinal técnico
gerado para o ativo-base, com critérios profissionais de seleção.

IMPORTANTE: a B3 não tem uma fonte gratuita e confiável de cadeia de opções
(strikes, vencimentos, gregas, liquidez). Este módulo tem duas frentes:

1. `sugerir_parametros_opcao()` — dá a lógica de QUAL strike/vencimento
   procurar (ex: "PETR4, CALL, strike ~R$ 34, vencimento ~35-45 dias"),
   mesmo sem cadeia real. Você usa isso para buscar manualmente no home
   broker ou na OpLab.

2. `buscar_cadeia_oplab()` — integração pronta com a API da OpLab
   (oplab.com.br), que tem dados reais de opções da B3. Requer uma chave
   de API paga. Preencha OPLAB_TOKEN em config.py para usar.

CRITÉRIOS PROFISSIONAIS DE SELEÇÃO:
- Delta alvo: 0.35-0.45 para equilíbrio entre alavancagem e probabilidade
- Liquidez mínima: volume financeiro > R$ 50k/dia ou open interest > 500 contratos
- Evitar vencimentos muito próximos (<15 dias) por causa do theta decay acelerado
- Considerar volatilidade implícita relativa ao histórico
"""

import requests
from typing import Optional, Dict, List, Tuple


def calcular_delta_aproximado(preco_ativo: float, strike: float, tipo: str, 
                               dias_vencimento: int, vol_implicita: float = 0.35) -> float:
    """
    Calcula delta aproximado usando fórmula simplificada de Black-Scholes.
    Não é preciso como uma calculadora profissional, mas dá uma estimativa
    boa o suficiente para filtrar strikes.
    
    preco_ativo: preço atual do ativo-base
    strike: strike da opção
    tipo: "CALL" ou "PUT"
    dias_vencimento: dias até o vencimento
    vol_implicita: volatilidade implícita anualizada (ex: 0.35 = 35% a.a.)
    """
    import math
    from scipy.stats import norm
    
    if dias_vencimento <= 0 or preco_ativo <= 0 or strike <= 0:
        return 0.5 if tipo == "CALL" else -0.5
    
    T = dias_vencimento / 252  # anos úteis
    sigma = vol_implicita
    
    # Evitar divisão por zero ou raiz negativa
    if T <= 0 or sigma <= 0:
        return 0.5 if tipo == "CALL" else -0.5
    
    d1 = (math.log(preco_ativo / strike) + (sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    
    if tipo == "CALL":
        delta = norm.cdf(d1)
    else:
        delta = norm.cdf(d1) - 1
    
    return round(delta, 3)


def sugerir_parametros_opcao(preco_atual: float, direcao: str, 
                              prazo_dias_min: int = 25, 
                              prazo_dias_max: int = 45,
                              delta_alvo: float = 0.40,
                              tolerancia_delta: float = 0.08) -> dict:
    """
    Sugere o TIPO de strike/vencimento a procurar, com base em regras
    profissionais de swing trade com opções.
    
    delta_alvo: delta ideal da opção (0.40 = equilíbrio entre alavancagem e chance de ITM)
    tolerancia_delta: faixa aceitável em torno do delta alvo (0.32 a 0.48 se delta_alvo=0.40)
    
    Retorna parâmetros detalhados incluindo delta estimado, moneyness, e critérios de liquidez.
    """
    tipo_opcao = "CALL" if direcao == "compra" else "PUT"
    
    # Calcula strikes candidatos baseados em diferentes deltas
    # Para CALL: delta ≈ N(d1), então podemos inverter para achar strike
    # Simplificação: strike ≈ preco * exp(-N^-1(delta) * sigma * sqrt(T))
    
    import math
    from scipy.stats import norm
    
    T_medio = ((prazo_dias_min + prazo_dias_max) / 2) / 252
    sigma_estimado = 0.35  # Volatilidade anualizada estimada (ajuste conforme o ativo)
    
    # Calcula strike teórico para o delta alvo
    try:
        if tipo_opcao == "CALL":
            d1_alvo = norm.ppf(delta_alvo)
            fator_strike = math.exp(-d1_alvo * sigma_estimado * math.sqrt(T_medio) + (sigma_estimado**2 / 2) * T_medio)
            strike_delta_alvo = preco_atual / fator_strike
        else:  # PUT
            d1_alvo = norm.ppf(delta_alvo + 1)  # Put delta é negativo
            fator_strike = math.exp(-d1_alvo * sigma_estimado * math.sqrt(T_medio) + (sigma_estimado**2 / 2) * T_medio)
            strike_delta_alvo = preco_atual / fator_strike
    except:
        # Fallback para cálculo simples se scipy falhar
        if tipo_opcao == "CALL":
            strike_delta_alvo = preco_atual * 1.03
        else:
            strike_delta_alvo = preco_atual * 0.97
    
    # Define faixa de strikes baseada na tolerância de delta
    delta_min = delta_alvo - tolerancia_delta
    delta_max = delta_alvo + tolerancia_delta
    
    try:
        if tipo_opcao == "CALL":
            d1_min = norm.ppf(delta_min)
            d1_max = norm.ppf(delta_max)
            strike_max = preco_atual / math.exp(-d1_min * sigma_estimado * math.sqrt(T_medio))
            strike_min = preco_atual / math.exp(-d1_max * sigma_estimado * math.sqrt(T_medio))
        else:
            d1_min = norm.ppf(delta_min + 1)
            d1_max = norm.ppf(delta_max + 1)
            strike_min = preco_atual / math.exp(-d1_min * sigma_estimado * math.sqrt(T_medio))
            strike_max = preco_atual / math.exp(-d1_max * sigma_estimado * math.sqrt(T_medio))
    except:
        # Fallback
        if tipo_opcao == "CALL":
            strike_min = preco_atual * 1.01
            strike_max = preco_atual * 1.06
        else:
            strike_min = preco_atual * 0.94
            strike_max = preco_atual * 0.99
    
    # Calcula moneyness (quanto ITM/OTM)
    moneyness = (preco_atual - strike_delta_alvo) / preco_atual if tipo_opcao == "CALL" else (strike_delta_alvo - preco_atual) / preco_atual
    moneyness_pct = moneyness * 100
    
    # Classifica a opção
    if abs(moneyness_pct) < 2:
        classificacao = "ATM (no dinheiro)"
    elif moneyness_pct > 0:
        classificacao = f"ITM ({moneyness_pct:.1f}% no dinheiro)"
    else:
        classificacao = f"OTM ({abs(moneyness_pct):.1f}% fora do dinheiro)"
    
    return {
        "tipo_opcao": tipo_opcao,
        "strike_sugerido_aprox": round(strike_delta_alvo, 2),
        "faixa_strike": (round(strike_min, 2), round(strike_max, 2)),
        "delta_alvo": delta_alvo,
        "faixa_delta_aceitavel": (round(delta_min, 2), round(delta_max, 2)),
        "vencimento_sugerido": f"entre {prazo_dias_min} e {prazo_dias_max} dias corridos",
        "classificacao": classificacao,
        "moneyness_pct": round(moneyness_pct, 2),
        "criterios_liquidez": {
            "volume_financeiro_minimo": "R$ 50.000/dia (ideal)",
            "open_interest_minimo": "500 contratos",
            "spread_maximo": "5% entre bid/ask",
        },
        "motivo": (
            f"Strike selecionado para delta ~{delta_alvo:.2f} busca equilíbrio entre "
            f"alavancagem e probabilidade de terminar ITM. Delta de {delta_alvo:.2f} significa "
            f"que a opção move ~R$ {delta_alvo:.2f} para cada R$ 1,00 do ativo. "
            f"Vencimento de {prazo_dias_min}-{prazo_dias_max} dias reduz theta decay acelerado "
            f"(que explode nos últimos 15 dias) mas dá tempo pro movimento acontecer."
        ),
        "observacao": (
            "Confirme ANTES de operar: "
            "1) Volume financeiro > R$ 50k/dia OU open interest > 500 contratos; "
            "2) Spread bid/ask < 5%; "
            "3) Delta real entre 0.32-0.48; "
            "4) Evite vencimentos < 15 dias (theta decay exponencial). "
            "Use a OpLab ou seu home broker para checar esses dados em tempo real."
        ),
        "dicas_profissionais": [
            "Delta 0.40 ≈ 40% de chance de exercer (probabilidade risk-neutral)",
            "Theta decay acelera exponencialmente nos últimos 15 dias — evite",
            "Vega positivo: opção valoriza se volatilidade implícita subir",
            "Gamma máximo em opções ATM perto do vencimento (cuidado!)",
        ],
    }


def buscar_cadeia_oplab(ticker: str, token: str) -> list:
    """
    Busca a cadeia de opções real via API da OpLab.
    Retorna lista de opções com strike, vencimento, tipo, bid/ask, gregas.
    Consulte a documentação atual em https://oplab.com.br/ para o endpoint
    exato, pois a API pode mudar; esta função é um esqueleto pronto para
    ajustar as chaves do JSON de resposta conforme a doc vigente.
    """
    url = f"https://api.oplab.com.br/v3/market/options/{ticker.upper()}"
    headers = {"Access-Token": token}
    resposta = requests.get(url, headers=headers)
    resposta.raise_for_status()
    return resposta.json()


def escolher_melhor_opcao(cadeia: list, strike_alvo: float, tipo_opcao: str, 
                           dias_min: int, dias_max: int,
                           delta_alvo: float = 0.40,
                           tolerancia_delta: float = 0.08,
                           volume_minimo: float = 50000,
                           open_interest_minimo: int = 500) -> dict:
    """
    Dado o retorno de buscar_cadeia_oplab, filtra pelo tipo e vencimento
    desejado e escolhe a opção com MELHOR combinação de:
    1. Delta dentro da faixa alvo (prioridade máxima)
    2. Liquidez (volume + open interest)
    3. Strike próximo do alvo
    4. Spread bid/ask razoável
    
    Parâmetros:
    - cadeia: lista de opções retornado pela OpLab
    - strike_alvo: strike sugerido pela análise técnica
    - tipo_opcao: "CALL" ou "PUT"
    - dias_min/dias_max: janela de vencimento em dias
    - delta_alvo: delta ideal (padrão 0.40)
    - tolerancia_delta: faixa aceitável de delta (padrão 0.08 = ±8%)
    - volume_minimo: volume financeiro mínimo em R$ (padrão 50k)
    - open_interest_minimo: contratos em aberto mínimos (padrão 500)
    
    Retorna a melhor opção encontrada OU a menos pior se nenhuma bater todos critérios.
    NOTA: ajuste os nomes de campos conforme o formato real retornado pela OpLab.
    """
    # Filtra por tipo e vencimento
    candidatas = [
        o for o in cadeia
        if o.get("type", "").upper() == tipo_opcao
        and dias_min <= o.get("days_to_maturity", 0) <= dias_max
    ]
    
    if not candidatas:
        return {}
    
    # Calcula score para cada candidata
    def calcular_score(opcao: dict) -> float:
        score = 0.0
        
        # 1. Delta na faixa alvo (peso máximo: 50 pontos)
        delta = opcao.get("delta", 0.5)
        if tipo_opcao == "PUT":
            delta = abs(delta)  # Put delta é negativo, mas queremos magnitude
        
        delta_min = delta_alvo - tolerancia_delta
        delta_max = delta_alvo + tolerancia_delta
        
        if delta_min <= delta <= delta_max:
            # Delta perfeito = 50 pontos, cai linearmente conforme se afasta
            distancia_delta = min(abs(delta - delta_alvo), tolerancia_delta)
            score += 50 * (1 - distancia_delta / tolerancia_delta)
        else:
            # Fora da faixa: penalidade proporcional à distância
            distancia_fora = min(abs(delta - delta_min), abs(delta - delta_max))
            score += max(0, 30 - distancia_fora * 100)
        
        # 2. Liquidez: volume financeiro (peso: 25 pontos)
        volume_fin = opcao.get("volume_financial", opcao.get("volume", 0) * opcao.get("last_price", 0))
        if volume_fin >= volume_minimo * 2:
            score += 25
        elif volume_fin >= volume_minimo:
            score += 25 * (volume_fin / volume_minimo)
        else:
            score += 10 * (volume_fin / volume_minimo) if volume_fin > 0 else 0
        
        # 3. Liquidez: open interest (peso: 15 pontos)
        oi = opcao.get("open_interest", 0)
        if oi >= open_interest_minimo * 2:
            score += 15
        elif oi >= open_interest_minimo:
            score += 15 * (oi / open_interest_minimo)
        else:
            score += 5 * (oi / open_interest_minimo) if oi > 0 else 0
        
        # 4. Spread bid/ask baixo (peso: 10 pontos)
        bid = opcao.get("bid", 0)
        ask = opcao.get("ask", 0)
        if bid > 0 and ask > 0:
            spread_pct = (ask - bid) / ((bid + ask) / 2) * 100
            if spread_pct <= 3:
                score += 10
            elif spread_pct <= 5:
                score += 7
            elif spread_pct <= 10:
                score += 4
            else:
                score += max(0, 2 - spread_pct / 10)
        
        # 5. Proximidade do strike alvo (peso bônus: até 5 pontos)
        strike = opcao.get("strike", 0)
        if strike > 0:
            distancia_strike_pct = abs(strike - strike_alvo) / strike_alvo * 100
            score += max(0, 5 - distancia_strike_pct / 2)
        
        return score
    
    # Ordena por score (melhor primeiro)
    candidatas_com_score = [(o, calcular_score(o)) for o in candidatas]
    candidatas_com_score.sort(key=lambda x: x[1], reverse=True)
    
    melhor_opcao = candidatas_com_score[0][0]
    melhor_score = candidatas_com_score[0][1]
    
    # Adiciona metadados de análise à opção retornada
    resultado = melhor_opcao.copy()
    resultado["score_selecao"] = round(melhor_score, 2)
    resultado["delta"] = melhor_opcao.get("delta", 0.5)
    resultado["gamma"] = melhor_opcao.get("gamma", 0)
    resultado["theta"] = melhor_opcao.get("theta", 0)
    resultado["vega"] = melhor_opcao.get("vega", 0)
    resultado["liquidez_ok"] = (
        melhor_opcao.get("volume_financial", 0) >= volume_minimo or
        melhor_opcao.get("open_interest", 0) >= open_interest_minimo
    )
    
    # Avalia se é uma boa opção
    delta = abs(melhor_opcao.get("delta", 0.5))
    delta_min = delta_alvo - tolerancia_delta
    delta_max = delta_alvo + tolerancia_delta
    
    resultado["recomendacao"] = "COMPRAR" if melhor_score >= 70 else "ANALISAR" if melhor_score >= 50 else "EVITAR"
    resultado["motivo_recomendacao"] = []
    
    if delta_min <= delta <= delta_max:
        resultado["motivo_recomendacao"].append(f"Delta {delta:.2f} dentro da faixa ideal ({delta_min:.2f}-{delta_max:.2f})")
    else:
        resultado["motivo_recomendacao"].append(f"Delta {delta:.2f} fora da faixa ideal ({delta_min:.2f}-{delta_max:.2f})")
    
    if resultado["liquidez_ok"]:
        resultado["motivo_recomendacao"].append("Liquidez adequada")
    else:
        resultado["motivo_recomendacao"].append("Liquidez abaixo do ideal — cuidado com spread")
    
    theta = melhor_opcao.get("theta", 0)
    if abs(theta) < 0.05:
        resultado["motivo_recomendacao"].append("Theta decay controlado")
    else:
        resultado["motivo_recomendacao"].append(f"Atenção: theta de {theta:.3f} (decay de ~R$ {abs(theta):.3f}/dia)")
    
    return resultado


def analisar_gregas_portifolio(opcoes: List[dict], preco_ativo: float) -> dict:
    """
    Analisa as gregas agregadas de um portfólio de opções.
    Útil para quem opera mais de uma opção simultaneamente.
    
    Retorna:
    - delta_total: exposição direcional total
    - gamma_total: sensibilidade do delta
    - theta_total: decay temporal diário
    - vega_total: sensibilidade à volatilidade
    - recomendacao: se o portfólio está equilibrado ou desbalanceado
    """
    if not opcoes:
        return {"erro": "Nenhuma opção fornecida"}
    
    delta_total = sum(o.get("delta", 0) for o in opcoes)
    gamma_total = sum(o.get("gamma", 0) for o in opcoes)
    theta_total = sum(o.get("theta", 0) for o in opcoes)
    vega_total = sum(o.get("vega", 0) for o in opcoes)
    
    # Interpretação
    interpretacao = {
        "delta_interpretacao": "",
        "gamma_interpretacao": "",
        "theta_interpretacao": "",
        "vega_interpretacao": "",
    }
    
    # Delta
    if abs(delta_total) < 10:
        interpretacao["delta_interpretacao"] = "Portfólio delta-neutro (sem direção definida)"
    elif delta_total > 0:
        interpretacao["delta_interpretacao"] = f"Posicionado para ALTA (delta +{delta_total:.1f}: lucra {delta_total*100:.0f} reais por R$ 1 de subida)"
    else:
        interpretacao["delta_interpretacao"] = f"Posicionado para BAIXA (delta {delta_total:.1f}: lucra {abs(delta_total)*100:.0f} reais por R$ 1 de queda)"
    
    # Gamma
    if abs(gamma_total) < 5:
        interpretacao["gamma_interpretacao"] = "Gamma baixo: delta estável, menos risco de movimentos bruscos"
    else:
        interpretacao["gamma_interpretacao"] = f"Gamma alto ({gamma_total:.1f}): delta muda rápido — atenção em movimentos grandes do ativo"
    
    # Theta
    interpretacao["theta_interpretacao"] = (
        f"Theta diário de {theta_total:.2f}: {'ganha' if theta_total > 0 else 'perde'} R$ {abs(theta_total):.2f}/dia só com passagem do tempo"
    )
    
    # Vega
    if abs(vega_total) < 10:
        interpretacao["vega_interpretacao"] = "Pouco sensível a mudanças na volatilidade implícita"
    else:
        interpretacao["vega_interpretacao"] = f"Vega alto ({vega_total:.1f}): portfólio sensível a mudanças na volatilidade"
    
    # Recomendação geral
    riscos = []
    if theta_total < -0.1:
        riscos.append("⚠️ Theta negativo alto: tempo trabalhando contra você")
    if abs(gamma_total) > 20:
        riscos.append("⚠️ Gamma muito alto: risco de aceleração brusca do delta")
    if abs(delta_total) > 100:
        riscos.append("⚠️ Delta muito exposto: portfólio altamente direcional")
    
    recomendacao = "PORTFÓLIO EQUILIBRADO" if not riscos else "ATENÇÃO: " + " | ".join(riscos)
    
    return {
        "delta_total": round(delta_total, 2),
        "gamma_total": round(gamma_total, 3),
        "theta_total": round(theta_total, 2),
        "vega_total": round(vega_total, 2),
        "interpretacao": interpretacao,
        "recomendacao": recomendacao,
        "numero_opcoes": len(opcoes),
    }
