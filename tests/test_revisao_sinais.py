"""Regressoes da semana sem sinais (out/2026): feed desalinhado, datas de
vencimento corrompidas vetando a carteira, setup exigido no candle do dia e
linhas corrompidas do provedor derrubando ativos inteiros. Sem rede."""
from datetime import date
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

import b3_swing_analyzer as b3
import relatorio_diario as rd
from carteira import avaliar_carteira
from setups import candidato_intacto, classificar_setup


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("Rede proibida")
    monkeypatch.setattr("socket.socket.connect", proibido)
    monkeypatch.setattr("socket.create_connection", proibido)


def historico_rompimento():
    close = np.linspace(80, 100, 81)
    df = pd.DataFrame(dict(open=close, high=close + .2, low=close - .2,
                           close=close, volume=np.full(81, 1000.)),
                      index=pd.bdate_range("2026-01-01", periods=81))
    df.iloc[-3] = [99.5, 100.2, 99.3, 99.5, 1000]
    df.iloc[-1] = [100.1, 100.6, 99.9, 100.5, 1000]
    return df


def espelhar(df):
    r = df.copy(deep=True)
    r["open"], r["close"] = 200 - df.open, 200 - df.close
    r["high"], r["low"] = 200 - df.low, 200 - df.high
    return r


def acrescentar(df, highs, lows, closes):
    extra = pd.DataFrame(
        dict(open=closes, high=highs, low=lows, close=closes,
             volume=[1000.] * len(highs)),
        index=pd.bdate_range(df.index[-1] + pd.Timedelta(days=1), periods=len(highs)))
    return pd.concat([df, extra])


# --- 1. forca relativa: feed do IBOV com um pregao a mais que as acoes ------

def test_forca_relativa_com_feed_desalinhado_do_mundo_real():
    datas_ibov = pd.bdate_range(end="2026-09-08", periods=15)
    ativo = pd.DataFrame({"close": np.linspace(100, 110, 16)},
                         index=datas_ibov.union([pd.Timestamp("2026-09-09")]))
    ibov = pd.Series(np.linspace(100, 102, 15), index=datas_ibov)
    r = b3.comparar_forca_relativa(ativo, ibov, agora="2026-09-10")
    assert r["disponivel"]
    assert r["alinhada"]["compra"]
    assert r["observacoes"] == 11 and r["data_final"] == "2026-09-08"


# --- 2. setup: varredura dos ultimos candles, com integridade --------------

@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_setup_do_candle_atual_continua_sendo_encontrado(direcao):
    df = espelhar(historico_rompimento()) if direcao == "venda" else historico_rompimento()
    p = rd._classificar_setup_recente(df, direcao)
    assert p["estado"] == "candidato"
    assert p["data_sinal"] == df.index[-1].date().isoformat()


def test_setup_de_dias_atras_intacto_volta_a_aparecer():
    df = acrescentar(historico_rompimento(),
                     highs=[100.55, 100.60], lows=[100.10, 100.15],
                     closes=[100.40, 100.45])
    atual = classificar_setup(df, "compra")
    assert atual["estado"] == "aguardar"  # candle de hoje, sozinho, nao tem padrao
    p = rd._classificar_setup_recente(df, "compra")
    assert p["estado"] == "candidato"
    assert p["data_sinal"] == df.index[-3].date().isoformat()
    assert p["gatilho"] == pytest.approx(100.61)


def test_setup_antigo_com_gatilho_ja_tocado_nao_e_perseguido():
    df = acrescentar(historico_rompimento(),
                     highs=[100.65, 100.60], lows=[100.10, 100.15],
                     closes=[100.40, 100.45])
    p = rd._classificar_setup_recente(df, "compra")
    assert p["estado"] == "aguardar"
    assert "intacto" in p["motivo"] and "gatilho" in p["motivo"]


def test_setup_antigo_com_stop_tocado_e_invalidado():
    df = acrescentar(historico_rompimento(),
                     highs=[100.55, 100.60], lows=[99.50, 100.15],
                     closes=[100.40, 100.45])
    p = rd._classificar_setup_recente(df, "compra")
    assert p["estado"] == "aguardar"
    assert "intacto" in p["motivo"]


def test_varredura_respeita_a_janela():
    df = acrescentar(historico_rompimento(),
                     highs=[100.55, 100.60, 100.55, 100.58, 100.55, 100.56],
                     lows=[100.10, 100.15, 100.10, 100.12, 100.10, 100.11],
                     closes=[100.40, 100.45, 100.40, 100.42, 100.40, 100.41])
    assert rd._classificar_setup_recente(df, "compra", janela=2)["estado"] == "aguardar"


@pytest.mark.parametrize("tocar,esperado", [
    ("nada", True), ("stop", False), ("alvo", False), ("gatilho", False),
    ("nan", False),
])
def test_candidato_intacto_verifica_sessoes_posteriores(tocar, esperado):
    plano = {"estado": "candidato", "direcao": "compra",
             "gatilho": 100.61, "stop": 99.9, "alvo": 102.03}
    linha = dict(high=100.55, low=100.10)
    if tocar == "stop":
        linha["low"] = 99.5
    elif tocar == "alvo":
        linha["high"] = 102.5
    elif tocar == "gatilho":
        linha["high"] = 100.7
    elif tocar == "nan":
        linha["high"] = np.nan
    posteriores = pd.DataFrame([linha]) if tocar != "nada" else pd.DataFrame()
    assert candidato_intacto(plano, posteriores) is esperado
    assert candidato_intacto(dict(plano, estado="aguardar"), pd.DataFrame()) is False


# --- 3. historico: linha corrompida nao derruba o ativo inteiro -------------

def _historico_valido(n=30):
    close = np.linspace(10, 11, n)
    return pd.DataFrame(dict(open=close, high=close + .1, low=close - .1,
                              close=close, volume=np.full(n, 1000.)),
                         index=pd.bdate_range("2026-01-01", periods=n))


def test_linha_corrompida_do_provedor_e_descartada():
    df = _historico_valido()
    df.iloc[10, df.columns.get_loc("close")] = 0.0
    r = b3._preparar_historico(df, agora="2026-03-01")
    assert len(r) == 29
    assert (r[["open", "high", "low", "close"]] > 0).all().all()
    assert len(b3._preparar_historico(_historico_valido(), agora="2026-03-01")) == 30


def test_historico_todo_corrompido_ainda_falha_de_forma_explicita():
    df = _historico_valido()
    df.loc[:, ["open", "high", "low", "close"]] = 0.0
    with pytest.raises(ValueError):
        b3._preparar_historico(df, agora="2026-03-01")


# --- 4. carteira: vencimento corrompido (caso real CMIG4) nao veta tudo ------

def test_vencimento_corrompido_como_o_caso_real_nao_veta_a_carteira():
    trava = {"ticker": "CMIG4", "direcao": "venda", "tipo_operacao": "trava",
             "preco_entrada": 0.22, "quantidade": 100,
             "vencimento": "2026-10-1612:21", "data_entrada": "2026-08-24"}
    r = avaliar_carteira({"CMIG4": trava}, 10000, data_referencia="2026-09-09")
    assert r["status"] == "completo"
    assert r["debito_travas"] == pytest.approx(22.0)
    assert r["permite_nova_operacao"]
    assert any("vencimento" in a.lower() for a in r["alertas"])
    assert any("corrija o registro" in a for a in r["alertas"])


# --- 5. candidato intacto sobrevive a queda do score para 6-7 ---------------

def _ambiente_preservacao(monkeypatch, tmp_path):
    """Relatorio com score 7 (caiu de 9) e candidato pendente intacto."""
    import relatorio_diario as rd

    class DataFixa(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 2)

    monkeypatch.setattr(rd, "date", DataFixa)
    monkeypatch.setattr(rd.config, "EXIGIR_SETUP", True)
    monkeypatch.setattr(rd.config, "NIVEL_DETALHE", 6, raising=False)

    plano = dict(setup="rompimento", estado="candidato", direcao="venda",
                 data_sinal="2026-09-30", gatilho=57.81, stop=59.88,
                 alvo=53.67, risco_retorno=2.0, alvo_teorico=True,
                 risco_retorno_min=2.0, distancia_max_atr=0.5)
    proposta = {"ticker": "JBSS32", "direcao": "venda", "estado_entrada": "candidato",
                "preco_entrada": 57.81, "stop": 59.88, "alvo": 53.67,
                "data_proposta": "2026-10-01", "plano_setup": dict(plano)}
    dados = {"JBSS32": proposta}
    monkeypatch.setattr(rd, "carregar_propostas", lambda: dict(dados))
    gravadas = {}
    monkeypatch.setattr(rd, "salvar_propostas", Mock(
        side_effect=lambda p: gravadas.update(dict(p))))
    monkeypatch.setattr(rd, "carregar_posicoes", Mock(return_value={}))
    monkeypatch.setattr(rd, "checar_risco_noticias", Mock(
        return_value={"bloquear_entrada": False, "noticias": []}))
    monkeypatch.setattr(rd, "checar_resultado_proximo", Mock(
        return_value={"tem_resultado_proximo": False}))
    monkeypatch.setattr(rd, "sugerir_parametros_opcao_com_preco", Mock(
        return_value={"tipo_opcao": "PUT", "strike_sugerido_aprox": 57,
                      "vencimento_sugerido": "2026-10-20", "premio": 0.4}))
    monkeypatch.setattr(rd, "calcular_tamanho_posicao", Mock(
        return_value={"quantidade_acoes": 100, "valor_posicao": 5900,
                      "valor_em_risco": 100, "pct_capital_em_risco": 1}))
    # Candle do sinal (09-30) + posteriores: venda com gatilho 57.81 e stop
    # 59.88 exige posteriores com high < stop e low > gatilho (nao tocaram).
    df = pd.DataFrame(
        dict(open=[60.0, 59.2, 59.1], high=[60.5, 59.5, 59.6],
             low=[59.9, 58.0, 58.2], close=[60.2, 59.0, 59.3],
             volume=[1000., 1000., 1000.],
             atr=[0.5, 0.5, 0.5], suporte=[58.0, 58.0, 58.0],
             resistencia=[60.5, 60.5, 60.5]),
        index=pd.to_datetime(["2026-09-30", "2026-10-01", "2026-10-02"]))
    resultado = dict(ticker="JBSS32", direcao="venda", score=7,
                     preco=59.3, motivos=[], df=df,
                     score_bruto=7)
    monkeypatch.setattr(rd, "_classificar_setup_recente",
                        Mock(return_value=dict(setup=None, estado="aguardar",
                                               motivo="Sem novo padrao")))
    return rd, resultado, proposta, gravadas, plano


def test_score_7_com_setup_intacto_preserva_candidato(monkeypatch, tmp_path):
    rd, resultado, proposta, gravadas, plano = _ambiente_preservacao(monkeypatch, tmp_path)
    rd.montar_bloco_resumo(resultado, {}, 6)
    assert resultado["estado_entrada"] == "candidato"
    assert resultado["veredito"]["veredito"] == "CANDIDATO"
    assert resultado["plano_setup"] == plano
    assert "intacto" in resultado["veredito"]["descricao"]
    # Sem re-salvar (data_proposta original preservada) e sem remover:
    assert gravadas == {}
    assert proposta["data_proposta"] == "2026-10-01"


def test_score_5_remove_candidato(monkeypatch, tmp_path):
    rd, resultado, _, gravadas, _ = _ambiente_preservacao(monkeypatch, tmp_path)
    resultado["score"] = 5
    resultado["score_bruto"] = 5
    rd.montar_bloco_resumo(resultado, {}, 6)
    assert resultado["estado_entrada"] == "aguardar"
    assert gravadas == {}  # propostas salvas sem o candidato


def test_direcao_trocada_remove_candidato(monkeypatch, tmp_path):
    rd, resultado, _, gravadas, _ = _ambiente_preservacao(monkeypatch, tmp_path)
    resultado["direcao"] = "compra"
    rd.montar_bloco_resumo(resultado, {}, 6)
    assert resultado["estado_entrada"] == "aguardar"
    assert gravadas == {}


def test_posicao_no_mesmo_ticker_remove_candidato_preservado(monkeypatch, tmp_path):
    rd, resultado, _, gravadas, _ = _ambiente_preservacao(monkeypatch, tmp_path)
    monkeypatch.setattr(rd, "carregar_posicoes", Mock(return_value={
        "JBSS32": {"ticker": "JBSS32", "direcao": "venda"}}))
    rd.montar_bloco_resumo(resultado, {}, 6)
    assert resultado["veredito"]["veredito"] == "EVITAR"
    assert "Ja existe posicao" in resultado["motivo_bloqueio"]
    assert gravadas == {}
