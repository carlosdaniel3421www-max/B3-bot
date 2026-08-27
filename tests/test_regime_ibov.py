# -*- coding: utf-8 -*-
"""Testes do filtro de regime de mercado (Ibovespa)."""
import numpy as np
import pandas as pd
from unittest.mock import patch

from b3_swing_analyzer import (
    calcular_adx,
    calcular_eficiencia,
    classificar_regime_ibov,
    avaliar_regime_ibov,
)


def _df_tendencia_alta(n=300, inicio=100, fim=200):
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    close = np.linspace(inicio, fim, n)
    return pd.DataFrame({
        "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.full(n, 1e6),
    }, index=idx)


def _df_tendencia_baixa(n=300, inicio=200, fim=100):
    return _df_tendencia_alta(n=n, inicio=inicio, fim=fim)


def _df_choppy(n=300, semente=42):
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    rng = np.random.default_rng(semente)
    close = 100 + np.cumsum(rng.normal(0, 1.5, n))
    return pd.DataFrame({
        "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.full(n, 1e6),
    }, index=idx)


def test_calcular_adx_tendencia_alta_forte():
    df = _df_tendencia_alta()
    adx = calcular_adx(df)
    assert not np.isnan(adx)
    assert adx > 25  # tendência forte


def test_calcular_adx_choppy_baixo():
    df = _df_choppy()
    adx = calcular_adx(df)
    assert not np.isnan(adx)
    assert adx < 25  # tendência fraca


def test_calcular_eficiencia_direcional():
    serie = pd.Series(np.linspace(10, 20, 20))
    assert calcular_eficiencia(serie, 10) > 0.9


def test_calcular_eficiencia_choppy():
    rng = np.random.default_rng(1)
    serie = pd.Series(np.cumsum(rng.normal(0, 1, 50)))
    assert calcular_eficiencia(serie, 10) < 0.7


def test_classificar_ibov_alta():
    r = classificar_regime_ibov(30, 28, 18, 0.8, +2.0, +2.0, +5.0)
    assert r["regime"] == "alta"
    assert r["tetos"]["compra"] == 10
    assert r["tetos"]["venda"] == 7


def test_classificar_ibov_baixa():
    r = classificar_regime_ibov(30, 18, 28, 0.8, -2.0, -2.0, -5.0)
    assert r["regime"] == "baixa"
    assert r["tetos"]["compra"] == 7
    assert r["tetos"]["venda"] == 10


def test_classificar_ibov_lateral():
    r = classificar_regime_ibov(18, 20, 22, 0.35, -0.5, -1.0, -2.0)
    assert r["regime"] == "lateral"
    assert r["tetos"]["compra"] == 7
    assert r["tetos"]["venda"] == 7


def test_classificar_ibov_indisponivel():
    r = classificar_regime_ibov(float("nan"), 20, 22, 0.4, 0, 0, 0)
    assert r["regime"] == "indisponivel"
    assert r["tetos"] == {"compra": 10, "venda": 10}


def test_avaliar_regime_ibov_baixa_dados_reais():
    with patch("b3_swing_analyzer.baixar_dados_ibov", return_value=_df_tendencia_baixa()):
        r = avaliar_regime_ibov()
    assert r["regime"] in ("alta", "baixa", "lateral")
    assert "tetos" in r
    assert "texto_curto" in r


def test_avaliar_regime_ibov_falha_nao_quebra():
    with patch("b3_swing_analyzer.baixar_dados_ibov", return_value=None):
        r = avaliar_regime_ibov()
    assert r["regime"] == "indisponivel"
    assert r["tetos"] == {"compra": 10, "venda": 10}


def test_avaliar_regime_ibov_dados_insuficientes():
    df_curto = _df_tendencia_alta(n=30)
    with patch("b3_swing_analyzer.baixar_dados_ibov", return_value=df_curto):
        r = avaliar_regime_ibov()
    assert r["regime"] == "indisponivel"
