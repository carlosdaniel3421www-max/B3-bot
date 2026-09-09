"""Contrato da API de carteira, com dados sinteticos e sem rede/arquivos reais."""

from copy import deepcopy
import builtins
from html import escape
import io
import socket

import pytest

from carteira import avaliar_carteira, avaliar_nova_operacao, formatar_resumo_carteira


@pytest.fixture(autouse=True)
def sem_io(monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("A API de carteira nao pode acessar arquivos ou rede")
    monkeypatch.setattr(builtins, "open", proibido)
    monkeypatch.setattr(io, "open", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)
    monkeypatch.setattr(socket.socket, "connect", proibido)


@pytest.fixture
def acao():
    return {"ticker": "PETR4", "direcao": "compra", "preco_entrada": 40,
            "stop": 38, "quantidade": 100, "data_entrada": "2026-08-19"}


@pytest.fixture
def trava():
    return {"ticker": "CMIG4", "direcao": "compra", "tipo_operacao": "trava",
            "preco_entrada": 0.13, "stop": 0.065, "quantidade": 100,
            "strike_comprado": 10.86, "strike_vendido": 11.56,
            "premio_comprado": 0.22, "premio_vendido": 0.09,
            "data_entrada": "2026-08-19", "vencimento": "2026-10-16"}


def test_carteira_vazia():
    r = avaliar_carteira({}, 10000, mapa_setores={})
    assert r["status"] == "completo"
    assert r["risco_reais"] == r["risco_pct"] == r["exposicao_nominal_acao"] == 0
    assert r["setores"] == r["detalhes"] == {}
    assert r["permite_nova_operacao"]


def test_agregado_compra_venda_e_trava_sem_compensar(acao, trava):
    venda = dict(acao, ticker="VALE3", direcao="venda", stop=42)
    r = avaliar_carteira({"PETR4": acao, "VALE3": venda, "CMIG4": trava}, 20000,
                         mapa_setores={"PETR4": "Commodities", "VALE3": "Commodities"})
    assert r["risco_reais"] == 413
    assert r["risco_pct"] == 2.065
    assert r["exposicao_nominal_acao"] == 8000
    assert r["debito_travas"] == 13
    assert r["por_direcao"]["compra"] == {
        "risco_reais": 213, "exposicao_nominal_acao": 4000, "debito_travas": 13}
    assert r["por_direcao"]["venda"]["risco_reais"] == 200
    assert r["setores"]["Commodities"] == {
        "compra": 4000, "venda": 4000, "exposicao_nominal_acao": 8000, "exposicao_pct": 40}
    assert r["permite_nova_operacao"]
    assert "margem" not in r and "capital_disponivel" not in r


@pytest.mark.parametrize("direcao,stop,risco", [("compra", 38, 200), ("venda", 42, 200),
                                              ("compra", 40, 0), ("venda", 40, 0)])
def test_risco_stop_e_breakeven(acao, direcao, stop, risco):
    acao.update(direcao=direcao, stop=stop)
    r = avaliar_carteira({"PETR4": acao}, 10000)
    assert r["risco_reais"] == risco
    assert r["exposicao_nominal_acao"] == 4000
    assert r["status"] == "completo"


@pytest.mark.parametrize("direcao,stop", [("compra", 41), ("venda", 39), ("lateral", 40)])
def test_direcao_invalida_nao_vira_risco_absoluto_valido(acao, direcao, stop):
    acao.update(direcao=direcao, stop=stop)
    r = avaliar_carteira({"PETR4": acao}, 10000)
    assert r["status"] == "incompleto" and not r["permite_nova_operacao"]
    assert r["detalhes"]["PETR4"]["risco_reais"] is None


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("stop", [None, 0, 0.065, 0.13, 0.20])
def test_trava_arrisca_debito_integral_nao_stop(trava, direcao, stop):
    if direcao == "venda":
        trava.update(direcao=direcao, strike_comprado=11.56, strike_vendido=10.86)
    if stop is None:
        trava.pop("stop")
    else:
        trava["stop"] = stop
    r = avaliar_carteira({"CMIG4": trava}, 10000)
    assert r["risco_reais"] == r["debito_travas"] == 13
    assert r["exposicao_nominal_acao"] == 0
    assert r["status"] == "completo"


@pytest.mark.parametrize("campo,valor", [("preco_entrada", -0.1), ("preco_entrada", 0),
    ("strike_vendido", 10), ("premio_comprado", 0.1), ("premio_vendido", -1)])
def test_trava_incoerente_bloqueia(trava, campo, valor):
    trava[campo] = valor
    r = avaliar_carteira({"CMIG4": trava}, 10000)
    assert not r["permite_nova_operacao"] and r["status"] == "incompleto"


@pytest.mark.parametrize("quantidade", [None, 0, "ausente"])
@pytest.mark.parametrize("tipo", ["acao", "trava"])
def test_quantidade_desconhecida_visivel_e_nao_zero(acao, trava, quantidade, tipo):
    registro = dict(acao if tipo == "acao" else trava)
    if quantidade == "ausente":
        registro.pop("quantidade")
    else:
        registro["quantidade"] = quantidade
    r = avaliar_carteira({"conhecida": acao, "desconhecida": registro}, 10000)
    assert r["risco_reais"] == 200
    assert r["status"] == "incompleto" and not r["permite_nova_operacao"]
    assert r["detalhes"]["desconhecida"]["risco_reais"] is None
    texto = formatar_resumo_carteira(r)
    assert "subtotais" in texto and "desconhecida" in texto and "indisponivel" in texto


@pytest.mark.parametrize("valor", [float("nan"), float("inf"), -float("inf"), True, "100", 10**400])
@pytest.mark.parametrize("campo", ["preco_entrada", "stop", "quantidade", "alvo", "prazo_maximo_dias"])
def test_numeros_invalidos_em_registro_bloqueiam(acao, campo, valor):
    acao[campo] = valor
    r = avaliar_carteira({"PETR4": acao}, 10000)
    assert r["status"] == "incompleto" and not r["permite_nova_operacao"]


@pytest.mark.parametrize("valor", [-1, 0.5, False])
def test_quantidade_invalida(acao, valor):
    acao["quantidade"] = valor
    assert not avaliar_carteira({"PETR4": acao}, 10000)["permite_nova_operacao"]


@pytest.mark.parametrize("campo,valor", [("capital", 0), ("capital", -1), ("capital", True),
    ("capital", float("nan")), ("capital", float("inf")), ("capital", "10000"),
    ("risco_max_pct", -1), ("risco_max_pct", 101), ("risco_max_pct", float("nan")),
    ("exposicao_setor_max_pct", float("inf")), ("exposicao_setor_max_pct", -1),
    ("exposicao_setor_max_pct", 101), ("exposicao_setor_max_pct", True)])
def test_parametros_globais_invalidos_levantam_valueerror(campo, valor):
    parametros = {"capital": 10000, campo: valor}
    with pytest.raises(ValueError):
        avaliar_carteira({}, **parametros)


@pytest.mark.parametrize("valor", [None, "", "2026-02-30", "20260819", "19/08/2026",
                                    "2026-08-19T10:00:00", True])
def test_data_invalida_nao_oculta_risco_calculavel(acao, valor):
    acao["data_entrada"] = valor
    r = avaliar_carteira({"PETR4": acao}, 10000)
    assert r["risco_reais"] == 200
    assert r["status"] == "incompleto" and not r["permite_nova_operacao"]


def test_datas_referencia_explicita_e_vencimento(trava, acao):
    r = avaliar_carteira({"PETR4": acao}, 10000, data_referencia="2026-08-18")
    assert not r["permite_nova_operacao"]
    for vencimento in ("", "2026-02-30", "2026-08-18", "2026-08-20"):
        trava["vencimento"] = vencimento
        r = avaliar_carteira({"CMIG4": trava}, 10000, data_referencia="2026-08-20")
        assert r["status"] == "incompleto" and r["risco_reais"] == 13
    with pytest.raises(ValueError):
        avaliar_carteira({}, 10000, data_referencia="amanha")


def test_limites_inclusivos_sem_arredondar(acao):
    acao.update(preco_entrada=0.4, stop=0.1, quantidade=100)
    assert avaliar_carteira({"P": acao}, 1000)["permite_nova_operacao"]
    acao["stop"] = 0.099999
    r = avaliar_carteira({"P": acao}, 1000)
    assert r["risco_pct"] > 3 and not r["permite_nova_operacao"]
    acao.update(preco_entrada=40.00001, stop=40)
    r = avaliar_carteira({"P": acao}, 10000, mapa_setores={"PETR4": "Energia"})
    assert r["setores"]["Energia"]["exposicao_pct"] > 40
    assert not r["permite_nova_operacao"]


def test_setores_opcionais_parciais_e_invalidos(acao):
    r = avaliar_carteira({"PETR4": acao}, 10000)
    assert r["setores"] is None and r["permite_nova_operacao"]
    assert any("setorial nao verificado" in a for a in r["alertas"])
    r = avaliar_carteira({"PETR4": acao}, 10000, mapa_setores={})
    assert r["status"] == "incompleto" and not r["permite_nova_operacao"]
    assert r["exposicao_nominal_acao"] == 4000
    for mapa in ([], {"PETR4": ""}, {"PETR4": None}):
        with pytest.raises(ValueError):
            avaliar_carteira({}, 10000, mapa_setores=mapa)


def test_simulacao_aditiva_mesmo_ticker_sem_mutacao(acao):
    posicoes = {"PETR4": acao, "PETR4#nova": dict(acao, quantidade=1)}
    candidato = dict(acao, direcao="venda", stop=42)
    mapa = {"PETR4": "Energia"}
    originais = deepcopy((posicoes, candidato, mapa))
    r = avaliar_nova_operacao(posicoes, candidato, 10000, mapa_setores=mapa)
    assert r["antes"]["risco_reais"] == 202
    assert r["depois"]["risco_reais"] == 402
    assert len(r["depois"]["detalhes"]) == 3
    assert not r["permite_nova_operacao"]
    assert (posicoes, candidato, mapa) == originais
    r["depois"]["detalhes"]["PETR4"]["quantidade"] = 1
    assert (posicoes, candidato, mapa) == originais


def test_simulacao_permitida_e_incompleta(acao):
    r = avaliar_nova_operacao({}, acao, 10000)
    assert r["antes"]["risco_reais"] == 0 and r["depois"]["risco_reais"] == 200
    assert r["permite_nova_operacao"]
    for posicoes, candidato in (({"legada": dict(acao, quantidade=0)}, acao),
                                ({}, dict(acao, quantidade=None))):
        r = avaliar_nova_operacao(posicoes, candidato, 10000)
        assert not r["permite_nova_operacao"]
        assert r["depois"]["status"] == "incompleto"


@pytest.mark.parametrize("candidato", [None, [], {}, {"ticker": ""}, {"ticker": 1}])
def test_candidato_sem_identidade_rejeitado(candidato):
    with pytest.raises(ValueError):
        avaliar_nova_operacao({}, candidato, 10000)


def test_determinismo_ordem_e_sem_io(acao, trava):
    a = avaliar_carteira({"P": acao, "C": trava}, 10000, data_referencia="2026-09-08")
    b = avaliar_carteira({"C": trava, "P": acao}, 10000, data_referencia="2026-09-08")
    assert a == b
    assert formatar_resumo_carteira(a) == formatar_resumo_carteira(b)


def test_html_seguro_e_linguagem_sem_garantias(acao):
    malicioso = '<script>alert("x")</script>&'
    acao["ticker"] = malicioso
    r = avaliar_carteira({malicioso: acao}, 10000, mapa_setores={malicioso: malicioso})
    r["alertas"].append(malicioso)
    texto = formatar_resumo_carteira(r)
    assert malicioso not in texto and escape(malicioso) in texto
    assert "<b>Resumo da carteira</b>" in texto
    assert "nao impede operacoes reais ou manuais" in texto
    assert "Nao ha garantia de lucro" in texto and "stops nao garantem" in texto


def test_estrutura_invalida_e_tipo_desconhecido(acao):
    for posicoes in ([], None, {1: acao}, {"": acao}):
        with pytest.raises(ValueError):
            avaliar_carteira(posicoes, 10000)
    for registro in (None, [], dict(acao, tipo_operacao="opcao_nua")):
        r = avaliar_carteira({"P": registro}, 10000)
        assert "P" in r["detalhes"] and not r["permite_nova_operacao"]


def test_overflow_percentual_nao_retorna_infinito(acao):
    with pytest.raises(ValueError, match="faixa"):
        avaliar_carteira({"P": acao}, 1e-308)


def test_overflow_registro_nao_contamina_subtotais(acao):
    enorme = dict(acao, preco_entrada=1e308, stop=1e308, quantidade=100)
    r = avaliar_carteira({"normal": acao, "enorme": enorme}, 10000)
    assert r["risco_reais"] == 200 and r["exposicao_nominal_acao"] == 4000
    assert r["detalhes"]["enorme"]["risco_reais"] is None
    assert r["status"] == "incompleto" and not r["permite_nova_operacao"]


@pytest.mark.parametrize("campo", ["preco_entrada", "quantidade", "stop", "strike_comprado",
                                   "strike_vendido", "premio_comprado", "premio_vendido"])
@pytest.mark.parametrize("valor", [float("nan"), float("inf"), -float("inf"), True])
def test_trava_rejeita_nao_finitos_e_booleanos(trava, campo, valor):
    trava[campo] = valor
    r = avaliar_carteira({"CMIG4": trava}, 10000)
    assert r["status"] == "incompleto" and not r["permite_nova_operacao"]


def test_limites_zero_e_personalizados(acao):
    assert not avaliar_carteira({"P": acao}, 10000, risco_max_pct=0)["permite_nova_operacao"]
    acao["stop"] = acao["preco_entrada"]
    assert avaliar_carteira({"P": acao}, 10000, risco_max_pct=0)["permite_nova_operacao"]
    assert not avaliar_carteira({"P": acao}, 10000, exposicao_setor_max_pct=0,
                               mapa_setores={"PETR4": "Energia"})["permite_nova_operacao"]
    acao["stop"] = 30
    assert avaliar_carteira({"P": acao}, 10000, risco_max_pct=10,
                           mapa_setores={"PETR4": "Energia"})["permite_nova_operacao"]
