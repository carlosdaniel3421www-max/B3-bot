"""Regressoes offline da excecao lateral; limiar zero e hipotese, nao performance."""
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

import b3_swing_analyzer as b3
import screener


def historicos(fim_ativo=110., fim_ibov=100., n=11):
    datas = pd.bdate_range(end="2026-09-08", periods=n)
    ativo = pd.DataFrame({"close": np.linspace(100., fim_ativo, n)}, index=datas)
    ibov = pd.Series(np.linspace(100., fim_ibov, n), index=datas)
    return ativo, ibov


@pytest.mark.parametrize("fim_ativo,fim_ibov,compra,venda", [
    (110, 102, True, False), (90, 98, False, True),
    (105, 110, False, False), (95, 90, False, False),
    (100, 90, False, False),  # superar o indice sem subir nao basta para compra
    (100, 110, False, False),  # ficar atras sem cair nao basta para venda
    (100, 100, False, False), (110, 110, False, False),
])
def test_direcao_absoluta_e_dois_diferenciais(fim_ativo, fim_ibov, compra, venda):
    ativo, ibov = historicos(fim_ativo, fim_ibov)
    antes_ativo, antes_ibov = ativo.copy(deep=True), ibov.copy(deep=True)
    r = b3.comparar_forca_relativa(ativo, ibov)
    assert r["disponivel"]
    assert r["alinhada"] == {"compra": compra, "venda": venda}
    assert r["observacoes"] == 11
    for janela in (5, 10):
        ra = (fim_ativo / ativo.close.iloc[-1 - janela] - 1) * 100
        ri = (fim_ibov / ibov.iloc[-1 - janela] - 1) * 100
        assert r[f"retorno_ativo_{janela}d"] == pytest.approx(ra)
        assert r[f"retorno_ibov_{janela}d"] == pytest.approx(ri)
        assert r[f"diferenca_{janela}d_pp"] == pytest.approx(ra - ri)
    pd.testing.assert_frame_equal(ativo, antes_ativo)
    pd.testing.assert_series_equal(ibov, antes_ibov)


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_dez_dias_tambem_precisam_confirmar(direcao):
    ativo, ibov = historicos(110 if direcao == "compra" else 90)
    ativo.iloc[0, 0] = 120 if direcao == "compra" else 80
    r = b3.comparar_forca_relativa(ativo, ibov)
    assert r["disponivel"]
    assert not r["alinhada"][direcao]


@pytest.mark.parametrize("lado", ["ativo", "ibov"])
@pytest.mark.parametrize("defeito", [
    "vazio", "curto", "nan", "infinito", "zero", "negativo", "texto", "booleano",
    "complexo", "duplicada", "intraday_duplicado", "nat", "desordenada", "numerica",
    "ultima_diferente", "lacuna_data", "futuro",
])
def test_historico_invalido_nao_libera(lado, defeito):
    ativo, ibov = historicos(n=20)
    serie = ativo.close.copy() if lado == "ativo" else ibov.copy()
    if defeito == "vazio":
        serie = serie.iloc[:0]
    elif defeito == "curto":
        serie = serie.iloc[-10:]
    elif defeito in ("nan", "infinito", "zero", "negativo"):
        serie.iloc[-4] = {"nan": np.nan, "infinito": np.inf, "zero": 0,
                           "negativo": -1}[defeito]
    elif defeito == "texto":
        serie = serie.astype(str)
    elif defeito == "booleano":
        serie = serie.astype(bool)
    elif defeito == "complexo":
        serie = serie.astype(complex)
    elif defeito == "desordenada":
        serie = serie.iloc[::-1]
    elif defeito == "numerica":
        serie.index = pd.RangeIndex(len(serie))
    elif defeito == "lacuna_data":
        serie = serie.drop(serie.index[-4])
    else:
        datas = list(serie.index)
        datas[-1] = {
            "duplicada": datas[-2], "intraday_duplicado": datas[-2] + pd.Timedelta(hours=1),
            "nat": pd.NaT, "ultima_diferente": datas[-1] - pd.Timedelta(days=1),
            "futuro": pd.Timestamp("2026-09-10"),
        }[defeito]
        serie.index = pd.DatetimeIndex(datas)
    if lado == "ativo":
        ativo = serie.to_frame("close")
    else:
        ibov = serie
    r = b3.comparar_forca_relativa(ativo, ibov, agora="2026-09-09")
    assert not r["disponivel"]
    assert r["alinhada"] == {"compra": False, "venda": False}
    assert r["motivo"]


def test_nan_em_ambos_nao_comprime_janela():
    ativo, ibov = historicos(n=20)
    ativo.iloc[-4, 0] = ibov.iloc[-4] = np.nan
    assert not b3.comparar_forca_relativa(ativo, ibov)["disponivel"]


def test_historico_antigo_extra_nao_exige_mesmo_inicio():
    ativo, ibov = historicos(n=20)
    assert b3.comparar_forca_relativa(ativo.iloc[-11:], ibov)["disponivel"]
    assert b3.comparar_forca_relativa(ativo, ibov.iloc[-11:])["disponivel"]


@pytest.mark.parametrize("defeito", ["coluna_ausente", "coluna_duplicada", "sem_ibov"])
def test_estrutura_invalida(defeito):
    ativo, ibov = historicos()
    if defeito == "coluna_ausente":
        ativo = ativo.rename(columns={"close": "preco"})
    elif defeito == "coluna_duplicada":
        ativo = pd.concat([ativo, ativo], axis=1)
    else:
        ibov = None
    assert not b3.comparar_forca_relativa(ativo, ibov)["disponivel"]


def test_fechados_fuso_e_limite_defasagem():
    ativo, ibov = historicos()
    ibov.index = ibov.index.tz_localize("America/Sao_Paulo").tz_convert("UTC")
    assert b3.comparar_forca_relativa(ativo, ibov, agora="2026-09-12")["disponivel"]
    assert not b3.comparar_forca_relativa(ativo, ibov, agora="2026-09-13")["disponivel"]
    ativo.loc[pd.Timestamp("2026-09-09"), "close"] = 1  # parcial nao inverte compra
    r = b3.comparar_forca_relativa(ativo, ibov, agora="2026-09-09 23:00-03:00")
    assert r["alinhada"]["compra"]
    assert r["data_final"] == "2026-09-08"


def preparar_screener(monkeypatch, fim_ativo=110, fim_ibov=100, direcao="compra",
                       score=9, teto_score=10):
    ativo, ibov = historicos(fim_ativo, fim_ibov, n=80)
    hoje = pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None).normalize()
    ativo.index = ibov.index = pd.bdate_range(end=hoje - pd.Timedelta(days=1), periods=80)
    baixar = Mock(side_effect=lambda *a, **k: ativo.copy())
    monkeypatch.setattr(screener, "baixar_dados", baixar)
    monkeypatch.setattr(screener, "calcular_indicadores", lambda df: df)
    monkeypatch.setattr(screener, "calcular_indicadores_curto_prazo", lambda df: df)
    avaliacao = Mock(return_value={"score": score, "direcao": direcao,
                                 "preco_atual": fim_ativo, "motivos": [],
                                 "teto_score": teto_score})
    monkeypatch.setattr(screener, "avaliar_ativo", avaliacao)
    monkeypatch.setattr(screener, "avaliar_ativo_curto_prazo", avaliacao)
    regime = b3.classificar_regime_ibov(18, 20, 22, .35, -.5, -1, -2)
    regime["historico_fechamentos"] = ibov
    return ativo, regime, baixar


@pytest.mark.parametrize("curto", [False, True])
@pytest.mark.parametrize("direcao,fim_ativo,fim_ibov,esperado", [
    ("compra", 110, 100, 9), ("venda", 90, 100, 9),
    ("compra", 105, 110, 7), ("venda", 95, 90, 7),
    ("compra", 95, 90, 7), ("venda", 105, 110, 7),
])
def test_screener_condicional(monkeypatch, curto, direcao, fim_ativo, fim_ibov, esperado):
    _, regime, baixar = preparar_screener(monkeypatch, fim_ativo, fim_ibov, direcao)
    r = screener._processar_ativo("TEST4", "1y", curto, False, False, regime)
    assert r["score"] == esperado
    assert r["forca_relativa"]["disponivel"]
    assert any("p.p." in m and "Ativo 5d" in m for m in r["motivos"])
    baixar.assert_called_once_with("TEST4", periodo="1y", incluir_atual=False)


@pytest.mark.parametrize("defeito", ["ausente", "vazio", "defasado", "desalinhado"])
def test_lateral_sem_evidencia_sempre_teto_sete(monkeypatch, defeito):
    ativo, regime, _ = preparar_screener(monkeypatch)
    if defeito == "ausente":
        del regime["historico_fechamentos"]
    elif defeito == "vazio":
        regime["historico_fechamentos"] = pd.Series(dtype=float)
    elif defeito == "defasado":
        ativo.index = ativo.index - pd.Timedelta(days=10)
        regime["historico_fechamentos"].index = ativo.index
    else:
        regime["historico_fechamentos"] = regime["historico_fechamentos"].iloc[:-1]
    r = screener._processar_ativo("TEST4", "1y", False, False, False, regime)
    assert r["score"] == 7
    assert not r["forca_relativa"]["disponivel"]


@pytest.mark.parametrize("score,teto,horario,esperado", [(6, 10, False, 6), (7, 7, True, 7)])
def test_relativa_nao_adiciona_score_nem_desfaz_exaustao(monkeypatch, score, teto, horario, esperado):
    _, regime, _ = preparar_screener(monkeypatch, score=score, teto_score=teto)
    monkeypatch.setattr(screener, "avaliar_timeframe_horario",
                        lambda *a: {"direcao": "compra", "rsi_h": 80})
    r = screener._processar_ativo("TEST4", "1y", False, False, horario, regime)
    assert r["forca_relativa"]["alinhada"]["compra"]
    assert r["score"] == esperado


@pytest.mark.parametrize("nome,tetos,direcao,esperado", [
    ("alta", {"compra": 10, "venda": 7}, "compra", 9),
    ("alta", {"compra": 10, "venda": 7}, "venda", 7),
    ("baixa", {"compra": 7, "venda": 10}, "compra", 7),
    ("baixa", {"compra": 7, "venda": 10}, "venda", 9),
    ("conflito", {"compra": 7, "venda": 7}, "compra", 7),
    ("misto", {"compra": 10, "venda": 10}, "compra", 7),
    ("mixto", {"compra": 10, "venda": 10}, "venda", 7),
])
def test_outros_regimes_nao_recebem_excecao(monkeypatch, nome, tetos, direcao, esperado):
    _, regime, _ = preparar_screener(monkeypatch, direcao=direcao)
    regime.update(regime=nome, tetos=tetos)
    r = screener._processar_ativo("TEST4", "1y", False, False, False, regime)
    assert r["score"] == esperado
    assert r["forca_relativa"] is None


@pytest.mark.parametrize("paralelo", [False, True])
@pytest.mark.parametrize("fornecido", [False, True])
def test_ibov_baixado_e_calculado_uma_vez(monkeypatch, paralelo, fornecido):
    _, lateral, baixar_ativo = preparar_screener(monkeypatch)
    df_ibov = lateral["historico_fechamentos"].to_frame("close")
    df_ibov["high"], df_ibov["low"] = df_ibov.close + 1, df_ibov.close - 1
    baixar_ibov = Mock(return_value=df_ibov)
    calcular = Mock(wraps=b3._calcular_adx_di)
    monkeypatch.setattr(b3, "baixar_dados_ibov", baixar_ibov)
    monkeypatch.setattr(b3, "_calcular_adx_di", calcular)
    avaliar = Mock(wraps=b3.avaliar_regime_ibov)
    monkeypatch.setattr(screener, "avaliar_regime_ibov", avaliar)
    regime = b3.avaliar_regime_ibov() if fornecido else None
    resultados = screener.rodar_screener(["A4", "B4", "C4"], pausa=0,
                                         paralelo=paralelo, regime_ibov=regime)
    assert len(resultados) == 3
    assert all(r["score"] == 9 for r in resultados)
    assert all(r["forca_relativa"]["disponivel"] for r in resultados)
    baixar_ibov.assert_called_once_with("1y")
    calcular.assert_called_once_with(df_ibov)
    assert avaliar.call_count == (0 if fornecido else 1)
    assert baixar_ativo.call_count == 3
    pd.testing.assert_series_equal(df_ibov.close, lateral["historico_fechamentos"],
                                   check_names=False)
