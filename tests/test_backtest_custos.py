"""Cenarios de atrito com OHLC sintetico, sem rede ou arquivos de operacao."""
import runpy
import socket
import sys
from unittest.mock import Mock

import pandas as pd
import pytest

import backtest
import b3_swing_analyzer as analyzer


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    def proibido(*args, **kwargs):
        pytest.fail("Acesso de rede nao autorizado")

    monkeypatch.setattr(socket.socket, "connect", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)
    monkeypatch.setattr(backtest, "baixar_dados", proibido)
    monkeypatch.setattr(analyzer, "baixar_dados", proibido)


@pytest.fixture
def simular(monkeypatch):
    def executar(direcao="compra", barras=None, multi=False, **kwargs):
        base = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}
        barras = [base.copy()] if barras is None else barras
        df = pd.DataFrame([base.copy() for _ in range(211)] + barras,
                          index=pd.bdate_range("2025-01-01", periods=211 + len(barras)))

        def avaliar(dados):
            return {"score": 9 if len(dados) == 211 else 0, "direcao": direcao}

        def limites(dados, sentido):
            assert len(dados) == 211  # Sinal nao pode observar a execucao futura.
            return {"stop": 95.0 if sentido == "compra" else 105.0,
                    "alvo": 110.0 if sentido == "compra" else 90.0}

        for modulo in (backtest, analyzer):
            monkeypatch.setattr(modulo, "baixar_dados", lambda *a, **kw: df.copy())
            monkeypatch.setattr(modulo, "calcular_indicadores", lambda dados: dados)
            monkeypatch.setattr(modulo, "avaliar_ativo", avaliar)
            monkeypatch.setattr(modulo, "sugerir_stop_alvo", limites)
        kwargs.setdefault("max_dias_holding", 0)
        if multi:
            return backtest.rodar_backtest_multi(["X", "Y"], **kwargs)
        return backtest.rodar_backtest("X", **kwargs)

    return executar


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_defaults_zero_preservam_resultado(simular, direcao):
    padrao = simular(direcao)
    explicito = simular(direcao, custos_bps_por_lado=0, slippage_bps_por_lado=0)
    assert padrao == explicito
    trade, = padrao["trades"]
    assert trade["preco_entrada"] == trade["preco_saida"] == 100
    assert trade["retorno_pct"] == trade["retorno_bruto_pct"] == trade["retorno_liquido_pct"] == 0
    assert trade["custos_pct"] == 0


@pytest.mark.parametrize("direcao,sentido", [("compra", 1), ("venda", -1)])
@pytest.mark.parametrize("custos,slippage", [(10, 0), (0, 25), (10, 25), (50, 100)])
def test_cenarios_custos_e_slippage_simetrico(simular, direcao, sentido, custos, slippage):
    resultado = simular(direcao, custos_bps_por_lado=custos, slippage_bps_por_lado=slippage)
    trade, = resultado["trades"]
    entrada = 100 * (1 + sentido * slippage / 10000)
    saida = 100 * (1 - sentido * slippage / 10000)
    bruto = sentido * (saida - entrada) / entrada * 100
    liquido = bruto - 2 * custos / 100
    assert trade["preco_entrada"] == entrada
    assert trade["preco_saida"] == saida
    assert trade["retorno_bruto_pct"] == bruto
    assert trade["custos_pct"] == 2 * custos / 100
    assert trade["retorno_liquido_pct"] == trade["retorno_pct"] == liquido < 0
    assert resultado["soma_retornos_pp"] == resultado["drawdown_soma_pp"] == round(liquido, 2)
    assert resultado["retorno_medio_por_trade_pct"] == resultado["media_perda_pct"] == round(liquido, 2)
    assert resultado["taxa_acerto_pct"] == resultado["profit_factor"] == 0


@pytest.mark.parametrize("direcao,high,low,referencia,motivo", [
    ("compra", 112, 98, 110, "alvo"),
    ("venda", 102, 88, 90, "alvo"),
    ("compra", 102, 94, 95, "stop"),
    ("venda", 106, 98, 105, "stop"),
    ("compra", 112, 94, 95, "stop"),
    ("venda", 106, 88, 105, "stop"),
])
def test_slippage_em_stop_alvo_e_ambiguidade(simular, direcao, high, low, referencia, motivo):
    resultado = simular(direcao, barras=[{"open": 100, "high": high, "low": low, "close": 100}],
                        custos_bps_por_lado=10, slippage_bps_por_lado=25)
    trade, = resultado["trades"]
    fator = 0.9975 if direcao == "compra" else 1.0025
    assert trade["preco_saida"] == referencia * fator
    assert trade["motivo_saida"] == motivo
    assert trade["dias_no_trade"] == 0


@pytest.mark.parametrize("direcao,abertura,referencia,motivo", [
    ("compra", 90, 90, "stop"), ("venda", 112, 112, "stop"),
    ("compra", 115, 110, "alvo"), ("venda", 85, 90, "alvo"),
])
def test_slippage_em_gaps_sem_melhoria_no_alvo(simular, direcao, abertura, referencia, motivo):
    resultado = simular(direcao, barras=[
        {"open": 100, "high": 101, "low": 99, "close": 100},
        {"open": abertura, "high": 120, "low": 80, "close": 100},
    ], max_dias_holding=20, slippage_bps_por_lado=25)
    trade, = resultado["trades"]
    fator = 0.9975 if direcao == "compra" else 1.0025
    assert trade["preco_saida"] == referencia * fator
    assert trade["motivo_saida"] == motivo
    assert trade["dias_no_trade"] == 1


@pytest.mark.parametrize("direcao,fechamento", [("compra", 100.1), ("venda", 99.9)])
def test_custos_transformam_ganho_bruto_em_perda_nas_stats(simular, direcao, fechamento):
    resultado = simular(direcao, barras=[
        {"open": 100, "high": 101, "low": 99, "close": fechamento},
    ], custos_bps_por_lado=10)
    trade, = resultado["trades"]
    assert trade["retorno_bruto_pct"] == pytest.approx(0.1)
    assert trade["retorno_pct"] == trade["retorno_liquido_pct"] == pytest.approx(-0.1)
    assert resultado["taxa_acerto_pct"] == resultado["profit_factor"] == 0
    assert resultado["soma_retornos_pp"] == resultado["drawdown_soma_pp"] == -0.1


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_slippage_nao_muda_condicao_ohlc_da_entrada(simular, direcao):
    # Mesmo com execucao alem do alvo, nao seleciona trades conforme o atrito.
    assert simular(direcao, slippage_bps_por_lado=2000)["total_trades"] == 1
    abertura = 110 if direcao == "compra" else 90
    resultado = simular(direcao, barras=[
        {"open": abertura, "high": 120, "low": 80, "close": 100},
    ], custos_bps_por_lado=10, slippage_bps_por_lado=25)
    assert resultado["total_trades"] == 0


@pytest.mark.parametrize("campo", ["custos_bps_por_lado", "slippage_bps_por_lado"])
@pytest.mark.parametrize("valor", [-1, float("nan"), float("inf"), -float("inf"),
                                  10000, 10001, 10**400, True, False, "10", None, 1j])
@pytest.mark.parametrize("multi", [False, True])
def test_parametros_invalidos_antes_de_download(monkeypatch, campo, valor, multi):
    download = Mock(side_effect=AssertionError("Nao deve baixar dados"))
    monkeypatch.setattr(backtest, "baixar_dados", download)
    funcao = backtest.rodar_backtest_multi if multi else backtest.rodar_backtest
    with pytest.raises(ValueError, match=campo):
        funcao(["X"] if multi else "X", **{campo: valor})
    download.assert_not_called()


@pytest.mark.parametrize("campo", ["custos_bps_por_lado", "slippage_bps_por_lado"])
@pytest.mark.parametrize("valor", [0, 0.5, 9999.99])
def test_intervalo_valido(simular, campo, valor):
    resultado = simular(**{campo: valor})
    assert resultado["total_trades"] == 1
    assert resultado["configuracao"][campo] == valor


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("sem_trades", [False, True])
def test_multi_propaga_atrito_e_configuracao(simular, direcao, sem_trades):
    resultado = simular(direcao, multi=True, periodo="1y", nivel_minimo=10 if sem_trades else 8,
                        custos_bps_por_lado=10, slippage_bps_por_lado=25)
    config = resultado["configuracao"]
    assert config["periodo"] == "1y"
    assert config["max_dias_holding"] == 0
    assert config["custos_bps_por_lado"] == 10
    assert config["slippage_bps_por_lado"] == 25
    assert resultado["falhas"] == []
    assert resultado["total_trades"] == (0 if sem_trades else 2)
    for ativo in resultado["por_ativo"]:
        assert ativo["configuracao"] == config
    if not sem_trades:
        assert resultado["soma_retornos_pp"] == round(sum(
            t["retorno_pct"] for ativo in resultado["por_ativo"] for t in ativo["trades"]), 2)
        assert resultado["taxa_acerto_pct"] == 0


@pytest.mark.parametrize("tickers", [["X"], ["X", "Y"]])
def test_cli_propaga_e_exibe_configuracao_mockada(simular, monkeypatch, capsys, tickers):
    simular()
    monkeypatch.setattr(sys, "argv", ["backtest.py", *tickers, "--max-dias", "0",
                                    "--custos-bps-por-lado", "10",
                                    "--slippage-bps-por-lado", "25"])
    modulo = runpy.run_path(backtest.__file__, run_name="__main__")
    resultado = modulo["resultado"]
    assert resultado["configuracao"]["custos_bps_por_lado"] == 10
    assert resultado["configuracao"]["slippage_bps_por_lado"] == 25
    esperado = (99.75 - 100.25) / 100.25 * 100 - 0.2
    assert all(t["retorno_pct"] == esperado for t in resultado["trades"])
    texto = capsys.readouterr().out
    assert "10.0 bps" in texto and "25.0 bps" in texto
    assert "retorno_pct = retorno_liquido_pct" in texto
    assert "nao e retorno de capital" in texto
    assert "sem custos" not in texto


@pytest.mark.parametrize("flag", ["--custos-bps-por-lado", "--slippage-bps-por-lado"])
@pytest.mark.parametrize("valor", ["-1", "nan", "inf", "10000"])
def test_cli_rejeita_atrito_invalido_antes_de_download(monkeypatch, capsys, flag, valor):
    monkeypatch.setattr(sys, "argv", ["backtest.py", "X", flag, valor])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(backtest.__file__, run_name="__main__")
    assert exc.value.code == 2
    assert "finito >= 0 e < 10000 bps" in capsys.readouterr().err
