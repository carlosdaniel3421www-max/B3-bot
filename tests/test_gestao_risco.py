# -*- coding: utf-8 -*-
"""Testes de gestão de risco e sugestão de opções (matemática pura)."""
from gestao_risco import (
    calcular_tamanho_posicao, calcular_contratos_opcao,
    calcular_contratos_trava, fracao_kelly, risco_com_kelly,
)
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


def test_calcular_contratos_trava_basico():
    # Capital 10000, risco 1%, custo trava R$0.15
    # valor maximo de risco = 100
    # contrato = 100 * 0.15 = R$15 -> 6 contratos
    r = calcular_contratos_trava(10000, 1.0, 0.15)
    assert r["quantidade_contratos"] == 6
    assert r["perda_maxima"] == 90.0


def test_calcular_contratos_trava_custo_zero():
    r = calcular_contratos_trava(10000, 1.0, 0.0)
    assert r["quantidade_contratos"] == 0
    assert "erro" in r


def test_fracao_kelly_50p():
    # 50% de acerto, ganho igual à perda -> Kelly = 0
    k = fracao_kelly(0.5, 1.0, 1.0)
    assert k == 0.0


def test_fracao_kelly_60p():
    # 60% de acerto, ganho=2, perda=1 -> Kelly = 0.4
    k = fracao_kelly(0.6, 2.0, 1.0)
    assert abs(k - 0.4) < 0.01


def test_fracao_kelly_70p():
    # 70% de acerto, ganho=1.5, perda=1 -> Kelly = 0.5
    k = fracao_kelly(0.7, 1.5, 1.0)
    assert abs(k - 0.5) < 0.01


def test_fracao_kelly_valores_invalidos():
    assert fracao_kelly(0.0, 1.0, 1.0) == 0.0
    assert fracao_kelly(1.0, 1.0, 1.0) == 0.0
    assert fracao_kelly(0.5, 0.0, 1.0) == 0.0
    assert fracao_kelly(0.5, 1.0, 0.0) == 0.0


def test_risco_com_kelly_sem_historico():
    # Sem histórico (prob_acerto=0) -> mantém risco padrão
    r = risco_com_kelly(10000, 1.0, 0.0, 1.0, 1.0)
    assert r == 1.0


def test_risco_com_kelly_melhor_que_padrao():
    # Kelly = 0.4, Kelly/4 = 0.10 -> 10% > 1% padrão -> limitado a 1%
    r = risco_com_kelly(10000, 1.0, 0.6, 2.0, 1.0, fator_kelly=0.25)
    assert r == 1.0  # limitado ao padrão


def test_risco_com_kelly_menor_que_padrao():
    # Kelly = 0.05, Kelly/4 = 0.0125 -> 1.25% > 1% padrão -> limitado a 1%
    # Teste com Kelly pequeno
    k = fracao_kelly(0.55, 1.2, 1.0)
    r = risco_com_kelly(10000, 1.0, 0.55, 1.2, 1.0, fator_kelly=0.25)
    assert r <= 1.0
