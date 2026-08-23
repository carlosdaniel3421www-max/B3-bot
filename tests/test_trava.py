# -*- coding: utf-8 -*-
"""Testes do módulo de trava (Bull Call Spread / Bear Put Spread)."""
import pytest
from trava import montar_trava, formatar_trava, estimar_premio, _lotes_strikes


def test_montar_trava_compra():
    trava = montar_trava(45.0, "compra")
    assert trava["nome"] == "TRAVA DE ALTA (Bull Call Spread)"
    assert trava["tipo_perna1"] == "call"
    assert trava["tipo_perna2"] == "call"
    # Perna comprada perto do preço, vendida mais longe
    assert trava["strike_comprado"] > 45.0
    assert trava["strike_vendido"] > trava["strike_comprado"]
    assert trava["custo_liquido"] > 0
    assert trava["risco_maximo"] == trava["custo_liquido"]
    # Ganho máximo = largura do spread - custo
    largura = trava["strike_vendido"] - trava["strike_comprado"]
    assert abs(trava["ganho_maximo"] - (largura - trava["custo_liquido"])) < 0.01
    assert trava["breakeven"] > trava["strike_comprado"]


def test_montar_trava_venda():
    trava = montar_trava(45.0, "venda")
    assert trava["nome"] == "TRAVA DE BAIXA (Bear Put Spread)"
    assert trava["tipo_perna1"] == "put"
    assert trava["tipo_perna2"] == "put"
    # Perna comprada perto do preço (maior strike), vendida mais longe (menor)
    assert trava["strike_comprado"] < 45.0
    assert trava["strike_vendido"] < trava["strike_comprado"]
    assert trava["custo_liquido"] > 0
    assert trava["risco_maximo"] == trava["custo_liquido"]


def test_trava_direcao_invalida():
    with pytest.raises(ValueError):
        montar_trava(45.0, "neutro")


def test_trava_precos_positivos():
    trava = montar_trava(100.0, "compra")
    assert trava["premio_comprado"] >= 0
    assert trava["premio_vendido"] >= 0
    assert trava["strike_comprado"] > 0
    assert trava["strike_vendido"] > 0


def test_trava_compra_ganho_maximo_positivo():
    # Com volatilidade razoável, a trava de alta deve ter ganho máximo > 0
    trava = montar_trava(50.0, "compra", sigma=0.30)
    assert trava["ganho_maximo"] > 0


def test_estimar_premio_otm_mais_barato():
    # Opção mais longe do dinheiro (OTM) deve ter prêmio menor
    premio_perto = estimar_premio(45.0, 46.0, 35, "call", 0.30)
    premio_longe = estimar_premio(45.0, 49.0, 35, "call", 0.30)
    assert premio_perto > premio_longe


def test_estimar_premio_put_mais_barato_longe():
    premio_perto = estimar_premio(45.0, 44.0, 35, "put", 0.30)
    premio_longe = estimar_premio(45.0, 41.0, 35, "put", 0.30)
    assert premio_perto > premio_longe


def test_estimar_premio_valores_extremos():
    assert estimar_premio(0, 10, 35, "call", 0.30) == 0.0
    assert estimar_premio(10, 0, 35, "call", 0.30) == 0.0


def test_lotes_strikes_grade_b3():
    # Abaixo de 10: múltiplo de 0.50
    s1, s2 = _lotes_strikes(5.0, 1.05, 1.10)
    assert abs(s1 - 5.0) < 1.0
    # Acima de 10: múltiplo de 1.00
    s1, s2 = _lotes_strikes(45.0, 1.03, 1.08)
    assert s1 % 1.0 == 0 or abs((s1 * 2) % 1.0) < 0.01


def test_formatar_trava_conteudo():
    trava = montar_trava(45.0, "compra")
    texto = formatar_trava(trava, 45.0)
    assert "TRAVA DE ALTA" in texto
    assert "Comprar" in texto
    assert "Vender" in texto
    assert "Risco máx" in texto
    assert "Ganho máx" in texto
    assert "Breakeven" in texto
    assert "Saia quando" in texto


def test_formatar_trava_venda():
    trava = montar_trava(45.0, "venda")
    texto = formatar_trava(trava, 45.0)
    assert "TRAVA DE BAIXA" in texto
