# -*- coding: utf-8 -*-
"""Testes do diário de sinais (sem rede)."""
import os
from datetime import date, timedelta

import pandas as pd
import pytest
import diario_sinais

from diario_sinais import (
    carregar_sinais, salvar_sinais, registrar_sinal,
    avaliar_sinal, atualizar_resultados, resumo_desempenho,
    formatar_resumo_desempenho,
)

CAMINHO_TEMP = "_test_sinais.json"
BUSCAR_HISTORICO_ORIGINAL = diario_sinais.buscar_historico_fechamentos


@pytest.fixture(autouse=True)
def isolar_diario(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    def sem_rede(*args, **kwargs):
        pytest.fail("Teste tentou buscar historico sem mock")
    monkeypatch.setattr(diario_sinais, "buscar_historico_fechamentos", sem_rede)


def _limpar():
    if os.path.exists(CAMINHO_TEMP):
        os.unlink(CAMINHO_TEMP)


def test_registrar_sinal_novo():
    _limpar()
    sinal = registrar_sinal("PETR4", "compra", 9, 43.11, arquivo=CAMINHO_TEMP)
    assert sinal["direcao"] == "compra"
    assert sinal["score"] == 9
    assert sinal["resultado"] is None

    sinais = carregar_sinais(CAMINHO_TEMP)
    assert "PETR4" in sinais
    assert len(sinais["PETR4"]) == 1
    _limpar()


def test_registrar_sinal_nao_duplica_mesmo_dia():
    _limpar()
    registrar_sinal("PETR4", "compra", 9, 43.11, arquivo=CAMINHO_TEMP)
    registrar_sinal("PETR4", "compra", 9, 43.11, arquivo=CAMINHO_TEMP)
    sinais = carregar_sinais(CAMINHO_TEMP)
    assert len(sinais["PETR4"]) == 1
    _limpar()


def test_registrar_sinal_permite_dias_diferentes():
    _limpar()
    registrar_sinal("PETR4", "compra", 9, 43.11, arquivo=CAMINHO_TEMP)
    # Força data anterior para simular outro dia
    sinais = carregar_sinais(CAMINHO_TEMP)
    sinais["PETR4"][-1]["data"] = (date.today() - timedelta(days=1)).isoformat()
    salvar_sinais(sinais, CAMINHO_TEMP)

    registrar_sinal("PETR4", "compra", 9, 44.00, arquivo=CAMINHO_TEMP)
    sinais = carregar_sinais(CAMINHO_TEMP)
    assert len(sinais["PETR4"]) == 2
    _limpar()


def test_avaliar_sinal_compra_acerto():
    sinal = {"direcao": "compra", "preco": 10.0}
    assert avaliar_sinal(sinal, 11.0) == "acerto"
    assert avaliar_sinal(sinal, 9.0) == "erro"


def test_avaliar_sinal_venda_acerto():
    sinal = {"direcao": "venda", "preco": 10.0}
    assert avaliar_sinal(sinal, 9.0) == "acerto"
    assert avaliar_sinal(sinal, 11.0) == "erro"


def test_avaliar_sinal_direcao_invalida():
    sinal = {"direcao": "neutro", "preco": 10.0}
    assert avaliar_sinal(sinal, 11.0) == "indefinido"


def test_atualizar_resultados_preenche_antigos(monkeypatch):
    _limpar()
    # Registra um sinal de 15 dias atrás
    registrar_sinal("PETR4", "compra", 9, 43.11, arquivo=CAMINHO_TEMP)
    sinais = carregar_sinais(CAMINHO_TEMP)
    sinais["PETR4"][-1]["data"] = (date.today() - timedelta(days=15)).isoformat()
    salvar_sinais(sinais, CAMINHO_TEMP)

    datas = pd.bdate_range(end=date.today() - timedelta(days=1), periods=10)
    monkeypatch.setattr(diario_sinais, "buscar_historico_fechamentos",
                        lambda *args: pd.Series(45.0, index=datas))
    sinais = atualizar_resultados({"PETR4": 45.00}, dias_min=10, arquivo=CAMINHO_TEMP)
    assert sinais["PETR4"][0]["resultado"] == "acerto"
    _limpar()


def test_atualizar_resultados_ignora_recentes():
    _limpar()
    registrar_sinal("PETR4", "compra", 9, 43.11, arquivo=CAMINHO_TEMP)
    sinais = atualizar_resultados({"PETR4": 45.00}, dias_min=10, arquivo=CAMINHO_TEMP)
    # Sinal de hoje, não deve ser avaliado ainda
    assert sinais["PETR4"][0]["resultado"] is None
    _limpar()


def test_resumo_desempenho():
    sinais = {
        "PETR4": [
            {"data": "2026-01-01", "direcao": "compra", "score": 9, "preco": 10, "resultado": "acerto", "metodo_avaliacao": "fechamento_n_sessoes"},
            {"data": "2026-01-02", "direcao": "compra", "score": 8, "preco": 10, "resultado": "erro", "metodo_avaliacao": "fechamento_n_sessoes"},
        ],
        "VALE3": [
            {"data": "2026-01-03", "direcao": "venda", "score": 9, "preco": 10, "resultado": "acerto", "metodo_avaliacao": "fechamento_n_sessoes"},
        ],
    }
    resumo = resumo_desempenho(sinais)
    assert resumo["total_avaliados"] == 3
    assert resumo["acertos"] == 2
    assert resumo["taxa_acerto_pct"] == 66.7
    assert resumo["por_direcao"]["compra"]["acertos"] == 1
    assert resumo["por_direcao"]["venda"]["acertos"] == 1


def test_resumo_desempenho_vazio():
    resumo = resumo_desempenho({})
    assert resumo["total_avaliados"] == 0
    assert resumo["taxa_acerto_pct"] == 0


def test_formatar_resumo_sem_sinais():
    _limpar()
    texto = formatar_resumo_desempenho()
    assert "Diário de sinais" in texto or "não há sinais" in texto.lower()
    _limpar()


@pytest.fixture
def janela(monkeypatch):
    class Hoje(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 30)
    monkeypatch.setattr(diario_sinais, "date", Hoje)
    # 7/set e fim de semana nao sao sessoes. 10a sessao: 21/set.
    datas = pd.to_datetime([
        "2026-09-04", "2026-09-08", "2026-09-09", "2026-09-10",
        "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16",
        "2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22",
        "2026-09-23", "2026-09-24",
    ])
    historico = pd.Series([100.0] * 10 + [90.0, 150.0, 200.0, 200.0], index=datas)
    salvar_sinais({"PETR4": [{"data": "2026-09-04", "direcao": "compra",
                              "preco": 100.0, "resultado": None}]}, CAMINHO_TEMP)
    return historico


def test_decima_sessao_nao_preco_atual_nem_execucao_atrasada(janela, monkeypatch):
    chamadas = []
    def buscar(ticker, inicio, fim):
        chamadas.append((ticker, inicio, fim))
        return janela
    monkeypatch.setattr(diario_sinais, "buscar_historico_fechamentos", buscar)
    resultado = atualizar_resultados({"PETR4": 999.0}, arquivo=CAMINHO_TEMP)
    sinal = resultado["PETR4"][0]
    assert sinal["resultado"] == "erro"
    assert sinal["preco_avaliacao"] == 90.0
    assert sinal["data_avaliacao"] == "2026-09-21"
    assert sinal["sessoes_avaliacao"] == 10
    assert chamadas == [("PETR4", date(2026, 9, 4), date(2026, 9, 30))]
    assert carregar_sinais(CAMINHO_TEMP) == resultado
    # Avaliacoes fechadas sao imutaveis e nao exigem novo download.
    assert atualizar_resultados({"PETR4": 1.0}, arquivo=CAMINHO_TEMP) == resultado
    assert len(chamadas) == 1


def test_avalia_fora_watchlist_e_venda(janela, monkeypatch):
    sinais = carregar_sinais(CAMINHO_TEMP)
    sinais["PETR4"][0]["direcao"] = "venda"
    salvar_sinais(sinais, CAMINHO_TEMP)
    monkeypatch.setattr(diario_sinais, "buscar_historico_fechamentos", lambda *args: janela)
    assert atualizar_resultados({}, arquivo=CAMINHO_TEMP)["PETR4"][0]["resultado"] == "acerto"


@pytest.mark.parametrize("modo", ["nove_sessoes", "nan_na_decima", "vazio", "falha", "infinito"])
def test_sem_fechamento_valido_nao_usa_cotacao_atual(janela, monkeypatch, modo):
    if modo == "nove_sessoes":
        janela = janela.iloc[:10]  # inclui dia do sinal, apenas nove posteriores
    elif modo == "nan_na_decima":
        janela.iloc[10] = float("nan")
    elif modo == "infinito":
        janela.iloc[10] = float("inf")
    elif modo == "vazio":
        janela = pd.Series(dtype=float)
    def buscar(*args):
        if modo == "falha":
            raise RuntimeError("offline")
        return janela
    monkeypatch.setattr(diario_sinais, "buscar_historico_fechamentos", buscar)
    sinal = atualizar_resultados({"PETR4": 999}, arquivo=CAMINHO_TEMP)["PETR4"][0]
    assert sinal["resultado"] is None
    assert "data_avaliacao" not in sinal


def test_exclui_barra_hoje_e_futura(janela, monkeypatch):
    janela = janela.iloc[:10]
    janela.loc[pd.Timestamp("2026-09-30")] = 90
    janela.loc[pd.Timestamp("2026-10-01")] = 90
    monkeypatch.setattr(diario_sinais, "buscar_historico_fechamentos", lambda *args: janela)
    assert atualizar_resultados({}, arquivo=CAMINHO_TEMP)["PETR4"][0]["resultado"] is None


def test_ordena_deduplica_e_respeita_janela_customizada(janela, monkeypatch):
    janela = pd.concat([janela, janela.iloc[[1]]]).iloc[::-1]
    monkeypatch.setattr(diario_sinais, "buscar_historico_fechamentos", lambda *args: janela)
    sinal = atualizar_resultados({}, dias_min=2, arquivo=CAMINHO_TEMP)["PETR4"][0]
    assert sinal["data_avaliacao"] == "2026-09-09"
    assert sinal["sessoes_avaliacao"] == 2
    assert sinal["resultado"] == "erro"  # empate nao e acerto


@pytest.mark.parametrize("dias", [0, -1, 1.5, True])
def test_janela_invalida(dias):
    with pytest.raises(ValueError):
        atualizar_resultados({}, dias_min=dias, arquivo=CAMINHO_TEMP)


def test_legados_preservados_sem_fingir_janela_fixa(monkeypatch):
    sinais = {"PETR4": [{"data": "2026-01-01", "direcao": "compra",
                          "preco": 100, "resultado": "lucro"}]}
    salvar_sinais(sinais, CAMINHO_TEMP)
    assert atualizar_resultados({"PETR4": 50}, arquivo=CAMINHO_TEMP) == sinais
    resumo = resumo_desempenho(sinais)
    assert resumo["total_avaliados"] == 0
    assert resumo["total_sem_janela_validada"] == 1
    monkeypatch.setattr(diario_sinais, "carregar_sinais", lambda: sinais)
    texto = formatar_resumo_desempenho()
    assert "Acerto direcional" in texto
    assert "PnL" in texto
    assert "fora da taxa" in texto


def test_busca_historico_intervalo_e_colunas_yfinance(monkeypatch):
    import yfinance as yf
    chamadas = []
    df = pd.DataFrame([[42.0]], index=pd.to_datetime(["2026-09-08"]),
                      columns=pd.MultiIndex.from_tuples([("Close", "PETR4.SA")]))
    def download(*args, **kwargs):
        chamadas.append((args, kwargs))
        return df
    # Usa a implementacao original apesar da fixture de protecao contra rede.
    funcao = BUSCAR_HISTORICO_ORIGINAL
    monkeypatch.setattr(yf, "download", download)
    resultado = funcao("PETR4", date(2026, 9, 4), date(2026, 9, 30))
    assert resultado.iloc[0] == 42.0
    assert chamadas == [(("PETR4.SA",), {"start": "2026-09-04", "end": "2026-09-30",
                                        "interval": "1d", "auto_adjust": False, "progress": False})]
