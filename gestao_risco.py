"""
Gestão de risco — calcula QUANTO comprar dado o quanto você aceita perder.

A regra de ouro: nunca arrisque mais que 1-2% do seu capital total numa
única operação. Esse módulo transforma "eu arrisco X%" em "compre N ações"
com base na distância até o stop.
"""


def calcular_tamanho_posicao(capital: float, risco_pct: float, preco_entrada: float, stop: float) -> dict:
    """
    Calcula quantas ações comprar (e o valor em risco) dado o capital
    disponível, o % de risco aceito por operação, e a distância até o stop.
    """
    risco_por_acao = abs(preco_entrada - stop)
    if risco_por_acao <= 0:
        return {"quantidade_acoes": 0, "valor_em_risco": 0, "valor_posicao": 0, "erro": "Stop igual à entrada"}

    valor_maximo_risco = capital * (risco_pct / 100)
    quantidade_acoes = int(valor_maximo_risco / risco_por_acao)

    # Arredonda pra baixo em lote de 100 (lote padrão da B3), mantendo pelo menos 1 lote se der
    lote_padrao = 100
    quantidade_em_lotes = (quantidade_acoes // lote_padrao) * lote_padrao

    quantidade_final = quantidade_em_lotes if quantidade_em_lotes >= lote_padrao else quantidade_acoes

    valor_posicao = quantidade_final * preco_entrada
    valor_em_risco_real = quantidade_final * risco_por_acao

    return {
        "quantidade_acoes": quantidade_final,
        "valor_posicao": round(valor_posicao, 2),
        "valor_em_risco": round(valor_em_risco_real, 2),
        "pct_capital_em_risco": round((valor_em_risco_real / capital) * 100, 2) if capital > 0 else 0,
        "aviso_lote_fracionado": quantidade_em_lotes < lote_padrao,
    }


def calcular_contratos_opcao(capital: float, risco_pct: float, preco_opcao_estimado: float) -> dict:
    """
    Estimativa de quantos contratos de opção comprar, assumindo que o
    prêmio da opção é o valor total em risco (opções compradas têm perda
    máxima limitada ao prêmio pago — diferente de ações, onde o risco é
    a distância até o stop).
    NOTA: preco_opcao_estimado precisa vir de uma cotação real da opção
    (home broker ou OpLab) — este módulo não estima o prêmio sozinho.
    """
    if preco_opcao_estimado <= 0:
        return {"quantidade_contratos": 0, "erro": "Preço da opção precisa ser maior que zero"}

    valor_maximo_risco = capital * (risco_pct / 100)
    lote_opcao = 100  # tamanho de lote padrão pra maioria das opções B3 (confirme no seu home broker)
    quantidade_contratos = int(valor_maximo_risco / (preco_opcao_estimado * lote_opcao))

    return {
        "quantidade_contratos": quantidade_contratos,
        "valor_total_investido": round(quantidade_contratos * preco_opcao_estimado * lote_opcao, 2),
        "perda_maxima": round(quantidade_contratos * preco_opcao_estimado * lote_opcao, 2),
        "observacao": "Perda máxima = prêmio pago. Confirme o preço real da opção antes de operar.",
    }


def calcular_contratos_trava(capital: float, risco_pct: float, custo_liquido_por_contrato: float) -> dict:
    """
    Quantos contratos de TRAVA comprar. Para trava (spread), o risco por
    contrato é o CUSTO LÍQUIDO (débito), que é MENOR que o prêmio da perna
    comprada — dimensiona corretamente sem subutilizar o capital.
    """
    if custo_liquido_por_contrato <= 0:
        return {"quantidade_contratos": 0, "erro": "Custo líquido da trava precisa ser maior que zero"}

    valor_maximo_risco = capital * (risco_pct / 100)
    lote_opcao = 100  # lote padrão de opções B3
    quantidade_contratos = int(valor_maximo_risco / (custo_liquido_por_contrato * lote_opcao))

    return {
        "quantidade_contratos": quantidade_contratos,
        "valor_total_investido": round(quantidade_contratos * custo_liquido_por_contrato * lote_opcao, 2),
        "perda_maxima": round(quantidade_contratos * custo_liquido_por_contrato * lote_opcao, 2),
        "observacao": "Perda máxima = débito da trava (custo líquido). Confirme os prêmios reais antes de operar.",
    }


def fracao_kelly(prob_acerto: float, media_ganho: float, media_perda: float) -> float:
    """
    Fórmula de Kelly: f* = p/b − q/c
      p = probabilidade de acerto (0-1)
      q = 1 − p (probabilidade de erro)
      b = ganho médio quando acerta (em R$/R$ arriscado)
      c = perda média quando erra (em R$/R$ arriscado)

    Retorna a fração ÓTIMA teórica do capital. O uso prático é Kelly/4
    (frações de Kelly são arriscadas em condições reais). Retorna 0 se
    os dados forem insuficientes/inválidos.
    """
    if not (0 < prob_acerto < 1):
        return 0.0
    if media_ganho <= 0 or media_perda <= 0:
        return 0.0

    p = prob_acerto
    q = 1 - p
    b = media_ganho / media_perda  # razão entre ganho e perda
    c = 1.0

    kelly = p - (q / b)  # f* = p − q/b (com c = perda unitária)
    return max(0.0, kelly)


def risco_com_kelly(capital: float, risco_pct_padrao: float,
                    prob_acerto: float, media_ganho: float, media_perda: float,
                    fator_kelly: float = 0.25) -> float:
    """
    Retorna o % de risco recomendado combinando o padrão (risco_pct_padrao)
    com o Kelly fracionado. O Kelly indica a fração ÓTIMA; usamos apenas
    fator_kelly dela (padrão 25% = Kelly/4) e limitamos ao risco padrão.

    Exemplo: Kelly = 0.40 -> fração usada = 0.10 (25%) -> risco = min(1%, 10%)
    Só aplica Kelly se o histórico tiver dados suficientes (prob_acerto válido).
    """
    kelly = fracao_kelly(prob_acerto, media_ganho, media_perda)
    if kelly <= 0:
        return risco_pct_padrao  # sem histórico confiável, mantém o padrão

    risco_kelly = kelly * fator_kelly * 100  # fração -> percentual
    return min(risco_pct_padrao, risco_kelly)
