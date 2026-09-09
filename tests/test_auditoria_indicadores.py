"""Auditoria matematica e integracao sintetica, sem rede nem relatorio."""
import builtins
import os
import pickle
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock, mock_open

import numpy as np
import pandas as pd
import pytest

import b3_swing_analyzer as b3
import gestao_risco as risco
import screener


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("Rede proibida nesta auditoria")
    monkeypatch.setattr(socket.socket, "connect", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)
    monkeypatch.setattr(socket, "getaddrinfo", proibido)
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=proibido))


def dados(n=240, plano=False):
    x = np.arange(n)
    close = np.full(n, 100.) if plano else 100 + x * .04 + 3 * np.sin(x * .4)
    return pd.DataFrame({"open": close, "high": close + (0 if plano else 2),
                         "low": close - (0 if plano else 1), "close": close,
                         "volume": np.full(n, 10000.)},
                        index=pd.bdate_range("2024-01-01", periods=n))


def referencia_wilder(df, n):
    # Oraculo escalar independente: sem ewm, rolling ou helpers de producao.
    tr, pos, neg = [], [], []
    for i in range(1, len(df)):
        h, l, c = df.iloc[i][["high", "low", "close"]]
        hp, lp, cp = df.iloc[i - 1][["high", "low", "close"]]
        up, down = h - hp, lp - l
        pos.append(up if up > down and up > 0 else 0.)
        neg.append(down if down > up and down > 0 else 0.)
        tr.append(max(h - l, abs(h - cp), abs(l - cp)))
    st, sp, sn = sum(tr[:n]), sum(pos[:n]), sum(neg[:n])
    dxs = []
    adx = None
    for i in range(n - 1, len(tr)):
        if i >= n:
            st, sp, sn = (st - st / n + tr[i], sp - sp / n + pos[i], sn - sn / n + neg[i])
        pdi, ndi = (100 * sp / st, 100 * sn / st) if st else (0., 0.)
        dx = 100 * abs(pdi - ndi) / (pdi + ndi) if pdi + ndi else 0.
        dxs.append(dx)
        if len(dxs) == n:
            adx = sum(dxs) / n
        elif len(dxs) > n:
            adx = (adx * (n - 1) + dx) / n
    return adx, pdi, ndi


@pytest.mark.parametrize("n,tamanho", [(3, 6), (3, 35), (14, 28), (14, 240)])
def test_adx_di_wilder_semente_e_recorrencia(n, tamanho):
    df = dados(tamanho)
    esperado = referencia_wilder(df, n)
    assert b3._calcular_adx_di(df, n) == pytest.approx(esperado, abs=1e-10)
    assert b3.calcular_adx(df, n) == pytest.approx(esperado[0])


def test_adx_nao_e_media_rolling():
    df, n = dados(100), 14
    up, down = df.high.diff(), -df.low.diff()
    p = up.where((up > down) & (up > 0), 0.).rolling(n).mean()
    m = down.where((down > up) & (down > 0), 0.).rolling(n).mean()
    rolling_antigo = (100 * (p - m).abs() / (p + m)).rolling(n).mean().iloc[-1]
    assert abs(b3.calcular_adx(df) - rolling_antigo) > 1


def test_adx_aquecimento_plano_e_empate_dm():
    assert np.isnan(b3.calcular_adx(dados(27)))
    assert b3._calcular_adx_di(dados(40, plano=True)) == (0., 0., 0.)
    df = dados(40, plano=True)
    df.high += np.arange(40)
    df.low -= np.arange(40)
    assert b3._calcular_adx_di(df) == (0., 0., 0.)


@pytest.mark.parametrize("n", [0, -1, 1.5])
def test_adx_periodo_invalido(n):
    assert np.isnan(b3.calcular_adx(dados(), n))


@pytest.mark.parametrize("valor", [np.nan, np.inf, -np.inf])
@pytest.mark.parametrize("coluna", ["open", "high", "low", "close", "volume"])
def test_ohlcv_nao_finito_rejeitado(valor, coluna):
    df = dados()
    df.loc[df.index[80], coluna] = valor
    for calcular in (b3.calcular_indicadores, b3.calcular_indicadores_curto_prazo):
        with pytest.raises(ValueError):
            calcular(df.copy())
    if coluna in ("high", "low", "close"):
        assert np.isnan(b3.calcular_adx(df))


@pytest.mark.parametrize("curto", [False, True])
@pytest.mark.parametrize("valor", [np.nan, np.inf, -np.inf])
def test_avaliador_nao_pontua_indicador_invalido(curto, valor):
    df = b3.calcular_indicadores(dados())
    if curto:
        df = b3.calcular_indicadores_curto_prazo(df)
    df.loc[df.index[-1], "rsi_curto" if curto else "rsi"] = valor
    with pytest.raises(ValueError):
        (b3.avaliar_ativo_curto_prazo if curto else b3.avaliar_ativo)(df)


def test_rsi_wilder_semente_nao_inventa_aquecimento():
    df = pd.DataFrame({"close": [10., 11., 13., 12., 14.]})
    rsi = b3.calcular_rsi(df, 3).rsi
    assert rsi.iloc[:3].isna().all()
    assert rsi.iloc[3] == pytest.approx(75.)
    assert rsi.iloc[4] == pytest.approx(100 - 100 / (1 + (4 / 3) / (2 / 9)))


def test_plano_nao_gera_venda_macd_zero_e_atr_zero():
    df = b3.calcular_indicadores(dados(plano=True))
    assert df.rsi.iloc[-1] == 50
    assert df.stoch_k.iloc[:13].isna().all()
    assert df.stoch_k.iloc[-1] == 50
    assert df.atr.iloc[-1] == 0
    assert b3.avaliar_ativo(df)["score"] == 0
    df = b3.calcular_indicadores_curto_prazo(df)
    assert df.rsi_curto.iloc[-1] == 50
    assert df.stoch_k_curto.iloc[-1] == 50
    assert b3.avaliar_ativo_curto_prazo(df)["score"] == 0


def test_vwap_sem_volume_indisponivel_e_atr_sma_preservado():
    df = dados(60)
    df.volume = 0.
    resultado = b3.calcular_indicadores(df.copy())
    assert resultado.vwap.isna().all()
    tr = [max(df.high.iloc[i] - df.low.iloc[i],
              abs(df.high.iloc[i] - df.close.iloc[i - 1]),
              abs(df.low.iloc[i] - df.close.iloc[i - 1])) for i in range(46, 60)]
    assert resultado.atr.iloc[-1] == pytest.approx(sum(tr) / 14)


def test_indicadores_e_avaliacao_causais():
    df = dados(260)
    prefixo = b3.calcular_indicadores_curto_prazo(b3.calcular_indicadores(df.iloc[:220].copy()))
    df.iloc[220:, :4] *= 3
    completo = b3.calcular_indicadores_curto_prazo(b3.calcular_indicadores(df.copy()))
    pd.testing.assert_frame_equal(prefixo, completo.iloc[:220])
    assert b3.avaliar_ativo(prefixo) == b3.avaliar_ativo(completo.iloc[:220])
    assert b3.avaliar_ativo_curto_prazo(prefixo) == b3.avaliar_ativo_curto_prazo(completo.iloc[:220])


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_stop_alvo_lados_teto_e_risco_arredondado(direcao):
    df = pd.DataFrame({"close": [100.004], "atr": [1.], "suporte": [10.], "resistencia": [190.]})
    r = b3.sugerir_stop_alvo(df, direcao)
    assert r["risco_por_acao"] == 3.
    assert r["risco_por_acao"] == pytest.approx(abs(r["preco_entrada"] - r["stop"]))
    assert r["alvo"] == (106. if direcao == "compra" else 94.)


@pytest.mark.parametrize("campo,valor", [("atr", 0.), ("atr", np.nan), ("close", np.inf),
                                         ("suporte", np.nan), ("atr", .00001)])
def test_stop_invalido_nao_cria_plano(campo, valor):
    df = pd.DataFrame({"close": [100.], "atr": [1.], "suporte": [100.], "resistencia": [100.]})
    df.loc[0, campo] = valor
    with pytest.raises(ValueError):
        b3.sugerir_stop_alvo(df, "compra")


def test_stop_nao_converte_neutro_em_venda():
    with pytest.raises(ValueError):
        b3.sugerir_stop_alvo(dados(), "neutro")


@pytest.mark.parametrize("score", [np.nan, np.inf, -np.inf, -1, 11])
def test_veredito_score_invalido(score):
    assert b3.determinar_veredito(score, "compra")["veredito"] == "SEM SINAL"


@pytest.mark.parametrize("campo", range(7))
@pytest.mark.parametrize("valor", [np.nan, np.inf, -np.inf, None])
def test_regime_requer_todas_metricas_finitas(campo, valor):
    args = [30., 28., 18., .8, 2., 2., 5.]
    args[campo] = valor
    r = b3.classificar_regime_ibov(*args)
    assert r["regime"] == "indisponivel"
    assert r["tetos"] == {"compra": 10, "venda": 10}  # politica existente, nao relaxada
    assert r["texto_aviso"]


def test_regime_conflito_nao_e_lateral_e_preserva_tetos():
    r = b3.classificar_regime_ibov(30, 28, 18, .8, -2, 2, 5)
    assert r["regime"] == "conflito"
    assert r["tetos"] == {"compra": 7, "venda": 7}
    assert b3.classificar_regime_ibov(22, 28, 18, .8, 2, 2, 5)["regime"] == "lateral"
    assert b3.classificar_regime_ibov(30, 28, 18, .5, 2, 2, 5)["regime"] == "lateral"


def test_ibov_di_unico_e_sma200_ausente_nao_zero(monkeypatch):
    df = dados(80)
    monkeypatch.setattr(b3, "baixar_dados_ibov", lambda *a: df)
    original = b3._calcular_adx_di
    calculo = Mock(side_effect=original)
    monkeypatch.setattr(b3, "_calcular_adx_di", calculo)
    r = b3.avaliar_regime_ibov()
    calculo.assert_called_once_with(df)
    assert (r["adx"], r["di_pos"], r["di_neg"]) == pytest.approx(referencia_wilder(df, 14))
    assert r["dist_sma200_pct"] is None


@pytest.mark.parametrize("tipo", ["curto", "vazio", "nan", "zero", "coluna"])
def test_ibov_insuficiente_ou_corrompido(monkeypatch, tipo):
    df = dados(20 if tipo == "curto" else 80)
    if tipo == "vazio":
        df = df.iloc[:0]
    elif tipo in ("nan", "zero"):
        df.loc[df.index[-6], "close"] = np.nan if tipo == "nan" else 0.
    elif tipo == "coluna":
        df = df.drop(columns="high")
    monkeypatch.setattr(b3, "baixar_dados_ibov", lambda *a: df)
    assert b3.avaliar_regime_ibov()["regime"] == "indisponivel"


def test_eficiencia_ausencia_nao_e_lateralidade():
    assert np.isnan(b3.calcular_eficiencia(pd.Series([1., 2.]), 10))
    assert np.isnan(b3.calcular_eficiencia(pd.Series([1., np.nan, 2.]), 2))
    assert b3.calcular_eficiencia(pd.Series([1., 1., 1.]), 2) == 0
    assert b3.calcular_eficiencia(pd.Series([1., 2., 3.]), 2) == 1


def test_datas_brt_ordem_diario_fechado_e_parcial():
    df = dados(3)
    df.index = pd.date_range("2026-09-07", periods=3, tz="America/Sao_Paulo").tz_convert("UTC")
    df = df.iloc[::-1]
    fechado = b3._preparar_historico(df, agora="2026-09-08 16:00Z")
    parcial = b3._preparar_historico(df, incluir_atual=True, agora="2026-09-08 16:00Z")
    assert fechado.index.tolist() == [pd.Timestamp("2026-09-07")]
    assert parcial.index.tolist() == [pd.Timestamp("2026-09-07"), pd.Timestamp("2026-09-08")]
    assert fechado.index.tz is None
    assert len(b3._preparar_historico(df, agora="2026-09-08 23:00-03:00")) == 1


def test_horario_so_candles_completos():
    df = dados(3)
    df.index = pd.date_range("2026-09-08 10:00", periods=3, freq="h", tz="America/Sao_Paulo")
    r = b3._preparar_historico(df, "60m", agora="2026-09-08 14:30Z")
    assert r.index.tolist() == [pd.Timestamp("2026-09-08 10:00")]


@pytest.mark.parametrize("tipo", ["numero", "duplicado"])
def test_indice_download_invalido(tipo):
    df = dados(3)
    df.index = pd.RangeIndex(3) if tipo == "numero" else pd.DatetimeIndex(["2024-01-01"] * 3)
    with pytest.raises(ValueError):
        b3._preparar_historico(df, agora="2026-09-08")


def test_cache_fechado_remove_parcial_antigo_sem_download(monkeypatch):
    hoje = pd.Timestamp.now(tz="America/Sao_Paulo").normalize()
    df = dados(2)
    df.index = pd.DatetimeIndex([hoje - pd.Timedelta(days=1), hoje])
    monkeypatch.setattr(os.path, "exists", lambda *a: True)
    monkeypatch.setattr(os.path, "getmtime", lambda *a: hoje.timestamp())
    monkeypatch.setattr(builtins, "open", mock_open(read_data=pickle.dumps(df)))
    r = b3.baixar_dados("petr4")
    assert len(r) == 1


@pytest.mark.parametrize("intervalo,incluir", [("1d", True), ("60m", False)])
def test_parcial_e_intraday_nao_leem_nem_gravam_cache(monkeypatch, intervalo, incluir):
    df = dados(40)
    baixar = Mock(return_value=df)
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=baixar))
    def proibido(*a, **k):
        raise AssertionError("Cache nao deve ser acessado")
    abrir = Mock(side_effect=proibido)
    monkeypatch.setattr(builtins, "open", abrir)
    assert len(b3.baixar_dados("petr4", intervalo=intervalo, incluir_atual=incluir, tentativas=1)) == 40
    abrir.assert_not_called()
    assert baixar.call_args.args == ("PETR4.SA",)


def test_cache_ibov_reutiliza_download_correto_e_periodo(monkeypatch):
    baixar = Mock(return_value=dados())
    monkeypatch.setattr(b3, "baixar_dados", baixar)
    b3.baixar_dados_ibov("2y")
    baixar.assert_called_once_with("^BVSP", periodo="2y")


def test_screener_volume_antes_indicadores_e_modo_parcial(monkeypatch):
    baixar = Mock(return_value=dados())
    monkeypatch.setattr(screener, "baixar_dados", baixar)
    def projetar(df):
        df = df.copy()
        df.iloc[-1, df.columns.get_loc("volume")] *= 3
        return df
    monkeypatch.setattr(screener, "projetar_volume_dia_atual", projetar)
    r = screener._processar_ativo("PETR4", "2y", False, True, False)
    assert r is not None
    baixar.assert_called_once_with("PETR4", periodo="2y", incluir_atual=True)
    ultimo = r["df"].iloc[-1]
    assert ultimo.force_index == pytest.approx(r["df"].close.diff().iloc[-1] * ultimo.volume)
    esperado = b3.calcular_indicadores(projetar(dados()))
    assert ultimo.vwap == pytest.approx(esperado.vwap.iloc[-1])


def test_screener_bonus_horario_nao_rompe_teto_exaustao(monkeypatch):
    df = dados()
    df[["open", "close"]] = np.linspace(50, 100, len(df))[:, None] * np.ones((1, 2))
    df.high, df.low = df.close + 1, df.close - 1
    monkeypatch.setattr(screener, "baixar_dados", lambda *a, **k: df.copy())
    monkeypatch.setattr(screener, "avaliar_timeframe_horario", lambda *a: {"direcao": "compra", "rsi_h": 80})
    base = b3.avaliar_ativo(b3.calcular_indicadores(df.copy()))
    assert base["teto_score"] == 7
    r = screener._processar_ativo("PETR4", "2y", False, False, True)
    assert r["score"] <= 7


def test_screener_vazio_nao_varre_padrao(monkeypatch):
    avaliar = Mock(side_effect=AssertionError("Nao deve avaliar IBOV"))
    monkeypatch.setattr(screener, "avaliar_regime_ibov", avaliar)
    assert screener.rodar_screener([]) == []
    avaliar.assert_not_called()


@pytest.mark.parametrize("stop", [99.99, 100.01])
def test_sizing_respeita_capital_compra_e_venda(stop):
    r = risco.calcular_tamanho_posicao(1000., 1., 100., stop)
    assert r["quantidade_acoes"] == 10
    assert r["valor_posicao"] <= 1000
    assert r["valor_em_risco"] <= 10


def test_sizing_decimal_nao_perde_lote_e_nao_forca_lote():
    r = risco.calcular_tamanho_posicao(1000., 1., 10., 9.9)
    assert r["quantidade_acoes"] == 100
    assert r["valor_em_risco"] == 10
    r = risco.calcular_tamanho_posicao(99., 1., 100., 99.)
    assert r["quantidade_acoes"] == 0
    assert not r["aviso_lote_fracionado"]


@pytest.mark.parametrize("func,args,chave", [
    (risco.calcular_tamanho_posicao, [1000., 1., 10., 9.], "quantidade_acoes"),
    (risco.calcular_contratos_opcao, [1000., 1., 1.], "quantidade_contratos"),
    (risco.calcular_contratos_trava, [1000., 1., 1.], "quantidade_contratos"),
])
@pytest.mark.parametrize("valor", [np.nan, np.inf, -np.inf, -1., None, True])
def test_sizing_invalido_retorna_zero(func, args, chave, valor):
    for i in range(len(args)):
        entrada = args.copy()
        entrada[i] = valor
        r = func(*entrada)
        assert r[chave] == 0
        assert "erro" in r


@pytest.mark.parametrize("func", [risco.calcular_contratos_opcao, risco.calcular_contratos_trava])
def test_opcoes_sizing_decimal_e_percentual(func):
    r = func(1000., 2.9, .29)
    assert r["quantidade_contratos"] == 1
    assert r["perda_maxima"] == 29.
    assert func(1000., 101., .29)["quantidade_contratos"] == 0


def test_kelly_sem_vantagem_nao_volta_ao_risco_padrao():
    assert risco.risco_com_kelly(10000, 1, .5, 1, 1) == 0
    assert risco.risco_com_kelly(10000, 1, .3, 1, 1) == 0
    assert risco.risco_com_kelly(10000, 1, 0, 1, 1) == 1  # sentinel existente sem historico
    assert risco.risco_com_kelly(10000, 1, .6, 2, 1, 0) == 0


@pytest.mark.parametrize("valor", [np.nan, np.inf, -np.inf])
def test_kelly_rejeita_nao_finitos(valor):
    assert risco.fracao_kelly(.6, valor, 1) == 0
    assert risco.fracao_kelly(.6, 2, valor) == 0
    assert risco.risco_com_kelly(10000, 1, .6, valor, 1) == 0


@pytest.mark.parametrize("func", [b3.calcular_medias_moveis, b3.calcular_macd,
                                  b3.calcular_estocastico, b3.calcular_vwap,
                                  b3.calcular_suporte_resistencia, b3.calcular_atr,
                                  b3.calcular_force_index])
def test_indicadores_isolados_nao_mascaram_nan(func):
    df = dados()
    df.loc[df.index[30], "close"] = np.nan
    with pytest.raises(ValueError):
        func(df)


@pytest.mark.parametrize("curto,n", [(False, 50), (True, 20)])
def test_primeira_janela_completa_sem_exigir_barra_extra(curto, n):
    calcular = b3.calcular_indicadores_curto_prazo if curto else b3.calcular_indicadores
    avaliar = b3.avaliar_ativo_curto_prazo if curto else b3.avaliar_ativo
    assert 0 <= avaliar(calcular(dados(n)))["score"] <= 10
    with pytest.raises(ValueError):
        avaliar(calcular(dados(n - 1)))


def test_volume_projetado_brt_e_fracionario_sem_mutar(monkeypatch):
    timestamp = pd.Timestamp
    class Relogio(timestamp):
        @classmethod
        def now(cls, tz=None):
            return timestamp("2026-09-08 13:00", tz="America/Sao_Paulo")
    df = dados(2)
    df.volume = df.volume.astype(int)
    df.index = pd.date_range("2026-09-07", periods=2, tz="America/Sao_Paulo").tz_convert("UTC")
    monkeypatch.setattr(pd, "Timestamp", Relogio)
    r = b3.projetar_volume_dia_atual(df)
    assert r.volume.iloc[-1] == pytest.approx(10000 * 7 / 3)
    assert df.volume.iloc[-1] == 10000


@pytest.mark.parametrize("corrompido", [False, True])
def test_cache_expirado_ou_corrompido_rebaixa_sem_io(monkeypatch, corrompido):
    hoje = pd.Timestamp.now(tz="America/Sao_Paulo").normalize()
    df = dados()
    baixar = Mock(return_value=df)
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=baixar))
    monkeypatch.setattr(os.path, "exists", lambda *a: True)
    monkeypatch.setattr(os.path, "getmtime", lambda *a: (hoje if corrompido else hoje - pd.Timedelta(days=1)).timestamp())
    monkeypatch.setattr(builtins, "open", mock_open(read_data=b"pickle invalido"))
    monkeypatch.setattr(os, "makedirs", Mock())
    salvar = Mock()
    monkeypatch.setattr(pickle, "dump", salvar)
    assert len(b3.baixar_dados("^BVSP", periodo="2y", tentativas=1)) == len(df)
    assert baixar.call_args.args == ("^BVSP",)
    assert baixar.call_args.kwargs["period"] == "2y"
    salvar.assert_called_once()


def test_timeframe_horario_plano_neutro_com_rsi_finito(monkeypatch):
    monkeypatch.setattr(b3, "baixar_dados", lambda *a, **k: dados(40, plano=True))
    r = b3.avaliar_timeframe_horario("PETR4")
    assert r["direcao"] == "neutro"
    assert r["rsi_h"] == 50


def test_grafico_nao_inventa_sma200_nem_mistura_volume_rsi(monkeypatch):
    capturado = {}
    fig = Mock()
    def plot(df, **kwargs):
        capturado.update(kwargs)
        return fig, []
    mpf = SimpleNamespace(make_addplot=lambda data, **kw: {"data": data, **kw},
                          make_marketcolors=lambda **kw: kw, make_mpf_style=lambda **kw: kw,
                          plot=plot)
    monkeypatch.setitem(sys.modules, "mplfinance", mpf)
    monkeypatch.setattr(b3.plt, "close", Mock())
    fallback = Mock(side_effect=AssertionError("Fallback inesperado"))
    monkeypatch.setattr(b3, "_plotar_grafico_linhas", fallback)
    df = b3.calcular_indicadores(dados(60))
    b3.plotar_grafico(df, "PETR4", "nao_gravar.png")
    plots = capturado["addplot"]
    assert capturado["panel_ratios"] == (4, 1, 1, 1)
    series = [p for p in plots if isinstance(p["data"], pd.Series)]
    assert "sma200" not in [p["data"].name for p in series]
    assert next(p for p in series if p["data"].name == "rsi")["panel"] == 2
    assert next(p for p in series if p["data"].name == "macd")["panel"] == 3
    sma50 = next(p["data"] for p in series if p["data"].name == "sma50")
    assert sma50.iloc[:49].isna().all()
    fig.savefig.assert_called_once()
    fallback.assert_not_called()
