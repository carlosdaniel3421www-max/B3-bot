"""Regressoes das fronteiras entre relatorio, comandos e provedores."""
from datetime import date, timedelta
from unittest.mock import Mock

import pandas as pd
import pytest

import relatorio_diario as rd
import telegram_bot as tb


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", Mock(side_effect=AssertionError("Sem rede")))


def test_comando_vazio_e_enderecado(monkeypatch):
    assert tb.processar_comando("fake", 1, "  ") is None
    assert "/registrar" in tb.processar_comando("fake", 1, "/ajuda@meubot")
    analisar = Mock(return_value="gestao")
    monkeypatch.setattr(tb, "_analisar_posicoes_ia", analisar)
    assert tb.processar_comando("fake", 1, "/analisar_posições") == "gestao"


@pytest.mark.parametrize("modulo", [rd, tb])
def test_nemotron_textual_sem_gemini(monkeypatch, modulo):
    monkeypatch.setattr(modulo.config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(modulo.config, "CARLOS", "fake")
    monkeypatch.setattr(modulo.config, "USAR_IA_ANALISE", True)
    factory = Mock()
    monkeypatch.setattr(modulo, "AIAnalyzer", factory)
    assert modulo._montar_analisador_ia() is factory.return_value
    assert factory.call_args.kwargs["CARLOS"] == "fake"


def test_confianca_trava_nao_e_certeza_ou_html():
    texto = rd._formatar_veredito_trava({"fazer_trava": True, "nivel_certeza": "85"})
    assert "subjetiva" in texto and "nao calibrada" in texto
    assert "certeza" not in texto
    texto = rd._formatar_veredito_trava({"fazer_trava": True, "nivel_certeza": "<script>"})
    assert "<script>" not in texto


def test_gestao_nao_baixa_acao_de_trava(monkeypatch):
    posicoes = {"CMIG4": {"tipo_operacao": "trava"}, "PETR4": {}}
    monkeypatch.setattr(rd, "carregar_posicoes", Mock(return_value=posicoes))
    buscar = Mock(return_value={"PETR4": 40})
    monkeypatch.setattr(tb, "_precos_posicoes", buscar)
    formatar = Mock(return_value="ok")
    monkeypatch.setattr(rd, "formatar_gestao_todas", formatar)
    assert rd.montar_gestao_posicoes([]) == "ok"
    buscar.assert_called_once_with({"PETR4": {}})


@pytest.mark.parametrize("resultados", [[], [{"ticker": "PETR4", "preco": 38.0}]])
def test_gestao_mesma_base_com_ou_sem_screener(monkeypatch, resultados):
    posicao = {"ticker": "PETR4", "direcao": "compra", "preco_entrada": 40.0,
               "stop": 39.0, "alvo": 44.0, "quantidade": 100,
               "data_entrada": date.today().isoformat(), "prazo_maximo_dias": 20}
    monkeypatch.setattr(rd, "carregar_posicoes", Mock(return_value={"PETR4": posicao}))
    buscar = Mock(return_value={"PETR4": 40.0})
    monkeypatch.setattr(tb, "_precos_posicoes", buscar)
    texto = rd.montar_gestao_posicoes(resultados)
    assert "MANTER" in texto
    assert "SAIR AGORA" not in texto
    buscar.assert_called_once_with({"PETR4": posicao})


def test_gestao_usa_fechamento_nao_candle_parcial(monkeypatch):
    hoje = pd.Timestamp.now(tz="America/Sao_Paulo").date()
    df = pd.DataFrame({"Close": [40.0, 90.0]}, index=pd.to_datetime([hoje - timedelta(days=1), hoje]))
    baixar = Mock(return_value=df)
    monkeypatch.setattr("yfinance.download", baixar)
    assert tb._precos_posicoes({"PETR4": {}}) == {"PETR4": 40.0}
    assert baixar.call_args.kwargs["threads"] is False
    assert baixar.call_args.kwargs["auto_adjust"] is False
