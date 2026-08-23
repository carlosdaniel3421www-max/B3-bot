# -*- coding: utf-8 -*-
"""Testes de gestão de risco e sugestão de opções (matemática pura)."""
from gestao_risco import calcular_tamanho_posicao, calcular_contratos_opcao
from opcoes import sugerir_parametros_opcao


def test_tamanho_posicao_basico():
    # Capital 10000, risco 1%, entrada 10, stop 9 (risco R$1/acao)
    # valor maximo de risco = 100
    # quantidade = 100 / 1 = 100 acoes
    r = calcular_tamanho_posicao(10000, 1.0, 10.0, 9.0)
    assert r["quantidade_acoes"] == 100
    assert r["valor_em_risco"] == 100.0
    assert r["pct_capital_em_risco"] == 1.0


def test_tamanho_posicao_stop_igual_entrada():
    # Stop igual à entrada -> não deve calcular
    r = calcular_tamanho_posicao(10000, 1.0, 10.0, 10.0)
    assert r["quantidade_acoes"] == 0
    assert "erro" in r


def test_tamanho_posicao_capital_zero():
    r = calcular_tamanho_posicao(0, 1.0, 10.0, 9.0)
    assert r["quantidade_acoes"] == 0
    assert r["pct_capital_em_risco"] == 0


def test_tamanho_posicao_nao_ultrapassa_risco():
    # Stop distante -> quantidade pequena, risco nunca passa do limite
    r = calcular_tamanho_posicao(10000, 1.0, 10.0, 5.0)  # risco R$5/acao
    assert r["pct_capital_em_risco"] <= 1.0


def test_contratos_opcao_basico():
    # Capital 10000, risco 1%, premio R$1.00 -> valor max 100
    # contrato = 100 * 1.00 = R$100 -> 1 contrato
    r = calcular_contratos_opcao(10000, 1.0, 1.0)
    assert r["quantidade_contratos"] == 1
    assert r["perda_maxima"] == 100.0


def test_contratos_opcao_premio_zero():
    r = calcular_contratos_opcao(10000, 1.0, 0.0)
    assert r["quantidade_contratos"] == 0
    assert "erro" in r


def test_sugerir_opcao_compra():
    r = sugerir_parametros_opcao(50.0, "compra")
    assert r["tipo_opcao"] == "CALL"
    assert r["strike_sugerido_aprox"] > 50.0  # levemente OTM (acima)
    assert "estimativa" in r["observacao"].lower() or "confirme" in r["observacao"].lower()


def test_sugerir_opcao_venda():
    r = sugerir_parametros_opcao(50.0, "venda")
    assert r["tipo_opcao"] == "PUT"
    assert r["strike_sugerido_aprox"] < 50.0  # levemente OTM (abaixo)


def test_sugerir_opcao_faixa_strike():
    r = sugerir_parametros_opcao(100.0, "compra")
    inferior, superior = r["faixa_strike"]
    assert inferior < superior
