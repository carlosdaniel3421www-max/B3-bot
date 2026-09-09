"""Selecao pela tese com relogio fixo, sem rede ou Black-Scholes."""

from copy import deepcopy
from datetime import date
import json

import pytest

from cenarios_trava import analisar_cenarios_trava
from selecao_trava import selecionar_trava_por_tese
from trava import formatar_trava, montar_trava


@pytest.fixture(autouse=True)
def ambiente_local(monkeypatch):
    class DataFixa(date):
        @classmethod
        def today(cls):
            return cls(2030, 1, 7)

    def proibido(*args, **kwargs):
        pytest.fail("Selecao nao deve acessar rede ou estimar premios")

    monkeypatch.setattr("selecao_trava.date", DataFixa)
    monkeypatch.setattr("fonte_opcoes.date", DataFixa)
    monkeypatch.setattr("trava.date", DataFixa)
    monkeypatch.setattr("socket.socket.connect", proibido)
    monkeypatch.setattr("socket.create_connection", proibido)
    monkeypatch.setattr("trava.estimar_premio", proibido)


def opcao(preco, **extras):
    return {"preco": preco, "negocios": 10, "data_hora": "2030-01-07T17:00:00", **extras}


def vencimento(lado, dt="2030-01-25", du=14, tipo="calls", **extras):
    return {"dt": dt, "du": du, tipo: lado, **extras}


def cadeia(*vencimentos):
    return {"expirations": list(vencimentos), "data_ultimo_pregao": "2030-01-07"}


@pytest.fixture
def dados():
    return cadeia(vencimento({101: opcao(1.1), 103: opcao(0.8), 105: opcao(0.7)}))


@pytest.mark.parametrize("direcao,sinal,lado", [("compra", 1, "calls"), ("venda", -1, "puts")])
def test_selecao_simetrica_schema_e_cenarios(direcao, sinal, lado):
    dados = cadeia(vencimento({
        100 + sinal: opcao(1.1, sufixo="A101", vol_impl=30, delta=sinal * 0.4),
        100 + 3 * sinal: opcao(0.8),
        100 + 5 * sinal: opcao(0.7),
    }, tipo=lado))
    antes = deepcopy(dados)
    resultado = selecionar_trava_por_tese(dados, 100, direcao, 100 + 5 * sinal)
    trava = resultado["trava"]
    assert trava["strike_comprado"] == 100 + sinal
    assert trava["strike_vendido"] == 100 + 5 * sinal
    assert trava["custo_total"] == 40
    assert trava["fonte"] == "real"
    assert trava["sufixo_comprado"] == "A101"
    assert trava["sufixo_vendido"] == ""
    assert trava["vencimento_data"] == "2030-01-25"
    assert trava["dias_corridos"] == 18
    analise = analisar_cenarios_trava(trava, 100, 100 + 5 * sinal)
    assert analise["cenarios"][-1]["pnl_total"] == pytest.approx(360)
    assert trava["pnl_alvo_vencimento"] == analise["cenarios"][-1]["pnl_total"]
    assert trava["payoff_alvo_vencimento"] == pytest.approx(3.6)
    referencia = montar_trava(
        100, direcao, premio_alvo_perna1=1.1, premio_alvo_perna2=0.7,
        cadeia_real=dados, ticker="TEST4")
    assert set(referencia) <= set(trava)
    for campo in ("custo_liquido", "custo_total", "risco_maximo", "ganho_maximo", "breakeven"):
        assert trava[campo] == pytest.approx(referencia[campo])
    texto = formatar_trava(trava, 100)
    assert "Comprar" in texto and "Vender" in texto
    assert "valoriza forte" not in texto
    assert "metade do ganho" not in texto
    assert "somente no vencimento" in trava["observacao"]
    assert "nao implica lucro antes" in resultado["motivo"]
    assert json.loads(json.dumps(resultado, allow_nan=False)) == resultado
    assert dados == antes


def test_prioriza_distancia_nao_premio_barato_ou_ganho():
    dados = cadeia(vencimento({
        101: opcao(1.1), 102: opcao(0.9), 104: opcao(0.25), 105: opcao(0.08),
    }))
    trava = selecionar_trava_por_tese(dados, 100, "compra", 105)["trava"]
    assert (trava["strike_comprado"], trava["strike_vendido"]) == (101, 102)


@pytest.mark.parametrize("comprado,vendido,alvo", [(100, 103, 105), (106, 109, 110)])
def test_aceita_atm_e_nao_impoe_corte_cinco_porcento(comprado, vendido, alvo):
    dados = cadeia(vencimento({comprado: opcao(0.6), vendido: opcao(0.3)}))
    trava = selecionar_trava_por_tese(dados, 100, "compra", alvo)["trava"]
    assert trava["strike_comprado"] == comprado


@pytest.mark.parametrize("direcao,lado,strikes,alvo", [
    ("compra", "calls", (101, 106), 105),
    ("venda", "puts", (99, 94), 95),
    ("compra", "calls", (99, 103), 105),
    ("venda", "puts", (101, 97), 95),
    ("compra", "calls", (105, 106), 105),
])
def test_nao_ultrapassa_alvo_nem_compra_contra_sentido(direcao, lado, strikes, alvo):
    dados = cadeia(vencimento(dict(zip(strikes, (opcao(0.6), opcao(0.3)))), tipo=lado))
    assert selecionar_trava_por_tese(dados, 100, direcao, alvo)["trava"] is None


def test_busca_todos_vencimentos_e_nao_cruza_pernas():
    dados = cadeia(
        vencimento({100.5: opcao(0.5)}, mensal=True),
        vencimento({105: opcao(0.1)}, dt="2030-02-01", du=19),
        vencimento({101: opcao(0.6), 104: opcao(0.3)}, dt="2030-02-06", du=22),
    )
    trava = selecionar_trava_por_tese(dados, 100, "compra", 105)["trava"]
    assert trava["strike_comprado"] == 101
    assert trava["vencimento_data"] == "2030-02-06"
    dados["expirations"].pop()
    assert selecionar_trava_por_tese(dados, 100, "compra", 105)["trava"] is None


def test_distancia_tem_prioridade_sobre_vencimento_mensal_e_ordem(dados):
    dados["expirations"].append(vencimento(
        {100.5: opcao(0.6), 104: opcao(0.3)}, dt="2030-02-06", du=22))
    dados["expirations"][0]["mensal"] = True
    esperado = selecionar_trava_por_tese(dados, 100, "compra", 105)
    assert esperado["trava"]["strike_comprado"] == 100.5
    dados["expirations"].reverse()
    for venc in dados["expirations"]:
        venc["calls"] = dict(reversed(list(venc["calls"].items())))
    assert selecionar_trava_por_tese(dados, 100, "compra", 105) == esperado


@pytest.mark.parametrize("du,dt", [
    (0, "2030-01-25"), (61, "2030-01-25"), (None, "2030-01-25"),
    (float("nan"), "2030-01-25"), (True, "2030-01-25"),
    (30, "2030-01-07"), (30, "2029-12-21"), (30, "invalida"), (30, None),
])
def test_vencimento_invalido(dados, du, dt):
    dados["expirations"][0].update(du=du, dt=dt)
    assert selecionar_trava_por_tese(dados, 100, "compra", 105)["trava"] is None


@pytest.mark.parametrize("du,minimo,maximo", [(20, 20, 60), (60, 20, 60), (10, 5, 10), (80, 70, 90)])
def test_faixa_inclusiva_e_personalizada(dados, du, minimo, maximo):
    dados["expirations"][0]["du"] = str(du)
    trava = selecionar_trava_por_tese(dados, 100, "compra", 105, dias_min=minimo, dias_max=maximo)["trava"]
    assert trava["dias_vencimento"] == du


@pytest.mark.parametrize("strike", [101, 105])
@pytest.mark.parametrize("campo,valor", [
    ("preco", None), ("preco", 0), ("preco", -0.1), ("preco", float("nan")),
    ("preco", float("inf")), ("preco", True), ("negocios", None),
    ("negocios", 0), ("negocios", -1), ("negocios", float("inf")),
    ("data_hora", None), ("data_hora", "invalida"),
    ("data_hora", "2030-01-06T17:00:00"), ("data_hora", "2030-01-08T17:00:00"),
    ("strike", 999),
])
def test_rejeita_perna_invalida(strike, campo, valor):
    dados = cadeia(vencimento({101: opcao(0.5), 105: opcao(0.2)}))
    dados["expirations"][0]["calls"][strike][campo] = valor
    resultado = selecionar_trava_por_tese(dados, 100, "compra", 105)
    assert resultado["trava"] is None and resultado["motivo"]


@pytest.mark.parametrize("referencia", [None, "invalida", "2029-12-28", "2030-01-08"])
def test_rejeita_referencia_ausente_antiga_ou_futura(dados, referencia):
    dados["data_ultimo_pregao"] = referencia
    for info in dados["expirations"][0]["calls"].values():
        info["data_hora"] = referencia
    assert selecionar_trava_por_tese(dados, 100, "compra", 105)["trava"] is None


@pytest.mark.parametrize("pc,pv,vendido,orcamento", [
    (0.3, 0.3, 105, 40), (0.2, 0.3, 105, 40), (0.71, 0.3, 105, 40),
    (4.3, 0.3, 105, 1000), (4.4, 0.3, 105, 1000),
    (0.8, 0.3, 101.5, 1000),
])
def test_debito_orcamento_e_payoff_invalidos(pc, pv, vendido, orcamento):
    dados = cadeia(vencimento({101: opcao(pc), vendido: opcao(pv)}))
    assert selecionar_trava_por_tese(dados, 100, "compra", vendido, orcamento=orcamento)["trava"] is None


def test_quantidade_sem_multiplicador_e_premios_sem_arredondamento():
    dados = cadeia(vencimento({101: opcao(0.254), 105: opcao(0.081)}))
    trava = selecionar_trava_por_tese(dados, 100, "compra", 105, contratos=37)["trava"]
    assert trava["contratos"] == 37
    assert trava["custo_liquido"] == pytest.approx(0.173)
    assert trava["breakeven"] == pytest.approx(101.173)
    assert trava["custo_total"] == 6.401
    assert analisar_cenarios_trava(trava, 100, 105)["custo_total"] == pytest.approx(6.401)


@pytest.mark.parametrize("alteracao", [
    {"preco_ativo": 0}, {"preco_ativo": True}, {"preco_ativo": "100"},
    {"preco_ativo": float("nan")}, {"alvo_ativo": float("inf")},
    {"alvo_ativo": 100}, {"alvo_ativo": 99}, {"alvo_ativo": None},
    {"contratos": 0}, {"contratos": 1.5}, {"contratos": 10**1000},
    {"orcamento": -1}, {"dias_min": 0}, {"dias_min": 61},
    {"direcao": "neutro"}, {"direcao": None},
])
def test_parametros_invalidos(dados, alteracao):
    parametros = {"preco_ativo": 100, "direcao": "compra", "alvo_ativo": 105, **alteracao}
    resultado = selecionar_trava_por_tese(dados, **parametros)
    assert resultado["trava"] is None and resultado["motivo"]


@pytest.mark.parametrize("dados", [None, {}, [], {"expirations": None}, cadeia(),
                                       cadeia(None, {}, vencimento([]))])
def test_cadeia_indisponivel_ou_malformada(dados):
    resultado = selecionar_trava_por_tese(dados, 100, "compra", 105)
    assert resultado["trava"] is None and resultado["motivo"]
