# -*- coding: utf-8 -*-
"""Testes do filtro do regime IBOV aplicado no screener."""
import pandas as pd
import numpy as np
from unittest.mock import patch

from screener import _processar_ativo, rodar_screener


def _df_tendencia_alta(n=100, inicio=10, fim=30):
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    close = np.linspace(inicio, fim, n)
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.full(n, 1e6),
    }, index=idx)


def _avaliacao_forte_compra():
    """Simula avaliar_ativo retornando 9/10 compra."""
    return {
        "direcao": "compra",
        "score": 9,
        "motivos": ["Tendência de alta confirmada"],
        "preco_atual": 20.0,
    }


def test_screener_limita_compra_em_lateral():
    # IBOV lateral => teto compra 7. Ativo com 9/10 compra deve virar 7.
    regime = {
        "regime": "lateral",
        "tetos": {"compra": 7, "venda": 7},
        "texto_aviso": "Mercado sem direção — compras limitadas a 7/10",
    }
    with patch("screener.baixar_dados", return_value=_df_tendencia_alta()):
        with patch("screener.calcular_indicadores", side_effect=lambda df: df):
            with patch("screener.avaliar_ativo", return_value=_avaliacao_forte_compra()):
                r = _processar_ativo("CMIG4", "2y", False, False, False, regime)
    assert r["score"] == 7
    assert any("Ibovespa" in m for m in r["motivos"])


def test_screener_mantem_compra_em_alta():
    # IBOV alta => teto compra 10. Ativo com 9/10 compra mantém 9.
    regime = {
        "regime": "alta",
        "tetos": {"compra": 10, "venda": 7},
        "texto_aviso": "",
    }
    with patch("screener.baixar_dados", return_value=_df_tendencia_alta()):
        with patch("screener.calcular_indicadores", side_effect=lambda df: df):
            with patch("screener.avaliar_ativo", return_value=_avaliacao_forte_compra()):
                r = _processar_ativo("CMIG4", "2y", False, False, False, regime)
    assert r["score"] == 9


def test_screener_sem_regime_nao_altera():
    with patch("screener.baixar_dados", return_value=_df_tendencia_alta()):
        with patch("screener.calcular_indicadores", side_effect=lambda df: df):
            with patch("screener.avaliar_ativo", return_value=_avaliacao_forte_compra()):
                r = _processar_ativo("CMIG4", "2y", False, False, False, None)
    assert r["score"] == 9


def test_rodar_screener_passa_regime():
    regime = {
        "regime": "lateral",
        "tetos": {"compra": 7, "venda": 7},
        "texto_aviso": "Mercado lateral",
    }
    with patch("screener._processar_ativo", return_value={
        "ticker": "PETR4", "score": 7, "direcao": "compra",
        "preco": 10.0, "motivos": [], "df": _df_tendencia_alta(),
    }):
        resultados = rodar_screener(
            watchlist=["PETR4"], paralelo=False, pausa=0, regime_ibov=regime,
        )
    assert len(resultados) == 1
    assert resultados[0]["ticker"] == "PETR4"
