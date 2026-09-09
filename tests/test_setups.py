"""Cenarios sinteticos espelhados; sem rede, orders ou persistencia."""

import socket

import numpy as np
import pandas as pd
import pytest

from setups import classificar_setup, validar_gatilho


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("Rede proibida")
    monkeypatch.setattr(socket.socket, "connect", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)
    monkeypatch.setattr(socket, "getaddrinfo", proibido)


def historico(tipo="rompimento"):
    close = np.linspace(80, 100, 81)
    df = pd.DataFrame(dict(open=close, high=close + .2, low=close - .2,
                           close=close, volume=np.full(81, 1000.)),
                      index=pd.bdate_range("2026-01-01", periods=81))
    # O penultimo ainda nao rompe; o ultimo cruza 100.20.
    df.iloc[-3] = [99.5, 100.2, 99.3, 99.5, 1000]
    df.iloc[-1] = [100.1, 100.6, 99.9, 100.5, 1000]
    if tipo == "recuo":
        df.iloc[-10, df.columns.get_loc("high")] = 102
        df.iloc[-3] = [98, 98.2, 96.5, 97.8, 1000]
        df.iloc[-2] = [98, 98.5, 97.8, 98.2, 1000]
        df.iloc[-1] = [98.4, 99.1, 98.3, 99, 1]
    return df


def espelhar(df, direcao):
    if direcao == "compra":
        return df.copy(deep=True)
    r = df.copy(deep=True)
    r["open"], r["close"] = 200 - df.open, 200 - df.close
    r["high"], r["low"] = 200 - df.low, 200 - df.high
    return r


def plano_base(direcao="compra", **kwargs):
    return classificar_setup(espelhar(historico(), direcao), direcao, **kwargs)


def pregao(plano, dias=1):
    return pd.Timestamp(plano["data_sinal"]) + pd.Timedelta(days=dias)


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_rompimento_plano_espelhado_nao_e_execucao(direcao):
    df = espelhar(historico(), direcao)
    original = df.copy(deep=True)
    p = classificar_setup(df, direcao)
    sinal = 1 if direcao == "compra" else -1
    assert p["setup"] == "rompimento"
    assert p["estado"] == "candidato"
    assert p["gatilho"] == pytest.approx(100.61 if sinal == 1 else 99.39)
    assert p["stop"] == pytest.approx(99.9 if sinal == 1 else 100.1)
    assert p["alvo"] == pytest.approx(102.03 if sinal == 1 else 97.97)
    assert p["risco_retorno"] == 2
    assert p["alvo_teorico"] is True
    assert "teorico" in p["motivo"] and "aguardar" in p["motivo"]
    assert p["data_sinal"] == df.index[-1].date().isoformat()
    assert sinal * (p["gatilho"] - df.close.iloc[-1]) > 0
    assert set(p) == {"setup", "estado", "motivo", "direcao", "data_sinal", "gatilho",
                      "stop", "alvo", "risco_retorno", "alvo_teorico",
                      "risco_retorno_min", "distancia_max_atr"}
    pd.testing.assert_frame_equal(df, original)
    assert classificar_setup(df, direcao) == p


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("falha", ["volume", "fechamento", "cruzamento", "tendencia"])
def test_rompimento_exige_todas_confirmacoes(direcao, falha):
    df = historico()
    if falha == "volume":
        df.iloc[-1, df.columns.get_loc("volume")] = 999.99
    elif falha == "fechamento":
        df.iloc[-1, df.columns.get_loc("close")] = 100.2
    elif falha == "cruzamento":
        df.iloc[-3, df.columns.get_loc("high")] = 99.7
    else:
        df.iloc[:50, :4] += 100
    p = classificar_setup(espelhar(df, direcao), direcao)
    assert p["setup"] is None
    assert p["estado"] == "aguardar"


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_volume_media_anterior_exclui_ultimo_e_inclui_vigesimo(direcao):
    df = historico()
    df.iloc[-21, df.columns.get_loc("volume")] = 2000
    df.iloc[-1, df.columns.get_loc("volume")] = 1050
    assert classificar_setup(espelhar(df, direcao), direcao)["setup"] == "rompimento"
    df.iloc[-1, df.columns.get_loc("volume")] = 1049.99
    assert classificar_setup(espelhar(df, direcao), direcao)["setup"] is None


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_recuo_sem_volume_stop_desde_toque(direcao):
    df = historico("recuo")
    p = classificar_setup(espelhar(df, direcao), direcao)
    assert p["setup"] == "recuo"
    assert p["stop"] == pytest.approx(96.5 if direcao == "compra" else 103.5)
    assert p["gatilho"] == pytest.approx(99.11 if direcao == "compra" else 100.89)
    assert p["alvo"] == pytest.approx(99.2 if direcao == "compra" else 100.8)
    assert p["alvo_teorico"] is False
    assert p["estado"] == "cancelado"
    assert p["risco_retorno"] < 2


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_recuo_candidato_com_espaco(direcao):
    df = historico("recuo")
    df.loc[df.index[:-3], "high"] = 106
    p = classificar_setup(espelhar(df, direcao), direcao)
    assert (p["setup"], p["estado"]) == ("recuo", "candidato")
    assert p["alvo"] == (106 if direcao == "compra" else 94)
    assert p["risco_retorno"] == pytest.approx(6.89 / 2.61)


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("falha", ["sma50", "retomada", "toque_antigo"])
def test_recuo_invalido(direcao, falha):
    df = historico("recuo")
    if falha == "sma50":
        df.iloc[-2, df.columns.get_loc("low")] = 90
    elif falha == "retomada":
        df.iloc[-1, df.columns.get_loc("close")] = 98.5
    else:
        df = historico()
        df.iloc[-6, df.columns.get_loc("low")] = 95
        df.iloc[-1, df.columns.get_loc("volume")] = 1
    p = classificar_setup(espelhar(df, direcao), direcao)
    assert p["setup"] is None
    assert p["estado"] == "aguardar"


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_rompimento_tem_prioridade_sobre_recuo(direcao):
    df = historico()
    df.iloc[-2, df.columns.get_loc("low")] = 97
    p = classificar_setup(espelhar(df, direcao), direcao)
    assert p["setup"] == "rompimento"
    assert p["stop"] == (99.9 if direcao == "compra" else 100.1)


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("barreira,estado", [(101, "cancelado"), (102.03, "candidato"),
                                             (103, "candidato"), (100.61, "cancelado")])
def test_barreira_mais_proxima_nao_pode_ser_ignorada(direcao, barreira, estado):
    df = historico()
    df.iloc[-40, df.columns.get_loc("high")] = 110
    df.iloc[-30, df.columns.get_loc("high")] = barreira
    p = classificar_setup(espelhar(df, direcao), direcao)
    assert p["setup"] == "rompimento"
    assert p["estado"] == estado
    assert p["alvo"] == pytest.approx(barreira if direcao == "compra" else 200 - barreira)
    assert p["alvo_teorico"] is False


@pytest.mark.parametrize("posicao,teorico", [(-62, True), (-61, False)])
def test_janela_barreira_exatamente_60_anteriores(posicao, teorico):
    df = historico()
    df.iloc[posicao, df.columns.get_loc("high")] = 105
    assert classificar_setup(df, "compra")["alvo_teorico"] is teorico


def test_minimo_configurado_nao_estica_projecao_2r():
    p = plano_base(risco_retorno_min=2.01)
    assert p["estado"] == "cancelado"
    assert p["risco_retorno"] == 2
    assert p["alvo_teorico"] is True


@pytest.mark.parametrize("n,estado", [(0, "aguardar"), (60, "aguardar"), (61, "candidato")])
def test_aquecimento(n, estado):
    df = historico().iloc[-n:] if n else historico().iloc[:0]
    assert classificar_setup(df, "compra")["estado"] == estado


@pytest.mark.parametrize("coluna", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("valor", [np.nan, np.inf, -np.inf, -1])
def test_ohlcv_invalido(coluna, valor):
    df = historico()
    df.loc[df.index[0], coluna] = valor
    p = classificar_setup(df, "compra")
    assert p["estado"] == "cancelado" and p["setup"] is None


@pytest.mark.parametrize("erro", ["coluna", "duplicada", "indice", "ordem", "data_duplicada",
                                  "nat", "intraday", "geometria", "texto", "bool"])
def test_estrutura_ohlcv_invalida(erro):
    df = historico()
    if erro == "coluna":
        df = df.drop(columns="open")
    elif erro == "duplicada":
        df = pd.concat([df, df[["close"]]], axis=1)
    elif erro == "indice":
        df = df.reset_index(drop=True)
    elif erro == "ordem":
        df = df.iloc[::-1]
    elif erro == "data_duplicada":
        df.index = pd.DatetimeIndex([df.index[0]] * len(df))
    elif erro == "nat":
        df.index = pd.DatetimeIndex([pd.NaT] + list(df.index[1:]))
    elif erro == "intraday":
        df.index = pd.date_range("2026-01-01", periods=len(df), freq="h")
    elif erro == "geometria":
        df.iloc[-1, df.columns.get_loc("low")] = 101
    elif erro == "texto":
        df["close"] = df.close.astype(str)
    else:
        df["volume"] = True
    assert classificar_setup(df, "compra")["estado"] == "cancelado"


@pytest.mark.parametrize("direcao", [None, "neutro", "COMPRA", 1])
def test_direcao_invalida(direcao):
    assert classificar_setup(historico(), direcao)["estado"] == "cancelado"


@pytest.mark.parametrize("parametro", ["risco_retorno_min", "distancia_max_atr"])
@pytest.mark.parametrize("valor", [None, True, np.nan, np.inf, -1, "2"])
def test_parametros_invalidos(parametro, valor):
    assert plano_base(**{parametro: valor})["estado"] == "cancelado"


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("distancia,estado", [(-.1, "aguardar"), (0, "candidato"),
                                              (.5, "candidato"), (.50001, "cancelado")])
def test_validar_direcao_e_gap_limite_inclusivo(direcao, distancia, estado):
    # Folga de RR apenas nesta fixture para isolar o limite de gap.
    p = plano_base(direcao, risco_retorno_min=.5)
    original = p.copy()
    sinal = 1 if direcao == "compra" else -1
    preco = round(p["gatilho"] + sinal * distancia, 5)
    r = validar_gatilho(p, preco, 1, pregao(p))
    assert r["estado"] == estado
    assert p == original
    assert r is not p
    if estado == "candidato":
        assert "nao comprova execucao" in r["motivo"]
    elif estado == "cancelado":
        assert "Gap" in r["motivo"]


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("campo,extra", [("stop", 0), ("stop", -.1), ("alvo", 0), ("alvo", .1)])
def test_stop_e_alvo_atingidos_ou_ultrapassados(direcao, campo, extra):
    p = plano_base(direcao)
    preco = p[campo] + (1 if direcao == "compra" else -1) * extra
    r = validar_gatilho(p, preco, 100, pregao(p))
    assert r["estado"] == "cancelado"
    assert campo in r["motivo"].lower()


@pytest.mark.parametrize("dias,estado", [(-1, "cancelado"), (0, "cancelado"),
                                        (1, "candidato"), (4, "candidato"), (5, "cancelado")])
def test_validade_dias_corridos_aproximacao(dias, estado):
    p = plano_base()
    # Sexta ate terca sao quatro dias corridos, nao quatro pregoes.
    p["data_sinal"] = "2026-09-04"
    r = validar_gatilho(p, p["gatilho"], 1, pregao(p, dias))
    assert r["estado"] == estado
    if estado == "cancelado":
        assert "dias corridos" in r["motivo"] and "aproximacao" in r["motivo"]


@pytest.mark.parametrize("data", [None, "invalida", "NaT", "today", "now", 123, pd.NaT])
def test_data_invalida(data):
    p = plano_base()
    assert validar_gatilho(p, p["gatilho"], 1, data)["estado"] == "cancelado"


def test_fuso_brt_e_indicadores_recalculados_sem_mutacao():
    df = historico()
    df.index = df.index.tz_localize("America/Sao_Paulo").tz_convert("UTC")
    df["sma21"], df["sma50"] = -1, np.nan
    p = classificar_setup(df, "compra")
    assert p == plano_base()
    p["data_sinal"] = "2026-09-04T23:00:00-03:00"
    assert validar_gatilho(p, p["gatilho"], 1, "2026-09-05T02:30:00Z")["estado"] == "cancelado"
    assert validar_gatilho(p, p["gatilho"], 1, "2026-09-05T03:00:00Z")["estado"] == "candidato"


@pytest.mark.parametrize("campo", ["preco", "atr"])
@pytest.mark.parametrize("valor", [None, True, 0, -1, np.inf, np.nan, "100"])
def test_validar_cotacao_atr_invalidos(campo, valor):
    p = plano_base()
    assert validar_gatilho(p, valor if campo == "preco" else p["gatilho"],
                           valor if campo == "atr" else 1, pregao(p))["estado"] == "cancelado"


@pytest.mark.parametrize("campo,valor", [("stop", 101), ("alvo", 100), ("gatilho", 0),
                                         ("risco_retorno", 3), ("distancia_max_atr", -1),
                                         ("risco_retorno_min", 3), ("estado", "cancelado"),
                                         ("direcao", "neutro"), ("alvo_teorico", "sim")])
def test_validar_plano_corrompido(campo, valor):
    p = plano_base()
    p[campo] = valor
    assert validar_gatilho(p, 100.61, 1, pregao(p))["estado"] == "cancelado"


def test_distancia_configurada_preservada_e_aguardar_revalidavel():
    p = plano_base(distancia_max_atr=.2, risco_retorno_min=.5)
    r = validar_gatilho(p, 100.82, 1, pregao(p))
    assert r["estado"] == "cancelado" and "Gap" in r["motivo"]
    assert validar_gatilho(p, 100.81, 1, pregao(p))["estado"] == "candidato"
    aguardando = validar_gatilho(p, 100.5, 1, pregao(p))
    assert validar_gatilho(aguardando, 100.61, 1, pregao(p))["estado"] == "candidato"
    p = plano_base(distancia_max_atr=0)
    assert validar_gatilho(p, 100.61, 1, pregao(p))["estado"] == "candidato"
    assert validar_gatilho(p, 100.62, 1, pregao(p))["estado"] == "cancelado"


@pytest.mark.parametrize("plano", [None, {}, [], {"estado": "candidato"}])
def test_validar_sempre_retorna_dict_com_campos(plano):
    r = validar_gatilho(plano, 100, 1, "2026-09-08")
    assert r["estado"] == "cancelado"
    assert {"setup", "estado", "motivo", "direcao", "data_sinal", "gatilho", "stop",
            "alvo", "risco_retorno", "alvo_teorico"} <= r.keys()


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("posicao,rompe", [(-22, True), (-21, False)])
def test_extremo_rompimento_exatamente_20_anteriores(direcao, posicao, rompe):
    df = historico()
    df.iloc[posicao, df.columns.get_loc("high")] = 105
    p = classificar_setup(espelhar(df, direcao), direcao)
    assert (p["setup"] == "rompimento") is rompe


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("posicao,recuo", [(-6, False), (-5, True), (-1, True)])
def test_toque_janela_5_inclui_ultimo(direcao, posicao, recuo):
    df = historico()
    df.iloc[-1, df.columns.get_loc("volume")] = 0
    df.iloc[posicao, df.columns.get_loc("low")] = 96
    p = classificar_setup(espelhar(df, direcao), direcao)
    assert (p["setup"] == "recuo") is recuo


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_recuo_stop_inclui_extremo_ultimo_e_sma50_igual_permitida(direcao):
    df = historico("recuo")
    df.loc[df.index[:-3], "high"] = 120
    sma50 = df.close.rolling(50).mean().iloc[-1]
    df.iloc[-1, df.columns.get_loc("low")] = sma50
    p = classificar_setup(espelhar(df, direcao), direcao)
    assert p["setup"] == "recuo"
    assert p["stop"] == pytest.approx(sma50 if direcao == "compra" else 200 - sma50)
    df.iloc[-1, df.columns.get_loc("low")] = sma50 - .001
    assert classificar_setup(espelhar(df, direcao), direcao)["setup"] is None


def test_venda_entrada_ou_alvo_nao_positivos_cancelam():
    df = espelhar(historico(), "venda")
    df[df.columns[:4]] *= .0001
    p = classificar_setup(df, "venda")
    assert p["estado"] == "cancelado"
    assert p["gatilho"] == 0
    df = espelhar(historico(), "venda")
    df.iloc[-1, df.columns.get_loc("high")] = 160
    p = classificar_setup(df, "venda")
    assert p["estado"] == "cancelado"
    assert p["alvo"] < 0


def test_rr_minimo_zero_invalido_e_df_nao_dataframe():
    assert plano_base(risco_retorno_min=0)["estado"] == "cancelado"
    assert classificar_setup(None, "compra")["estado"] == "cancelado"


def test_causalidade_usa_apenas_prefixo_fornecido():
    df = historico()
    prefixo = df.copy(deep=True)
    futuro = df.iloc[-2:].copy()
    futuro.index += pd.Timedelta(days=10)
    futuro[futuro.columns[:4]] *= 10
    completo = pd.concat([df, futuro])
    assert classificar_setup(completo.iloc[:len(df)], "compra") == classificar_setup(prefixo, "compra")


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_gap_escala_com_atr(direcao):
    p = plano_base(direcao, risco_retorno_min=.5)
    sinal = 1 if direcao == "compra" else -1
    preco = round(p["gatilho"] + sinal * .25, 2)
    assert validar_gatilho(p, preco, .5, pregao(p))["estado"] == "candidato"
    r = validar_gatilho(p, preco, .49, pregao(p))
    assert r["estado"] == "cancelado" and "Gap" in r["motivo"]


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_rr_2_no_gatilho_rejeita_preco_pior_mesmo_dentro_do_gap(direcao):
    p = plano_base(direcao)
    original = p.copy()
    sinal = 1 if direcao == "compra" else -1
    assert p["risco_retorno"] == p["risco_retorno_min"] == 2
    assert validar_gatilho(p, p["gatilho"], 1, pregao(p))["estado"] == "candidato"
    preco = round(p["gatilho"] + sinal * .01, 2)
    r = validar_gatilho(p, preco, 1, pregao(p))
    assert r["estado"] == "cancelado"
    assert "Risco-retorno no preco informado abaixo do minimo" in r["motivo"]
    assert r["risco_retorno"] == p["risco_retorno"]
    assert p == original


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("distancia,estado", [(.49999, "candidato"),
                                              (.5, "candidato"), (.50001, "cancelado")])
def test_rr_no_preco_limite_minimo_inclusivo_espelhado(direcao, distancia, estado):
    df = historico()
    df.iloc[-30, df.columns.get_loc("high")] = 103.53
    p = classificar_setup(espelhar(df, direcao), direcao)
    original = p.copy()
    sinal = 1 if direcao == "compra" else -1
    # Compra: (103.53 - 101.11) / (101.11 - 99.90) = 2; venda espelhada.
    assert p["estado"] == "candidato" and p["risco_retorno"] > 2
    assert p["risco_retorno_min"] == 2 and p["alvo_teorico"] is False
    preco = round(p["gatilho"] + sinal * distancia, 5)
    # ATR=2 deixa todos os precos dentro do gap permitido, isolando RR.
    r = validar_gatilho(p, preco, 2, pregao(p))
    assert r["estado"] == estado
    if estado == "cancelado":
        assert "Risco-retorno no preco informado abaixo do minimo" in r["motivo"]
    else:
        assert "nao comprova execucao" in r["motivo"]
    assert r["risco_retorno"] == p["risco_retorno"]
    assert p == original


@pytest.mark.parametrize("campo", ["stop", "alvo"])
def test_plano_sem_risco_ou_retorno_nao_validado(campo):
    p = plano_base()
    p[campo] = p["gatilho"]
    assert validar_gatilho(p, p["gatilho"], 1, pregao(p))["estado"] == "cancelado"
