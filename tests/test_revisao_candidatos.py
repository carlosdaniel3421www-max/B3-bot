"""Regressoes de candidatos: OHLCV sintetico, datas fixas e I/O em memoria."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

import posicoes
import relatorio_diario as rd
import screener
import telegram_bot as bot
from setups import classificar_setup, reutilizar_candidato
from test_setups import espelhar, historico


@pytest.fixture(autouse=True)
def isolado(monkeypatch):
    def proibido(*args, **kwargs):
        pytest.fail("Rede/JSON real proibidos")

    for alvo in ("requests.sessions.Session.request", "socket.socket.connect",
                 "socket.create_connection", "socket.getaddrinfo"):
        monkeypatch.setattr(alvo, proibido)
    for nome in ("_carregar_json", "_salvar_json", "_sincronizar_github"):
        monkeypatch.setattr(posicoes, nome, proibido)


@pytest.fixture(params=["compra", "venda"])
def ambiente(request, monkeypatch):
    class DataFixa(date):
        atual = date(2030, 1, 8)

        @classmethod
        def today(cls):
            return cls.atual

    for modulo in (rd, bot):
        monkeypatch.setattr(modulo, "date", DataFixa)
    monkeypatch.setattr(rd.config, "EXIGIR_SETUP", True)
    df = historico()
    df.index = pd.bdate_range(end="2030-01-04", periods=len(df))
    df = espelhar(df, request.param)
    plano = classificar_setup(df, request.param)
    assert plano["estado"] == "candidato"
    posteriores = pd.DataFrame([[100.4, 100.55, 100.1, 100.4, 1000.]],
                               columns=df.columns, index=pd.to_datetime(["2030-01-07"]))
    df = pd.concat([df, espelhar(posteriores, request.param)])
    assert classificar_setup(df, request.param)["estado"] == "aguardar"
    proposta = dict(ticker="PETR4", direcao=request.param, estado_entrada="candidato",
                    preco_entrada=plano["gatilho"], stop=plano["stop"], alvo=plano["alvo"],
                    data_proposta="2030-01-04", plano_setup=deepcopy(plano))
    dados = {"PETR4": proposta, "OUTRO": {"intacto": True}}
    for modulo in (rd, bot):
        monkeypatch.setattr(modulo, "carregar_propostas", lambda: deepcopy(dados))

    def salvar(propostas):
        dados.clear()
        dados.update(deepcopy(propostas))

    monkeypatch.setattr(rd, "salvar_propostas", Mock(side_effect=salvar))
    monkeypatch.setattr(rd, "salvar_proposta_entrada", Mock())
    monkeypatch.setattr(rd, "carregar_posicoes", Mock(return_value={}))
    monkeypatch.setattr(rd, "checar_risco_noticias", Mock(return_value={
        "bloquear_entrada": False, "noticias": [],
    }))
    monkeypatch.setattr(rd, "checar_resultado_proximo", Mock(return_value={
        "tem_resultado_proximo": False,
    }))
    monkeypatch.setattr(rd, "sugerir_parametros_opcao_com_preco", Mock(return_value={
        "tipo_opcao": "CALL", "strike_sugerido_aprox": 100,
        "vencimento_sugerido": "2030-02-15", "premio": None,
    }))
    monkeypatch.setattr(rd, "calcular_tamanho_posicao", Mock(return_value={"quantidade_acoes": 0}))
    resultado = dict(ticker="PETR4", direcao=request.param, score=9,
                     preco=float(df.close.iloc[-1]), motivos=[], df=df)
    return SimpleNamespace(dados=dados, resultado=resultado, plano=plano, data=DataFixa)


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("high", [100.6, 100.601, 100.609, 100.61])
def test_gatilho_proximo_centavo_estrito_antes_de_calcular_2r(direcao, high):
    df = historico()
    df.iloc[-1, df.columns.get_loc("high")] = high
    df = espelhar(df, direcao)
    plano = classificar_setup(df, direcao)
    sinal = 1 if direcao == "compra" else -1
    extremo = Decimal(str(df.iloc[-1]["high" if sinal == 1 else "low"]))
    gatilho, stop, alvo = (Decimal(str(plano[c])) for c in ("gatilho", "stop", "alvo"))
    assert gatilho % Decimal("0.01") == 0
    assert 0 < sinal * (gatilho - extremo) <= Decimal("0.01")
    assert sinal * (gatilho - sinal * Decimal("0.01") - extremo) <= 0
    assert alvo == gatilho + 2 * (gatilho - stop)
    assert plano["risco_retorno"] == 2


@pytest.mark.parametrize("idade", [1, 2, 3, 4])
def test_sem_novo_padrao_preserva_plano_datas_e_niveis(ambiente, idade):
    a = ambiente
    a.data.atual = date(2030, 1, 4) + timedelta(days=idade)
    a.resultado["df"] = a.resultado["df"].loc[a.resultado["df"].index.date < a.data.today()]
    # Forca ausencia de padrao novo inclusive quando o ultimo candle e o sinal.
    original = deepcopy(a.dados)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(rd, "classificar_setup", Mock(return_value={"estado": "aguardar", "motivo": "Sem novo padrao"}))
        texto = rd.montar_bloco_resumo(a.resultado, {}, 10)
    assert a.resultado["estado_entrada"] == "candidato"
    assert a.resultado["plano_setup"] == a.plano
    assert a.dados == original
    rd.salvar_propostas.assert_not_called()
    rd.salvar_proposta_entrada.assert_not_called()
    assert "/gatilho PETR4" in texto and "/registrar" not in texto
    assert "nao comprova execucao" in texto


def test_classificador_real_sem_novo_padrao_mantem(ambiente):
    rd.montar_bloco_resumo(ambiente.resultado, {}, 6)
    assert ambiente.resultado["plano_setup"] == ambiente.plano
    assert ambiente.resultado["estado_entrada"] == "candidato"


@pytest.mark.parametrize("idade", [-1, 0, 5])
def test_plano_anterior_futuro_mesmo_dia_ou_expirado_nao_reutiliza(ambiente, idade):
    a = ambiente
    a.data.atual = date(2030, 1, 4) + timedelta(days=idade)
    rd.montar_bloco_resumo(a.resultado, {}, 6)
    assert not a.resultado["entrada_permitida"]
    assert a.dados == {"OUTRO": {"intacto": True}}
    rd.salvar_proposta_entrada.assert_not_called()


@pytest.mark.parametrize("idade,permitida", [(-1, False), (0, True), (1, True), (4, True), (5, False)])
def test_publicacao_com_classificador_real_limites_data(ambiente, idade, permitida):
    a = ambiente
    a.resultado["df"] = a.resultado["df"].iloc[:-1]
    a.data.atual = date(2030, 1, 4) + timedelta(days=idade)
    rd.montar_bloco_resumo(a.resultado, {}, 6)
    assert a.resultado["entrada_permitida"] is permitida
    assert rd.salvar_proposta_entrada.called is permitida


def test_toque_em_candle_intermediario_nao_some_com_recuperacao(ambiente):
    a = ambiente
    df = a.resultado["df"]
    intermediario = df.iloc[-1:].copy()
    intermediario.index = pd.to_datetime(["2030-01-05"])
    coluna = "low" if a.plano["direcao"] == "compra" else "high"
    intermediario[coluna] = a.plano["stop"]
    a.resultado["df"] = pd.concat([df.iloc[:-1], intermediario, df.iloc[-1:]])
    rd.montar_bloco_resumo(a.resultado, {}, 6)
    assert not a.resultado["entrada_permitida"]
    assert a.dados == {"OUTRO": {"intacto": True}}


@pytest.mark.parametrize("campo", ["stop", "alvo"])
@pytest.mark.parametrize("extra", [0, .1])
def test_pavio_posterior_toca_ou_ultrapassa_cancela_mesmo_close_seguro(ambiente, campo, extra):
    a = ambiente
    df = a.resultado["df"]
    nivel = a.plano[campo]
    inferior = nivel < a.plano["gatilho"]
    df.loc[df.index[-1], "low" if inferior else "high"] = nivel + (-extra if inferior else extra)
    assert reutilizar_candidato(a.plano, df, a.plano["direcao"], a.data.today()) is None
    rd.montar_bloco_resumo(a.resultado, {}, 6)
    assert not a.resultado["entrada_permitida"]
    assert a.dados == {"OUTRO": {"intacto": True}}


@pytest.mark.parametrize("falha", ["nan", "inf", "geometria", "coluna", "bool", "texto",
                                  "sem_sinal", "lacuna", "duplicado", "ordem", "futuro"])
def test_reuso_exige_cobertura_e_ohlcv_posterior_valido(ambiente, falha):
    a = ambiente
    df = a.resultado["df"].copy()
    if falha in ("nan", "inf", "geometria"):
        df.loc[df.index[-1], "low"] = {"nan": np.nan, "inf": np.inf, "geometria": 200}[falha]
    elif falha == "coluna":
        df = df.drop(columns="open")
    elif falha == "bool":
        df["volume"] = True
    elif falha == "texto":
        df["close"] = df.close.astype(str)
    elif falha == "sem_sinal":
        df = df.iloc[-1:]
    elif falha == "lacuna":
        df = df.iloc[:-1]
    elif falha == "duplicado":
        df = pd.concat([df, df.iloc[-1:]])
    elif falha == "ordem":
        df = df.iloc[::-1]
    else:
        df = df.rename(index={df.index[-1]: pd.Timestamp("2030-01-09")})
    assert reutilizar_candidato(a.plano, df, a.plano["direcao"], a.data.today()) is None


@pytest.mark.parametrize("campo,valor", [("estado", "aguardar"), ("direcao", "neutro"),
                                       ("risco_retorno", 5), ("stop", None)])
def test_plano_incompativel_nao_reutiliza(ambiente, campo, valor):
    plano = dict(ambiente.plano, **{campo: valor})
    assert reutilizar_candidato(plano, ambiente.resultado["df"], ambiente.plano["direcao"], ambiente.data.today()) is None


@pytest.mark.parametrize("data_sinal", ["2030-01-03", "2030-01-09", "invalida", None])
def test_publicacao_rejeita_novo_expirado_futuro_ou_data_invalida(ambiente, monkeypatch, data_sinal):
    plano = dict(ambiente.plano, data_sinal=data_sinal)
    monkeypatch.setattr(rd, "classificar_setup", Mock(return_value=plano))
    texto = rd.montar_bloco_resumo(ambiente.resultado, {}, 6)
    assert not ambiente.resultado["entrada_permitida"]
    assert "/gatilho" not in texto and "/registrar" not in texto
    assert ambiente.dados == {"OUTRO": {"intacto": True}}
    rd.salvar_proposta_entrada.assert_not_called()


@pytest.mark.parametrize("data_sinal,rotulo", [("2030-01-03", "EXPIRADO"),
                                             ("2030-01-09", "INVALIDO"), (None, "INVALIDO")])
def test_propostas_vencidas_sem_convite_e_sem_mutacao(ambiente, data_sinal, rotulo):
    ambiente.dados.pop("OUTRO")
    ambiente.dados["PETR4"]["plano_setup"]["data_sinal"] = data_sinal
    original = deepcopy(ambiente.dados)
    texto = bot.processar_comando("token", 1, "/propostas")
    assert rotulo in texto
    assert "/gatilho" not in texto and "/registrar" not in texto
    assert ambiente.dados == original


@pytest.mark.parametrize("filtro", ["noticia", "resultados", "ibov", "carteira"])
def test_reuso_nao_contorna_risco_corrente(ambiente, monkeypatch, filtro):
    a = ambiente
    if filtro == "noticia":
        rd.checar_risco_noticias.return_value = {"bloquear_entrada": True, "alertas": [{"motivo": "Risco atual"}]}
    elif filtro == "resultados":
        rd.checar_resultado_proximo.return_value = {
            "tem_resultado_proximo": True, "dias_ate_resultado": 1, "data_resultado": "2030-01-09",
        }
    elif filtro == "carteira":
        rd.carregar_posicoes.return_value = {"VALE3": {"quantidade": None}}
    else:
        monkeypatch.setattr(screener, "baixar_dados", Mock(return_value=a.resultado["df"]))
        monkeypatch.setattr(screener, "calcular_indicadores", lambda df: df)
        monkeypatch.setattr(screener, "avaliar_ativo", Mock(return_value={
            "score": 9, "direcao": a.plano["direcao"], "preco_atual": a.resultado["preco"], "motivos": [],
        }))
        a.resultado = screener._processar_ativo("PETR4", "1y", False, False, False,
                                              {"tetos": {"compra": 7, "venda": 7}})
        assert a.resultado["score"] == 7
    texto = rd.montar_bloco_resumo(a.resultado, {}, 10)
    assert not a.resultado["entrada_permitida"]
    assert a.dados == {"OUTRO": {"intacto": True}}
    assert "/gatilho" not in texto and "/registrar" not in texto
    rd.salvar_proposta_entrada.assert_not_called()
