# -*- coding: utf-8 -*-
"""Testes da matemática dos indicadores técnicos (sem rede)."""
import pandas as pd
import numpy as np

from b3_swing_analyzer import (
    calcular_medias_moveis,
    calcular_rsi,
    calcular_macd,
    calcular_atr,
    determinar_veredito,
    sugerir_stop_alvo,
    avaliar_ativo,
)


def _df_precos(precos):
    """Cria DataFrame com os preços fornecidos (dados diários artificiais)."""
    import datetime
    idx = pd.date_range("2026-01-01", periods=len(precos), freq="B")
    df = pd.DataFrame({
        "open": precos,
        "high": [p * 1.01 for p in precos],
        "low": [p * 0.99 for p in precos],
        "close": precos,
        "volume": [1000000] * len(precos),
    }, index=idx)
    return df


def test_calcular_medias_moveis_janelas():
    precos = list(range(1, 51))  # 1..50, tendência de alta perfeita
    df = _df_precos(precos)
    df = calcular_medias_moveis(df)
    assert "sma9" in df.columns
    assert "sma21" in df.columns
    assert "sma50" in df.columns
    # Últimos valores devem ser números (não NaN após período suficiente)
    assert not np.isnan(df["sma9"].iloc[-1])
    assert not np.isnan(df["sma21"].iloc[-1])
    # SMA de 50 com 50 pontos: o último deve existir
    assert not np.isnan(df["sma50"].iloc[-1])
    # SMA50 de uma sequência 1..50 = média = 25.5
    assert abs(df["sma50"].iloc[-1] - 25.5) < 1e-6


def test_calcular_rsi_tendencia_sobe():
    # Série só de altas -> RSI deve ficar perto de 100
    precos = list(range(1, 40))
    df = _df_precos(precos)
    df = calcular_rsi(df)
    rsi_final = df["rsi"].iloc[-1]
    assert not np.isnan(rsi_final)
    assert rsi_final > 90  # tendência de alta pura => RSI altíssimo


def test_calcular_rsi_tendencia_cai():
    # Série só de quedas -> RSI deve ficar perto de 0
    precos = list(range(40, 1, -1))
    df = _df_precos(precos)
    df = calcular_rsi(df)
    rsi_final = df["rsi"].iloc[-1]
    assert not np.isnan(rsi_final)
    assert rsi_final < 10


def test_calcular_rsi_faixa_valida():
    # RSI sempre entre 0 e 100
    rng = np.random.default_rng(42)
    precos = list(rng.uniform(10, 50, 60))
    df = _df_precos(precos)
    df = calcular_rsi(df)
    rsi = df["rsi"].dropna()
    assert (rsi >= 0).all()
    assert (rsi <= 100).all()


def test_calcular_macd_colunas():
    precos = list(np.linspace(10, 30, 60))
    df = _df_precos(precos)
    df = calcular_macd(df)
    assert "macd" in df.columns
    assert "macd_sinal" in df.columns
    assert "macd_hist" in df.columns
    assert not np.isnan(df["macd"].iloc[-1])


def test_calcular_atr_positivo():
    precos = list(np.linspace(10, 30, 40))
    df = _df_precos(precos)
    df = calcular_atr(df)
    assert "atr" in df.columns
    atr_final = df["atr"].iloc[-1]
    assert not np.isnan(atr_final)
    assert atr_final > 0


def test_determinar_veredito_entrar():
    v = determinar_veredito(9, "compra")
    assert v["veredito"] == "ENTRAR"


def test_determinar_veredito_aguardar():
    v = determinar_veredito(7, "compra")
    assert v["veredito"] == "AGUARDAR"


def test_determinar_veredito_evitar():
    v = determinar_veredito(4, "compra")
    assert v["veredito"] == "EVITAR"


def test_determinar_veredito_neutro():
    v = determinar_veredito(5, "neutro")
    assert v["veredito"] == "SEM SINAL"


def test_sugerir_stop_alvo_compra():
    # Tendência de alta: stop abaixo, alvo acima
    precos = list(np.linspace(10, 20, 40))
    df = _df_precos(precos)
    df = calcular_medias_moveis(df)
    df = calcular_atr(df)
    from b3_swing_analyzer import calcular_suporte_resistencia
    df = calcular_suporte_resistencia(df)

    sugestao = sugerir_stop_alvo(df, "compra", atr_mult=1.5, risco_retorno=2.0)
    assert sugestao["stop"] < sugestao["preco_entrada"]
    assert sugestao["alvo"] > sugestao["preco_entrada"]


def test_sugerir_stop_alvo_venda():
    precos = list(np.linspace(20, 10, 40))
    df = _df_precos(precos)
    df = calcular_medias_moveis(df)
    df = calcular_atr(df)
    from b3_swing_analyzer import calcular_suporte_resistencia
    df = calcular_suporte_resistencia(df)

    sugestao = sugerir_stop_alvo(df, "venda", atr_mult=1.5, risco_retorno=2.0)
    assert sugestao["stop"] > sugestao["preco_entrada"]
    assert sugestao["alvo"] < sugestao["preco_entrada"]


def test_avaliar_ativo_tendencia_alta():
    # 100 dias subindo -> deve pontuar compra
    precos = list(np.linspace(10, 30, 100))
    df = _df_precos(precos)
    from b3_swing_analyzer import calcular_indicadores
    df = calcular_indicadores(df)
    avaliacao = avaliar_ativo(df)
    assert avaliacao["direcao"] == "compra"
    assert avaliacao["score"] >= 1


def test_avaliar_ativo_retorna_estrutura():
    precos = list(np.random.default_rng(7).uniform(10, 40, 100))
    df = _df_precos(precos)
    from b3_swing_analyzer import calcular_indicadores
    df = calcular_indicadores(df)
    avaliacao = avaliar_ativo(df)
    assert set(["direcao", "score", "motivos", "preco_atual"]).issubset(avaliacao)
    assert 0 <= avaliacao["score"] <= 10
