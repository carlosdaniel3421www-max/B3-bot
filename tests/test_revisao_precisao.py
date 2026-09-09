"""Regressoes de precisao com cadeia e OHLC em memoria, sem rede."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
import math

import pandas as pd
import pytest

import backtest
from cenarios_trava import analisar_cenarios_trava
from selecao_trava import selecionar_trava_por_tese
from trava import calcular_trava_manual, montar_trava


@pytest.fixture(autouse=True)
def ambiente_local(monkeypatch):
    class DataFixa(date):
        @classmethod
        def today(cls):
            return cls(2030, 1, 7)

    def proibido(*args, **kwargs):
        pytest.fail("Rede e precificacao estimada proibidas")

    monkeypatch.setattr("socket.socket.connect", proibido)
    monkeypatch.setattr("socket.create_connection", proibido)
    monkeypatch.setattr("selecao_trava.date", DataFixa)
    monkeypatch.setattr("fonte_opcoes.date", DataFixa)
    monkeypatch.setattr("trava.date", DataFixa)
    monkeypatch.setattr("trava.estimar_premio", proibido)
    monkeypatch.setattr(backtest, "baixar_dados", proibido)


@pytest.fixture(params=["manual", "montar", "selecao"])
def executar_trava(request):
    def executar(direcao, kc, kv, pc, pv, contratos=100, orcamento=40):
        if request.param == "manual":
            return calcular_trava_manual(direcao, kc, pc, kv, pv,
                                         contratos=contratos, gasto_maximo=orcamento)
        sinal = 1 if direcao == "compra" else -1
        preco = float(Decimal(str(kc)) - sinal * Decimal("0.01"))
        lado = "calls" if direcao == "compra" else "puts"
        cadeia = {"data_ultimo_pregao": "2030-01-07", "expirations": [{
            "dt": "2030-01-25", "du": 14, lado: {
                k: {"preco": p, "negocios": 10, "data_hora": "2030-01-07T17:00:00"}
                for k, p in ((kc, pc), (kv, pv))
            },
        }]}
        antes = deepcopy(cadeia)
        try:
            if request.param == "montar":
                return montar_trava(preco, direcao, premio_alvo_perna1=pc,
                                    premio_alvo_perna2=pv, contratos=contratos,
                                    gasto_maximo=orcamento, cadeia_real=cadeia, ticker="TEST4")
            return selecionar_trava_por_tese(cadeia, preco, direcao, kv,
                                             contratos=contratos, orcamento=orcamento)["trava"]
        finally:
            assert cadeia == antes

    return executar


@pytest.mark.parametrize("direcao,kc,kv", [("compra", 10, 10.3), ("venda", 10.3, 10)])
def test_debito_sete_centavos_cabe_em_sete_reais(executar_trava, direcao, kc, kv):
    trava = executar_trava(direcao, kc, kv, 0.17, 0.10, orcamento=7)
    assert trava is not None
    assert trava["custo_liquido"] == 0.07
    assert trava["custo_total"] == trava["risco_maximo"] == 7
    assert trava["dentro_orcamento"] is True
    assert trava["ganho_maximo"] == 23
    analise = analisar_cenarios_trava(trava, kc, alvo_ativo=kv)
    assert analise["largura"] == 0.3
    assert analise["custo_total"] == 7
    assert analise["cenarios"][-1]["pnl_total"] == 23


@pytest.mark.parametrize("direcao,kc,kv", [("compra", 10, 10.3), ("venda", 10.3, 10)])
@pytest.mark.parametrize("premio", [0.4, math.nextafter(0.4, math.inf)])
def test_debito_maior_ou_igual_largura_rejeitado(executar_trava, direcao, kc, kv, premio):
    try:
        resultado = executar_trava(direcao, kc, kv, premio, 0.1, orcamento=100)
    except ValueError:
        return
    assert resultado is None


@pytest.mark.parametrize("direcao,kc,kv", [("compra", 10, 10.3), ("venda", 10.3, 10)])
def test_orcamento_estrito_sem_tolerancia(executar_trava, direcao, kc, kv):
    resultado = executar_trava(direcao, kc, kv, 0.17, 0.1,
                               orcamento=math.nextafter(7, 0))
    assert resultado is None or resultado["dentro_orcamento"] is False


@pytest.mark.parametrize("direcao,kc,kv", [("compra", 10, 10.3), ("venda", 10.3, 10)])
def test_lucro_fracionario_positivo_nao_arredonda_para_zero(executar_trava, direcao, kc, kv):
    trava = executar_trava(direcao, kc, kv, 0.3999999999999, 0.1)
    assert trava is not None
    assert trava["ganho_maximo"] == 1e-11
    assert analisar_cenarios_trava(trava, kc, alvo_ativo=kv)["cenarios"][-1]["pnl_total"] == 1e-11


def test_debito_com_precisao_decimal_maior_que_float(executar_trava):
    trava = executar_trava("compra", 10, 10.3, 0.1234567890123456, 1e-17)
    assert trava is not None
    analise = analisar_cenarios_trava(trava, 10, alvo_ativo=10.3)
    assert analise["custo_total"] == trava["custo_total"]
    assert analise["ganho_maximo"] == trava["ganho_maximo"]


@pytest.mark.parametrize("direcao,kc,kv", [("compra", 10.0001, 10.3004), ("venda", 10.3004, 10.0001)])
def test_fracoes_preservadas_em_todos_os_calculos(executar_trava, direcao, kc, kv):
    trava = executar_trava(direcao, kc, kv, 0.254, 0.081, contratos=37, orcamento=6.401)
    assert trava is not None
    assert trava["custo_liquido"] == 0.173
    assert trava["custo_total"] == 6.401
    assert trava["ganho_maximo"] == 4.7101
    sinal = 1 if direcao == "compra" else -1
    be = float(Decimal(str(kc)) + sinal * Decimal("0.173"))
    assert trava["breakeven"] == be
    analise = analisar_cenarios_trava(trava, kc, alvo_ativo=be, stop_ativo=kv)
    assert analise["largura"] == 0.3003
    assert analise["custo_total"] == trava["custo_total"]
    assert analise["ganho_maximo"] == trava["ganho_maximo"]
    assert analise["cenarios"][-2]["pnl_total"] == 0
    assert analise["cenarios"][-1]["pnl_total"] == 4.7101


def test_debito_abaixo_de_dez_casas_nao_desaparece(executar_trava):
    trava = executar_trava("compra", 10, 10.3, 0.10000000001, 0.1, orcamento=1e-9)
    assert trava is not None
    assert trava["custo_liquido"] == 1e-11
    assert trava["custo_total"] == 1e-9
    assert trava["breakeven"] == 10.00000000001


@pytest.mark.parametrize("direcao,kc,kv,tipo", [
    ("compra", 10, 10.3, "call"), ("venda", 10.3, 10, "put"),
])
def test_cenarios_rejeitam_largura_igual_debito(direcao, kc, kv, tipo):
    with pytest.raises(ValueError, match="largura"):
        analisar_cenarios_trava({"direcao": direcao, "tipo": tipo,
                                "strike_comprado": kc, "strike_vendido": kv,
                                "custo_liquido": 0.3, "contratos": 100}, kc)


@pytest.mark.parametrize("direcao,kc,kv", [("compra", 10, 10.3), ("venda", 10.3, 10)])
def test_payoff_estrito_ao_redor_do_breakeven(direcao, kc, kv):
    trava = calcular_trava_manual(direcao, kc, 0.17, kv, 0.1)
    sinal = 1 if direcao == "compra" else -1
    be = Decimal(str(trava["breakeven"]))
    antes = float(be - sinal * Decimal("0.00000000001"))
    depois = float(be + sinal * Decimal("0.00000000001"))
    analise = analisar_cenarios_trava(trava, kc, alvo_ativo=antes, stop_ativo=depois)
    assert analise["cenarios"][-2]["pnl_total"] == -1e-9
    assert analise["cenarios"][-1]["pnl_total"] == 1e-9


@pytest.fixture
def simular_backtest(monkeypatch):
    def executar(direcao, custos=0.2, slippage=0, fechamento=100, multi=False):
        df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0,
                           "close": fechamento}, index=pd.bdate_range("2025-01-01", periods=311))
        monkeypatch.setattr(backtest, "baixar_dados", lambda *a, **kw: df.copy())
        monkeypatch.setattr(backtest, "calcular_indicadores", lambda dados: dados)
        monkeypatch.setattr(backtest, "avaliar_ativo", lambda dados: {"score": 9, "direcao": direcao})
        monkeypatch.setattr(backtest, "sugerir_stop_alvo", lambda dados, sentido: {
            "stop": 95 if sentido == "compra" else 105,
            "alvo": 105 if sentido == "compra" else 95,
        })
        kwargs = dict(max_dias_holding=0, custos_bps_por_lado=custos,
                      slippage_bps_por_lado=slippage)
        if multi:
            return backtest.rodar_backtest_multi(["X", "Y"], **kwargs)
        return backtest.rodar_backtest("X", **kwargs)

    return executar


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("multi", [False, True])
def test_cem_trades_flat_acumulam_custos_fracionarios(simular_backtest, direcao, multi):
    resultado = simular_backtest(direcao, multi=multi)
    assert resultado["total_trades"] == (200 if multi else 100)
    assert resultado["soma_retornos_pp"] == (-0.8 if multi else -0.4)
    assert resultado["drawdown_soma_pp"] == resultado["soma_retornos_pp"]
    assert resultado["profit_factor"] == resultado["taxa_acerto_pct"] == 0
    for trade in resultado["trades"]:
        assert trade["retorno_bruto_pct"] == 0
        assert trade["custos_pct"] == 0.004
        assert trade["retorno_pct"] == trade["retorno_liquido_pct"] == -0.004


@pytest.mark.parametrize("direcao,sinal", [("compra", 1), ("venda", -1)])
def test_registro_preserva_precos_e_retornos_com_slippage(simular_backtest, direcao, sinal):
    resultado = simular_backtest(direcao, slippage=0.2)
    for trade in resultado["trades"]:
        entrada = 100 * (1 + sinal * 0.2 / 10000)
        saida = 100 * (1 - sinal * 0.2 / 10000)
        bruto = sinal * (saida - entrada) / entrada * 100
        assert trade["preco_entrada"] == entrada
        assert trade["preco_saida"] == saida
        assert trade["retorno_bruto_pct"] == bruto
        assert trade["retorno_pct"] == bruto - 0.004


def test_pequenos_ganhos_nao_viram_zero_nas_estatisticas(simular_backtest):
    resultado = simular_backtest("compra", fechamento=100.005)
    assert resultado["soma_retornos_pp"] == 0.1
    assert resultado["taxa_acerto_pct"] == 100
    assert resultado["profit_factor"] == "inf (sem perdas)"
    assert all(0 < t["retorno_pct"] < 0.005 for t in resultado["trades"])
