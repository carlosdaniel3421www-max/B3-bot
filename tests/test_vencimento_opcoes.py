"""Politica de novas entradas, com datas congeladas e nenhuma rede/JSON real."""

from copy import deepcopy
from datetime import date, timedelta
from unittest.mock import Mock

import pytest

import config
import fonte_opcoes as fonte
import opcoes
import selecao_trava
import trava


class Hoje(date):
    @classmethod
    def today(cls):
        return cls(2030, 1, 20)


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    def proibido(*args, **kwargs):
        pytest.fail("Rede proibida")

    for modulo in (fonte, opcoes, selecao_trava, trava):
        monkeypatch.setattr(modulo, "date", Hoje)
    monkeypatch.setattr("requests.sessions.Session.request", proibido)
    monkeypatch.setattr("socket.socket.connect", proibido)
    monkeypatch.setattr("socket.create_connection", proibido)
    fonte.limpar_cache_cadeia()
    yield
    fonte.limpar_cache_cadeia()


def cadeia(dias, direcao="compra"):
    sinal = 1 if direcao == "compra" else -1
    return {"data_ultimo_pregao": "2030-01-18", "expirations": [{
        "dt": (Hoje.today() + timedelta(days=dias)).isoformat(),
        "du": sum((Hoje.today() + timedelta(days=d)).weekday() < 5
                  for d in range(1, dias + 1)),
        "mensal": True,
        "calls" if sinal == 1 else "puts": {
            100 + sinal: {"preco": 0.25, "negocios": 10, "data_hora": "2030-01-18"},
            100 + 3 * sinal: {"preco": 0.08, "negocios": 10, "data_hora": "2030-01-18"},
        },
    }]}


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("dias,aceita", [(14, True), (30, True), (13, False), (31, False)])
def test_limites_mes_cruzado_em_todas_as_selecoes(monkeypatch, direcao, dias, aceita):
    dados = cadeia(dias, direcao)
    antes = deepcopy(dados)
    sinal = 1 if direcao == "compra" else -1
    tipo = "call" if sinal == 1 else "put"
    monkeypatch.setattr(fonte, "buscar_cadeia_estruturada", lambda *a: dados)
    assert (fonte.buscar_melhor_vencimento(dados) is not None) == aceita
    premio = fonte.buscar_premio_real("TEST4", 100 + sinal, tipo)
    assert (premio is not None) == aceita
    selecao = selecao_trava.selecionar_trava_por_tese(dados, 100, direcao, 100 + 3 * sinal)
    assert (selecao["trava"] is not None) == aceita
    if aceita:
        real = trava.montar_trava(100, direcao, cadeia_real=dados, ticker="TEST4",
                                  permitir_estimativa=False)
        assert real["fonte"] == "real"
        assert real["dias_corridos"] == premio["dias_corridos"] == dias
        assert selecao["trava"]["dias_corridos"] == dias
        assert f"{dias} dias corridos" in selecao["motivo"]
        assert f"{dias} dias corridos" in trava.formatar_trava(real, 100)
    else:
        with pytest.raises(ValueError, match="par real completo"):
            trava.montar_trava(100, direcao, cadeia_real=dados, ticker="TEST4",
                               permitir_estimativa=False)
        assert "14 e 30 dias corridos" in selecao["motivo"]
    cotacao = {"type": tipo.upper(), "strike": 100 + sinal,
               "due_date": dados["expirations"][0]["dt"], "days_to_maturity": dias,
               "ask": 0.25, "bid": 0.20, "volume": 10}
    monkeypatch.setattr(opcoes, "buscar_cadeia_oplab", lambda *a: [cotacao])
    assert bool(opcoes.escolher_melhor_opcao([cotacao], 100 + sinal, tipo)) == aceita
    sugestao = opcoes.sugerir_parametros_opcao_com_preco(100, direcao, "TEST4", token="fake")
    assert (sugestao["fonte"] == "oplab") == aceita
    assert dados == antes


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("dt", [None, "invalida", "2030-01-20", "2030-02-02", "2030-02-20"])
def test_du_plausivel_nao_substitui_data(monkeypatch, direcao, dt):
    dados = cadeia(22, direcao)
    dados["expirations"][0].update(dt=dt, du=15)
    if dt is None:
        del dados["expirations"][0]["dt"]
    assert fonte.buscar_melhor_vencimento(dados) is None
    alvo = 103 if direcao == "compra" else 97
    assert selecao_trava.selecionar_trava_por_tese(dados, 100, direcao, alvo)["trava"] is None
    with pytest.raises(ValueError):
        trava.montar_trava(100, direcao, cadeia_real=dados, ticker="TEST4", permitir_estimativa=False)
    tipo = "CALL" if direcao == "compra" else "PUT"
    cotacao = {"type": tipo, "strike": 101, "days_to_maturity": 22,
               "ask": 0.25, "volume": 10, "due_date": dt}
    assert opcoes.escolher_melhor_opcao([cotacao], 101, tipo) == {}


@pytest.mark.parametrize("du,aceita", [(1, True), (10, True), (60, True), (0, False), (61, False)])
def test_du_e_filtro_adicional_nao_conversao_de_prazo(du, aceita):
    dados = cadeia(14)
    dados["expirations"][0]["du"] = du
    assert bool(fonte.buscar_melhor_vencimento(dados)) == aceita
    resultado = selecao_trava.selecionar_trava_por_tese(dados, 100, "compra", 103)
    assert bool(resultado["trava"]) == aceita
    if aceita:
        assert resultado["trava"]["dias_corridos"] == 14


@pytest.mark.parametrize("informado", [None, 1, 90])
def test_oplab_calcula_prazo_pela_data_nao_contador(monkeypatch, informado):
    cotacao = {"type": "CALL", "strike": 103, "days_to_maturity": informado,
               "ask": 0.25, "volume": 10, "due_date": "2030-02-11"}
    monkeypatch.setattr(opcoes, "buscar_cadeia_oplab", lambda *a: [cotacao])
    real = opcoes._buscar_premio_oplab_para_strike("TEST4", "fake", "CALL", 103)
    assert real["dias_corridos"] == 22


def test_parametros_opcionais_estreitam_sem_contornar_politica(monkeypatch):
    dados = cadeia(14)
    monkeypatch.setattr(fonte, "buscar_cadeia_estruturada", lambda *a: dados)
    filtros = {"dias_corridos_min": 20, "dias_corridos_max": 25}
    assert fonte.buscar_melhor_vencimento(dados, **filtros) is None
    assert fonte.buscar_premio_real("TEST4", 101, "call", **filtros) is None
    assert selecao_trava.selecionar_trava_por_tese(dados, 100, "compra", 103, **filtros)["trava"] is None
    for dias in (13, 31):
        dados = cadeia(dias)
        filtros = {"dias_corridos_min": 1, "dias_corridos_max": 365}
        assert fonte.buscar_melhor_vencimento(dados, **filtros) is None
        assert selecao_trava.selecionar_trava_por_tese(dados, 100, "compra", 103, **filtros)["trava"] is None
    assert opcoes.sugerir_parametros_opcao(100, "compra", 1, 365)["vencimento_sugerido"] == "entre 14 e 30 dias corridos"


def test_defaults_consultam_config_e_ordenam_por_meio_corrido(monkeypatch):
    assert (config.OPCOES_MIN_DIAS_CORRIDOS, config.OPCOES_MAX_DIAS_CORRIDOS) == (14, 30)
    dados = cadeia(14)
    dados["expirations"] += cadeia(22)["expirations"] + cadeia(30)["expirations"]
    assert fonte.buscar_melhor_vencimento(dados)["dt"] == "2030-02-11"
    monkeypatch.setattr(config, "OPCOES_MIN_DIAS_CORRIDOS", 20)
    monkeypatch.setattr(config, "OPCOES_MAX_DIAS_CORRIDOS", 25)
    assert fonte.buscar_melhor_vencimento(cadeia(14)) is None
    assert selecao_trava.selecionar_trava_por_tese(cadeia(14), 100, "compra", 103)["trava"] is None
    assert opcoes.sugerir_parametros_opcao(100, "compra")["vencimento_sugerido"] == "entre 20 e 25 dias corridos"


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("dias", [13, 31])
def test_par_inelegivel_nao_ganha_por_mensal_ou_strike(direcao, dias):
    dados = cadeia(dias, direcao)
    lado = "calls" if direcao == "compra" else "puts"
    sinal = 1 if direcao == "compra" else -1
    dados["expirations"][0][lado][100] = {"preco": 0.30, "negocios": 10,
                                        "data_hora": "2030-01-18"}
    elegivel = cadeia(22, direcao)["expirations"][0]
    elegivel["mensal"] = False
    dados["expirations"].append(elegivel)
    assert fonte.buscar_melhor_vencimento(dados) is elegivel
    selecionada = selecao_trava.selecionar_trava_por_tese(dados, 100, direcao, 100 + 3 * sinal)["trava"]
    assert selecionada["vencimento_data"] == elegivel["dt"]
    assert selecionada["strike_comprado"] == 100 + sinal
    assert trava.montar_trava(100, direcao, cadeia_real=dados, ticker="TEST4",
                              permitir_estimativa=False)["vencimento_data"] == elegivel["dt"]


def test_oplab_limites_opcionais_e_data_ausente():
    cotacao = {"type": "CALL", "strike": 103, "days_to_maturity": 22,
               "ask": 0.25, "volume": 10}
    assert opcoes.escolher_melhor_opcao([cotacao], 103, "CALL") == {}
    cotacao["due_date"] = "2030-02-11"
    assert opcoes.escolher_melhor_opcao([cotacao], 103, "CALL",
                                       dias_corridos_min=23, dias_corridos_max=30) == {}
    assert opcoes.escolher_melhor_opcao([cotacao], 103, "CALL",
                                       dias_corridos_min=22, dias_corridos_max=22) == cotacao
    cotacao["due_date"] = "2030-02-20"
    assert opcoes.escolher_melhor_opcao([cotacao], 103, "CALL",
                                       dias_corridos_min=1, dias_corridos_max=365) == {}


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_estimativa_opcao_usa_22_sobre_365(monkeypatch, direcao):
    bs = Mock(wraps=trava._premio_bs_europeu)
    monkeypatch.setattr(trava, "_premio_bs_europeu", bs)
    resultado = opcoes.sugerir_parametros_opcao_com_preco(100, direcao, "TEST4")
    assert resultado["fonte"] == "estimativa"
    assert resultado["vencimento_sugerido"] == "entre 14 e 30 dias corridos"
    assert bs.call_args.args[2] == 22 / 365


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("pernas", [0, 1])
def test_legado_sem_par_real_nao_estima_se_proibido(monkeypatch, direcao, pernas):
    dados = cadeia(22, direcao) if pernas else None
    if pernas:
        lado = "calls" if direcao == "compra" else "puts"
        dados["expirations"][0][lado].popitem()
    bs = Mock(side_effect=AssertionError("BS proibido"))
    monkeypatch.setattr(trava, "estimar_premio", bs)
    with pytest.raises(ValueError, match="estimativa desabilitada"):
        trava.montar_trava(100, direcao, cadeia_real=dados, ticker="TEST4", permitir_estimativa=False)
    bs.assert_not_called()


@pytest.mark.parametrize("direcao,tipo", [("compra", "call"), ("venda", "put")])
def test_simulacao_pura_preserva_prazo_arbitrario(direcao, tipo):
    resultado = trava.montar_trava(100, direcao, dias_venc=252, permitir_estimativa=True)
    assert resultado["fonte"] == "estimativa"
    assert resultado["dias_vencimento"] == 252
    assert resultado["dias_corridos"] is None
    assert resultado["vencimento_data"] is None
    assert trava.estimar_premio(100, 100, 252, tipo) == round(
        trava._premio_bs_europeu(100, 100, 1, 0.105, 0.30, tipo), 2)


def test_cadeia_bruta_e_estruturada_preservam_todos_vencimentos(monkeypatch):
    from test_fonte_opcoes import _mock_payload

    payload = _mock_payload()
    vencimentos = payload["requests"][1]["results"]["expirations"]
    original = deepcopy(vencimentos[0])
    vencimentos.clear()
    for dias in (1, 13, 14, 22, 30, 31, 90):
        vencimentos.append({**deepcopy(original), "dt": (Hoje.today() + timedelta(days=dias)).isoformat(),
                           "du": sum((Hoje.today() + timedelta(days=d)).weekday() < 5
                                     for d in range(1, dias + 1))})
    antes = deepcopy(payload)
    monkeypatch.setattr(fonte.requests, "get", Mock(return_value=Mock(status_code=200, json=lambda: payload)))
    raw = fonte.buscar_cadeia_opcoesnet("TEST4")
    estruturada = fonte.buscar_cadeia_estruturada("TEST4")
    assert [e["dt"] for e in raw["expirations"]] == [e["dt"] for e in vencimentos]
    assert [e["dt"] for e in estruturada["expirations"]] == [e["dt"] for e in vencimentos]
    assert fonte.buscar_melhor_vencimento(estruturada)["dt"] == "2030-02-11"
    assert len(estruturada["expirations"]) == 7
    assert payload == antes
