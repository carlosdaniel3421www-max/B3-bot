# -*- coding: utf-8 -*-
"""Testes do módulo de trava (Bull Call Spread / Bear Put Spread)."""
import pytest
from trava import montar_trava, formatar_trava, estimar_premio, _arredondar_strike, _proximo_strike


def test_montar_trava_compra():
    trava = montar_trava(45.0, "compra")
    assert trava["nome"] == "TRAVA DE ALTA (Bull Call Spread)"
    assert trava["tipo"] == "call"
    assert trava["strike_comprado"] > 45.0
    assert trava["strike_vendido"] > trava["strike_comprado"]
    assert trava["custo_liquido"] > 0
    assert 0 < trava["custo_total"] <= 40  # dentro do orçamento
    assert trava["dentro_orcamento"] is True


def test_montar_trava_venda():
    trava = montar_trava(45.0, "venda")
    assert trava["nome"] == "TRAVA DE BAIXA (Bear Put Spread)"
    assert trava["tipo"] == "put"
    assert trava["strike_comprado"] < 45.0
    assert trava["strike_vendido"] < trava["strike_comprado"]
    assert trava["custo_liquido"] > 0
    assert 0 < trava["custo_total"] <= 40


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


def test_arredondar_strike_grade_b3():
    # Abaixo de 10: múltiplo de 0.50
    assert _arredondar_strike(5.3) == 5.5
    assert _arredondar_strike(5.0) == 5.0
    # Acima de 10: múltiplo de 1.00
    assert _arredondar_strike(45.3) == 45.0
    assert _arredondar_strike(45.7) == 46.0


def test_proximo_strike_sempre_avanca():
    # Verifica que nunca fica preso no mesmo strike (bug do round .5)
    s = 45.0
    visto = {s}
    for _ in range(10):
        s = _proximo_strike(s, "cima")
        assert s > 45.0
        assert s not in visto
        visto.add(s)
    s = 45.0
    for _ in range(10):
        s = _proximo_strike(s, "baixo")
        assert s < 45.0


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
    assert "Vencimento" in texto


def test_formatar_trava_venda():
    trava = montar_trava(45.0, "venda")
    texto = formatar_trava(trava, 45.0)
    assert "TRAVA DE BAIXA" in texto
