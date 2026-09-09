"""Regressoes isoladas: arquivos sinteticos, datas fixas e nenhuma rede."""
import copy
import inspect
import json
import runpy
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd
import pytest

import backtest
import diario_sinais as diario
import estado


@pytest.fixture(autouse=True)
def isolamento(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def proibido(*args, **kwargs):
        pytest.fail("Acesso de rede nao autorizado")

    monkeypatch.setattr(socket.socket, "connect", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)
    monkeypatch.setattr(backtest, "baixar_dados", proibido)
    monkeypatch.setattr(diario, "buscar_historico_fechamentos", proibido)

    class Hoje(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 15)

    monkeypatch.setattr(diario, "date", Hoje)
    monkeypatch.setattr(estado, "date", Hoje)


@pytest.mark.parametrize("modulo,carregar,salvar", [
    (estado, estado.carregar_estado, estado.salvar_estado),
    (diario, diario.carregar_sinais, diario.salvar_sinais),
])
@pytest.mark.parametrize("conteudo", ['{', '[]', 'null', '{"X": null}', '{"X":{},"X":{}}'])
def test_json_invalido_nao_vira_vazio(tmp_path, modulo, carregar, salvar, conteudo):
    caminho = tmp_path / "corrompido.json"
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(ValueError, match="preservado"):
        carregar(caminho)
    assert caminho.read_text(encoding="utf-8") == conteudo
    assert carregar(tmp_path / "inexistente.json") == {}


@pytest.mark.parametrize("carregar", [estado.carregar_estado, diario.carregar_sinais])
def test_erro_io_nao_vira_vazio(tmp_path, carregar):
    with pytest.raises(ValueError, match="preservado"):
        carregar(tmp_path)


@pytest.mark.parametrize("carregar,conteudo", [
    (estado.carregar_estado, '{"X":{"score":NaN}}'),
    (diario.carregar_sinais, '{"X":[{"preco":Infinity}]}'),
])
def test_json_constantes_nao_finitas_rejeitadas(tmp_path, carregar, conteudo):
    caminho = tmp_path / "invalido.json"
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(ValueError):
        carregar(caminho)


@pytest.mark.parametrize("salvar,dados", [
    (estado.salvar_estado, {"X": {"score": 8}}),
    (diario.salvar_sinais, {"X": [{"preco": 100}]}),
])
def test_gravacao_atomica_preserva_anterior_em_falha(tmp_path, monkeypatch, salvar, dados):
    caminho = tmp_path / "historico.json"
    salvar(dados, caminho)
    anterior = caminho.read_bytes()

    def falhar(*args):
        raise OSError("falha na substituicao")

    monkeypatch.setattr(estado.os, "replace", falhar)
    with pytest.raises(OSError):
        salvar({}, caminho)
    assert caminho.read_bytes() == anterior
    assert list(tmp_path.iterdir()) == [caminho]


@pytest.mark.parametrize("salvar,dados", [
    (estado.salvar_estado, {"X": {"extra": float("nan")}}),
    (diario.salvar_sinais, {"X": [{"preco": float("inf")}] }),
])
def test_serializacao_invalida_nao_trunca(tmp_path, salvar, dados):
    caminho = tmp_path / "historico.json"
    salvar({}, caminho)
    with pytest.raises(ValueError):
        salvar(dados, caminho)
    assert caminho.read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize("score", [None, "8", True, float("nan"), float("inf"), 8.5])
def test_score_invalido_nao_muta(score):
    dados = {}
    with pytest.raises(ValueError):
        estado.score_suavizado(dados, "X", score, "compra")
    assert dados == {}
    with pytest.raises(ValueError):
        estado.eh_alerta_novo(dados, "X", score, "compra", 8)
    with pytest.raises(ValueError):
        estado.atualizar_estado(dados, "X", score, "compra", 8)
    assert dados == {}


@pytest.mark.parametrize("janela", [0, -1, True, 1.5, None])
def test_janela_score_invalida(janela):
    dados = {}
    with pytest.raises(ValueError):
        estado.score_suavizado(dados, "X", 8, "compra", janela)
    assert dados == {}


@pytest.mark.parametrize("historico", [None, {}, [{}], [{"score": "8", "direcao": "compra"}], [True]])
def test_historico_score_malformado_fail_closed(historico, tmp_path):
    dados = {"X": {"score_history": historico}}
    anterior = copy.deepcopy(dados)
    with pytest.raises(ValueError):
        estado.score_suavizado(dados, "X", 8, "compra")
    assert dados == anterior
    caminho = tmp_path / "estado.json"
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    with pytest.raises(ValueError):
        estado.carregar_estado(caminho)


def test_clamp_antes_de_persistir_e_neutro_nao_alerta():
    dados = {}
    assert estado.score_suavizado(dados, "X", 50, "compra") == 10
    assert dados["X"]["score_history"][0]["score"] == 10
    assert estado.eh_alerta_novo(dados, "X", 10, "neutro", 8) is False
    estado.atualizar_estado(dados, "X", 10, "neutro", 8)
    assert "score" not in dados["X"]
    assert dados["X"]["score_history"][0]["score"] == 10


@pytest.mark.parametrize("ticker", [None, "", " ", []])
def test_estado_ticker_invalido_nao_muta(ticker):
    dados = {}
    for funcao, extra in ((estado.score_suavizado, ()),
                          (estado.eh_alerta_novo, (8,)),
                          (estado.atualizar_estado, (8,))):
        with pytest.raises(ValueError):
            funcao(dados, ticker, 8, "compra", *extra)
        assert dados == {}


@pytest.mark.parametrize("campo,valor", [
    ("ticker", None), ("ticker", " "), ("ticker", ".sa"),
    ("direcao", "neutro"), ("score", True), ("score", 11),
    ("preco", "10"), ("preco", None), ("preco", True),
    ("preco", float("nan")), ("preco", float("inf")), ("preco", 0.001),
])
def test_registro_invalido_nao_cria_arquivo(tmp_path, campo, valor):
    args = dict(ticker="X", direcao="compra", score=8, preco=100)
    args[campo] = valor
    with pytest.raises(ValueError):
        diario.registrar_sinal(**args)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("preco", [None, "100", True, [], float("nan"), float("inf"), -1])
def test_avaliacao_preco_invalido_indefinida(preco):
    assert diario.avaliar_sinal({"preco": preco, "direcao": "compra"}, 110) == "indefinido"
    assert diario.avaliar_sinal({"preco": 100, "direcao": "compra"}, preco) == "indefinido"


def test_dedup_diario_nao_depende_ordem_e_normaliza_ticker():
    original = diario.registrar_sinal(" petr4.sa ", "compra", 8, 100)
    dados = diario.carregar_sinais()
    dados["PETR4"].append(dict(original, data="2026-09-01"))
    diario.salvar_sinais(dados)
    assert diario.registrar_sinal("PETR4", "venda", 10, 90) == original
    assert diario.carregar_sinais() == dados


def test_registros_concorrentes_nao_perdem_tickers_ou_duplicam():
    barreira = threading.Barrier(8)

    def registrar(i):
        barreira.wait(timeout=5)
        diario.registrar_sinal(f"X{i % 4}", "compra", 8, 100)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(registrar, range(8)))
    dados = diario.carregar_sinais()
    assert set(dados) == {"X0", "X1", "X2", "X3"}
    assert all(len(registros) == 1 for registros in dados.values())


def _pendente(data="2026-09-08"):
    return {"data": data, "preco": 100, "score": 8, "direcao": "compra", "resultado": None}


def test_avaliacao_concorrente_com_registro_preserva_ambos(monkeypatch):
    diario.salvar_sinais({"ANTIGO": [_pendente()]})
    buscando = threading.Event()
    liberar = threading.Event()
    registrando = threading.Event()

    def historico(*args):
        buscando.set()
        assert liberar.wait(timeout=5)
        return pd.Series([110], index=pd.to_datetime(["2026-09-09"]))

    def registrar():
        registrando.set()
        return diario.registrar_sinal("NOVO", "venda", 9, 100)

    monkeypatch.setattr(diario, "buscar_historico_fechamentos", historico)
    with ThreadPoolExecutor(max_workers=2) as pool:
        avaliacao = pool.submit(diario.atualizar_resultados, {}, 1)
        try:
            assert buscando.wait(timeout=5)
            registro = pool.submit(registrar)
            assert registrando.wait(timeout=5)
        finally:
            liberar.set()
        avaliacao.result(timeout=5)
        registro.result(timeout=5)
    dados = diario.carregar_sinais()
    assert dados["ANTIGO"][0]["resultado"] == "acerto"
    assert dados["NOVO"][0]["resultado"] is None


@pytest.mark.parametrize("data", [None, 123, "2026-02-30", "20260908", "2026-09-20"])
def test_data_emissao_invalida_ou_futura_nao_busca(data):
    dados = {"X": [_pendente(data)]}
    diario.salvar_sinais(dados)
    assert diario.atualizar_resultados({}, 1) == dados


@pytest.mark.parametrize("historico", [
    pd.Series([110], index=[123]),
    pd.Series([110], index=[pd.NaT]),
    pd.Series([110, 90], index=pd.to_datetime(["2026-09-09", "2026-09-09"])),
    pd.Series([True], index=pd.to_datetime(["2026-09-09"])),
    pd.Series(["110"], index=pd.to_datetime(["2026-09-09"])),
    pd.DataFrame({"Close": [110]}, index=pd.to_datetime(["2026-09-09"])),
])
def test_historico_ambiguo_ou_invalido_nao_avalia(monkeypatch, historico):
    diario.salvar_sinais({"X": [_pendente()]})
    monkeypatch.setattr(diario, "buscar_historico_fechamentos", lambda *args: historico)
    assert diario.atualizar_resultados({}, 1)["X"][0]["resultado"] is None


def test_historico_fuso_e_n_esima_sessao(monkeypatch):
    diario.salvar_sinais({"X": [_pendente()]})
    historico = pd.Series([999, 110, 90], index=pd.to_datetime([
        "2026-09-09 01:00Z", "2026-09-10 01:00Z", "2026-09-11 01:00Z",
    ]))
    monkeypatch.setattr(diario, "buscar_historico_fechamentos", lambda *args: historico)
    sinal = diario.atualizar_resultados({}, 2)["X"][0]
    assert sinal["data_avaliacao"] == "2026-09-10"
    assert sinal["preco_avaliacao"] == 90
    assert sinal["resultado"] == "erro"


def test_resumo_nao_conta_direcao_invalida_e_escapa_html(monkeypatch):
    dados = {"<X>": [dict(_pendente(), direcao=[], resultado="acerto",
                         metodo_avaliacao="fechamento_n_sessoes")]}
    assert diario.resumo_desempenho(dados)["total_avaliados"] == 0
    monkeypatch.setattr(diario, "carregar_sinais", lambda: dados)
    assert "&lt;X&gt;" in diario.formatar_resumo_desempenho()


def _trade(data, retorno):
    return {"data_entrada": pd.Timestamp(data), "data_saida": pd.Timestamp(data),
            "retorno_pct": retorno, "direcao": "compra", "score_entrada": 8}


def test_multi_independe_ordem_e_agrupa_saidas_simultaneas(monkeypatch):
    trades = {"A": [_trade("2026-09-01", 10), _trade("2026-09-03", -10)],
              "B": [_trade("2026-09-02", -10), _trade("2026-09-03", 10)]}
    monkeypatch.setattr(backtest, "rodar_backtest", lambda ticker, **kw:
                        backtest.montar_estatisticas(ticker, trades[ticker]))
    a = backtest.rodar_backtest_multi(["A", "B"])
    b = backtest.rodar_backtest_multi(["B", "A"])
    for chave in ("drawdown_soma_pp", "soma_retornos_pp", "profit_factor", "taxa_acerto_pct", "trades"):
        assert a[chave] == b[chave]
    assert a["drawdown_soma_pp"] == -10
    assert a["soma_retornos_pp"] == 0
    assert "max_drawdown_pct" not in a
    assert "retorno_total_pct" not in a
    assert "nao representa capital" in a["metrica"]
    assert "ticker" not in trades["A"][0]  # Nao muta os resultados individuais.


def test_multi_deduplica_tickers_e_informa_falhas(monkeypatch):
    chamadas = []

    def rodar(ticker, **kwargs):
        chamadas.append(ticker)
        if ticker == "RUIM":
            raise ValueError("sem historico")
        return backtest.montar_estatisticas(ticker, [_trade("2026-09-01", 5)])

    monkeypatch.setattr(backtest, "rodar_backtest", rodar)
    resultado = backtest.rodar_backtest_multi([" a.sa ", "A", "RUIM"])
    assert chamadas == ["A", "RUIM"]
    assert resultado["total_trades"] == 1
    assert resultado["falhas"] == ["RUIM: sem historico"]


@pytest.mark.parametrize("kwargs", [
    {"nivel_minimo": -1}, {"nivel_minimo": 11}, {"nivel_minimo": True},
    {"nivel_minimo": 8.5}, {"max_dias_holding": -1},
    {"max_dias_holding": True}, {"max_dias_holding": 1.5},
])
def test_limites_invalidos_antes_de_buscar(kwargs):
    with pytest.raises(ValueError):
        backtest.rodar_backtest("X", **kwargs)
    with pytest.raises(ValueError):
        backtest.rodar_backtest_multi(["X"], **kwargs)


def test_defaults_alinhados_ao_corte_entrar():
    for funcao in (backtest.rodar_backtest, backtest.rodar_backtest_multi):
        assert inspect.signature(funcao).parameters["nivel_minimo"].default == 8


def test_apenas_empates_nao_geram_profit_factor_infinito():
    resultado = backtest.montar_estatisticas("X", [_trade("2026-09-01", 0)])
    assert resultado["profit_factor"] == "indefinido (sem ganhos/perdas)"
    assert resultado["taxa_acerto_pct"] == 0


@pytest.mark.parametrize("retorno", [float("nan"), float("inf"), True, "5"])
def test_estatisticas_rejeitam_retorno_invalido(retorno):
    with pytest.raises(ValueError):
        backtest.montar_estatisticas("X", [_trade("2026-09-01", retorno)])


def test_saida_multi_nao_afirma_carteira(monkeypatch, capsys):
    monkeypatch.setattr(backtest, "rodar_backtest", lambda ticker, **kw:
                        backtest.montar_estatisticas(ticker, [_trade("2026-09-01", 5)]))
    backtest.imprimir_resultado_multi(backtest.rodar_backtest_multi(["X"]))
    texto = capsys.readouterr().out
    assert "nao e retorno de capital" in texto
    assert "sem MTM" in texto
    assert "40-55%" not in texto


@pytest.mark.parametrize("argumentos", [
    ["X", "--max-dias", "-1"], ["X", "--nivel-minimo", "11"],
])
def test_cli_rejeita_limites_antes_de_rede(monkeypatch, argumentos):
    monkeypatch.setattr(sys, "argv", ["backtest.py", *argumentos])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(backtest.__file__, run_name="__main__")
    assert exc.value.code == 2


@pytest.mark.parametrize("stop", [float("inf"), float("nan"), True, None])
def test_backtest_limites_stop_invalidos(monkeypatch, stop):
    df = pd.DataFrame({"open": [100.] * 212}, index=pd.bdate_range("2025-01-01", periods=212))
    monkeypatch.setattr(backtest, "baixar_dados", lambda *a, **kw: df)
    monkeypatch.setattr(backtest, "calcular_indicadores", lambda df: df)
    monkeypatch.setattr(backtest, "avaliar_ativo", lambda df: {"score": 8, "direcao": "compra"})
    monkeypatch.setattr(backtest, "sugerir_stop_alvo", lambda *a: {"stop": stop, "alvo": 110})
    with pytest.raises(ValueError, match="stop e alvo"):
        backtest.rodar_backtest("X")
