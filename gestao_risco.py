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
