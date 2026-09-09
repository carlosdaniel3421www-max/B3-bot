"""Auditoria offline de IA, noticias, calendario e configuracao."""
import json
import runpy
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

import ai_analyzer
import calendario
import noticias
from ai_analyzer import AIAnalyzer


@pytest.fixture(autouse=True)
def auditoria_sem_rede(monkeypatch):
    tentativas = []

    def bloquear(*args, **kwargs):
        tentativas.append(True)
        raise AssertionError("Rede proibida")

    for alvo in ("socket.socket.connect", "socket.socket.connect_ex", "socket.getaddrinfo",
                 "requests.sessions.Session.request", "httpx.Client.send",
                 "curl_cffi.requests.Session.request"):
        monkeypatch.setattr(alvo, bloquear)
    yield
    assert not tentativas, "Uma chamada de rede foi bloqueada, mesmo que a excecao tenha sido capturada"


@pytest.fixture
def resposta():
    return dict(concorda_com_robo=True, vale_operar=True, entrada_agora=True,
                esperar_confirmacao=False, operacao="CALL", confianca=75,
                explicacao="Sinais fornecidos alinhados", risco="Liquidez",
                pontos_fortes=["Tendencia"], pontos_fracos=[], divergencia="")


@pytest.fixture
def dados():
    return dict(ticker="PETR4", current_price=10.0, ema21=9.5, ema200=9.0,
                rsi=60.0, macd=0.1, volume=1000.0, atr=0.3, support=9.0,
                resistance=12.0, score=9, direction="compra", reasons=["Tendencia"])


@pytest.fixture
def ia(monkeypatch):
    analisador = AIAnalyzer("fake")
    monkeypatch.setattr(analisador, "_get_client", Mock(return_value=object()))
    monkeypatch.setattr(ai_analyzer.time, "sleep", Mock())
    return analisador


@pytest.mark.parametrize("score", [0, 5.9, 6, 7, 7.99, 8, 10])
def test_score_so_bloqueia_nunca_fabrica_aprovacao(ia, resposta, score):
    original = deepcopy(resposta)
    r = ia._validate_response(resposta, "compra", score)
    assert r["vale_operar"] is (score >= 8)
    assert r["entrada_agora"] is (score >= 8)
    assert r["concorda_com_robo"] is True
    assert r["operacao"] == "CALL"
    assert resposta == original
    resposta.update(concorda_com_robo=False, vale_operar=False, entrada_agora=False,
                    esperar_confirmacao=True, divergencia="Risco de exaustao")
    r = ia._validate_response(resposta, "compra", score)
    assert not r["concorda_com_robo"] and not r["vale_operar"] and not r["entrada_agora"]
    assert r["divergencia"] == "Risco de exaustao"


@pytest.mark.parametrize("campo,valor", [
    ("concorda_com_robo", "false"), ("vale_operar", "true"), ("entrada_agora", 1),
    ("esperar_confirmacao", None), ("confianca", True), ("confianca", "80"),
    ("confianca", 80.5), ("confianca", -1), ("confianca", 100), ("confianca", 101),
    ("confianca", float("nan")), ("confianca", float("inf")),
    ("operacao", "neutro"), ("operacao", None), ("explicacao", " "),
    ("explicacao", {}), ("pontos_fortes", "alta"), ("pontos_fracos", [None]),
    ("stop", float("inf")), ("risco", []),
])
def test_schema_invalido_rejeitado(ia, resposta, campo, valor):
    resposta[campo] = valor
    assert ia._validate_response(resposta, "compra", 9) is None


@pytest.mark.parametrize("valor", [None, {}, [], [1], "texto", {"foo": 1}])
def test_schema_ausente_nao_aprova(ia, valor):
    assert ia._validate_response(valor, "compra", 10) is None


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -1, 11, "9", True])
def test_score_invalido(ia, resposta, score):
    assert ia._validate_response(resposta, "compra", score) is None


@pytest.mark.parametrize("direcao,operacao,permitida", [
    (" compra ", " buy ", True), ("venda", "SELL", True), ("neutro", "PUT", False),
    ("compra", "PUT", False), ("venda", "CALL", False), ("???", "CALL", False),
])
def test_direcao_sem_inventar_ou_inverter(ia, resposta, direcao, operacao, permitida):
    resposta["operacao"] = operacao
    r = ia._validate_response(resposta, direcao, 9)
    assert r["vale_operar"] is permitida
    assert r["entrada_agora"] is permitida


def test_confirmacao_e_precos_sem_fonte(ia, resposta):
    resposta.update(esperar_confirmacao=True, preco_ideal_entrada="999", stop="888",
                    alvo="2000", strike_sugerido="123")
    r = ia._validate_response(resposta, "compra", 9)
    assert not r["entrada_agora"]
    assert all(r[c] == "" for c in ("preco_ideal_entrada", "stop", "alvo", "strike_sugerido"))
    texto = ia.format_telegram_message(r)
    assert "999" not in texto and "123" not in texto
    assert "subjetiva" in texto and "calibrada" in texto and "75%" not in texto
    assert "confirma" in texto


def test_html_escapado(ia, resposta):
    resposta.update(explicacao="<b>nao</b> & risco", risco="<alto>", divergencia="<div>")
    texto = ia.format_telegram_message(ia._validate_response(resposta, "compra", 9))
    assert "&lt;b&gt;" in texto and "&lt;alto&gt;" in texto and "&lt;div&gt;" in texto
    assert ia.format_telegram_message(None) == "IA indispon\u00edvel."


@pytest.mark.parametrize("texto", [
    '[]', '[{"vale_operar":true}]', 'null', 'true', '{}', '{"x":NaN}',
    '{"x":Infinity}', '{"x":1e999}', '{"x":1,"x":2}',
    '{"outer":{"vale_operar":true}', 'prefixo {"outer":{"a":1}',
    '{"a":1} {"a":2}', '```json\n{"a":1}', None,
])
def test_json_invalido_ou_fragmento(ia, texto):
    assert ia._extract_json(texto) is None


@pytest.mark.parametrize("envolver", [lambda t: t, lambda t: "```json\n" + t + "\n```",
                                       lambda t: "Resposta:\n" + t + "\nFim."])
def test_json_aninhado_com_escapes(ia, envolver):
    obj = {"analises": [{"ticker": "PETR4", "explicacao": 'chaves { } e "aspas"'}]}
    assert ia._extract_json(envolver(json.dumps(obj))) == obj


@pytest.mark.parametrize("campo", ["current_price", "ema21", "ema200", "rsi", "macd",
                                   "volume", "atr", "support", "resistance", "score"])
@pytest.mark.parametrize("valor", [float("nan"), float("inf"), True])
def test_payload_invalido_nao_chama_provedor(ia, dados, monkeypatch, campo, valor):
    dados[campo] = valor
    chamada = Mock()
    monkeypatch.setattr(ia, "_call_gemini", chamada)
    assert ia.analyze_asset(**dados) is None
    assert "payload" in ia.ultimo_erro
    chamada.assert_not_called()


@pytest.mark.parametrize("campo,valor", [("current_price", 0), ("support", -1),
    ("atr", -1), ("volume", -1), ("rsi", 101), ("rsi", -1), ("score", 11)])
def test_payload_limites(ia, dados, campo, valor):
    dados[campo] = valor
    with pytest.raises(ValueError):
        ia._build_payload(**dados)


def test_payload_distancia_zero_prompt_e_contexto(ia, dados):
    dados.update(support=10.0, resistance=10.0, extra_context={"valor": float("nan")})
    payload = ia._build_payload(**dados)
    assert payload["niveis"]["distancia_suporte_percentual"] == 0
    assert payload["niveis"]["distancia_resistencia_percentual"] == 0
    with pytest.raises(ValueError):
        ia._build_prompt(payload)
    payload.pop("contexto_extra")
    prompt = ia._build_prompt(payload)
    assert "FOR\u00c7ADA A SEGUIR" not in prompt
    assert "PODE discordar" in prompt and "calibrada" in prompt
    assert "Deixe preco_ideal_entrada" in prompt


def test_retry_schema_e_limpeza_erro(ia, dados, resposta, monkeypatch):
    chamar = Mock(side_effect=[{"foo": 1}, resposta])
    monkeypatch.setattr(ia, "_call_gemini", chamar)
    assert ia.analyze_asset(**dados)["vale_operar"]
    assert chamar.call_count == 2 and ia.ultimo_erro is None
    ai_analyzer.time.sleep.assert_called_once_with(2)


def test_nemotron_schema_invalido_faz_fallback(ia, dados, resposta, monkeypatch):
    ia.CARLOS = "fake"
    monkeypatch.setattr(ia, "_call_nemotron", Mock(return_value={"foo": 1}))
    monkeypatch.setattr(ia, "_call_gemini", Mock(return_value=resposta))
    assert ia.analyze_asset(**dados)
    assert ia.ultimo_erro_nemotron and ia.ultimo_erro is None
    assert ia.ultimo_provedor == "gemini"


def test_nemotron_sem_gemini(ia, dados, resposta, monkeypatch):
    ia.api_key = ""
    ia.CARLOS = "fake"
    monkeypatch.setattr(ia, "_call_nemotron", Mock(return_value=resposta))
    assert ia.is_available() and ia.analyze_asset(**dados)
    ia._get_client.assert_not_called()
    assert ia.ultimo_provedor == "nemotron"


def test_sem_chaves(dados):
    ia = AIAnalyzer(" ", CARLOS=" ")
    assert not ia.is_available()
    assert ia.analyze_asset(**dados) is None
    assert ia.ultimo_erro


@pytest.mark.parametrize("livre", [False, True])
def test_fallback_404_mesmo_com_uma_tentativa(ia, dados, resposta, monkeypatch, livre):
    ia.max_retries = 1
    erro = RuntimeError("NOT_FOUND")
    erro.code = 404
    chamar = Mock(side_effect=[erro, erro, resposta])
    monkeypatch.setattr(ia, "_call_gemini", chamar)
    result = ia.analisar_prompt("teste")[0] if livre else ia.analyze_asset(**dados)
    assert result
    assert [c.kwargs["modelo"] for c in chamar.call_args_list] == [ia.model, *ia.MODELOS_FALLBACK]
    ai_analyzer.time.sleep.assert_not_called()


@pytest.mark.parametrize("codigo,quantidade", [(400, 1), (401, 1), (403, 1), (429, 3), (500, 3), (404, 3)])
def test_falhas_limitadas_sem_sleep_final(ia, dados, monkeypatch, codigo, quantidade):
    erro = RuntimeError("Please retry in 120s")
    erro.status_code = codigo
    chamar = Mock(side_effect=erro)
    monkeypatch.setattr(ia, "_call_gemini", chamar)
    assert ia.analyze_asset(**dados) is None
    assert chamar.call_count == quantidade and ia.ultimo_erro
    assert ai_analyzer.time.sleep.call_count == (2 if codigo in (429, 500) else 0)
    if codigo == 429:
        assert all(c.args == (65,) for c in ai_analyzer.time.sleep.call_args_list)


def test_sdk_gemini_timeout_e_json(monkeypatch, resposta):
    from google import genai
    from google.genai import types
    cliente = Mock()
    cliente.models.generate_content.return_value = SimpleNamespace(text=json.dumps(resposta))
    criar = Mock(return_value=cliente)
    monkeypatch.setattr(genai, "Client", criar)
    ia = AIAnalyzer("fake", model="modelo-configurado", timeout_seconds=12)
    assert ia._call_gemini(ia._get_client(), "teste") == resposta
    opcoes = types.HttpOptions(**criar.call_args.kwargs["http_options"])
    assert opcoes.timeout == 12000 and opcoes.retry_options.attempts == 1
    assert cliente.models.generate_content.call_args.kwargs["model"] == "modelo-configurado"
    assert ia._get_client() is cliente
    criar.assert_called_once()


@pytest.mark.parametrize("conteudo", ["", "[]", '{"a":1}'])
def test_sdk_nemotron_diagnostico(monkeypatch, conteudo):
    import openai
    cliente = Mock()
    cliente.chat.completions.create.return_value = SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(content=conteudo))])
    criar = Mock(return_value=cliente)
    monkeypatch.setattr(openai, "OpenAI", criar)
    ia = AIAnalyzer("", CARLOS="fake", CARLOS_model="modelo-configurado")
    r = ia._call_nemotron("teste")
    assert bool(r) is (conteudo == '{"a":1}')
    if r is None:
        assert ia.ultimo_erro_nemotron
    assert criar.call_args.kwargs["max_retries"] == 0
    assert cliente.chat.completions.create.call_args.kwargs["model"] == "modelo-configurado"


def test_grafico_mockado_e_falha_visual_nao_bloqueia_texto(monkeypatch, resposta):
    cliente = Mock()
    cliente.models.generate_content.return_value = SimpleNamespace(text="Tendencia visivel")
    ia = AIAnalyzer("fake", model="modelo-configurado", CARLOS="fake")
    ia._client = cliente
    caminho = Mock()
    caminho.exists.return_value = True
    caminho.read_bytes.return_value = b"imagem-simulada"
    monkeypatch.setattr(ai_analyzer, "Path", Mock(return_value=caminho))
    assert ia._descrever_grafico_gemini("grafico.png") == "Tendencia visivel"
    assert cliente.models.generate_content.call_args.kwargs["model"] == "modelo-configurado"
    cliente.models.generate_content.return_value = SimpleNamespace(text=json.dumps(resposta))
    assert ia._call_gemini(cliente, "teste", "grafico.png") == resposta
    partes = cliente.models.generate_content.call_args.kwargs["contents"][0].parts
    assert len(partes) == 2
    cliente.models.generate_content.side_effect = RuntimeError("NOT_FOUND")
    assert ia._descrever_grafico_gemini("grafico.png") == ""
    caminho.exists.return_value = False
    assert ia._descrever_grafico_gemini("ausente.png") == ""


@pytest.mark.parametrize("texto,esperado", [("retryDelay: '12s'", 12),
    ("Please retry in 0.5s", 0.5), ("retry in ...s", None), ("erro", None)])
def test_delay_retry(texto, esperado):
    assert AIAnalyzer._extrair_delay_retry(RuntimeError(texto)) == esperado


@pytest.mark.parametrize("titulo,categoria", [
    ("Empresa tem confusao interna", None), ("Empresa sofre difusao de boatos", None),
    ("Empresa anuncia fusao", "positivas"), ("Empresa nega fraude", "neutralizadas"),
    ("Nega fraude: empresa se manifesta", "neutralizadas"),
    ("Empresa nega fraude, mas registra prejuizo", "alertas"),
    ("Empresa nega venda e sofre investigacao", "alertas"),
    ("Empresa nega fraude e anuncia novo contrato", "neutralizadas"),
    ("Empresa nao confirma novo contrato", None),
    ("Empresa sofre fraude e anuncia expansao", "alertas"),
    ("Empresa nega fraude; nova fraude e descoberta", "alertas"),
    ("Empresa nao descarta fraude", "alertas"),
    ("Empresa nao nega fraude", "alertas"),
    ("Empresa sofre fraudes e acidentes", "alertas"),
    ("Empresa entra em recuperacao judicial", "alertas"),
])
def test_noticias_palavras_e_negacao_local(titulo, categoria):
    r = noticias.classificar_noticias([{"titulo": titulo}])
    for nome in ("alertas", "positivas", "neutralizadas"):
        assert bool(r[nome]) is (nome == categoria)


def test_noticias_entradas_invalidas():
    r = noticias.classificar_noticias([None, {}, {"titulo": None}, {"titulo": 1}, {"titulo": ""}])
    assert r["total_analisado"] == 0


def test_rss_timeout_e_erro_nao_parece_sem_risco(monkeypatch):
    xml = b'<rss version="2.0"><channel><title>News</title><item><title>Empresa sofre fraude</title></item></channel></rss>'
    resposta = Mock(content=xml)
    chamada = Mock(return_value=resposta)
    monkeypatch.setattr(noticias.requests, "get", chamada)
    r = noticias.checar_risco_noticias("Empresa & Cia")
    assert r["bloquear_entrada"] and r["noticias"][0]["link"] == ""
    assert chamada.call_args.kwargs["timeout"] == 15
    assert "Empresa%20%26%20Cia" in chamada.call_args.args[0]
    resposta.content = b"<rss>malformado"
    with pytest.raises(ValueError, match="Feed"):
        noticias.buscar_noticias("Empresa")
    assert noticias.buscar_noticias("Empresa", 0) == []


@pytest.fixture
def calendario_fake(monkeypatch):
    import yfinance

    class Relogio(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 8, 23, 30, tzinfo=tz)

    monkeypatch.setattr(calendario, "datetime", Relogio)
    ticker = Mock()
    monkeypatch.setattr(yfinance, "Ticker", Mock(return_value=ticker))
    return ticker


@pytest.mark.parametrize("data,proximo,dias", [
    ("2026-09-08", True, 0), ("2026-09-13", True, 5), ("2026-09-14", False, 6),
    ("2026-09-09T01:00:00+00:00", True, 0),
])
def test_calendario_fuso_e_limites(calendario_fake, data, proximo, dias):
    calendario_fake.get_earnings_dates.return_value = pd.DataFrame({"x": [1]}, index=[data])
    r = calendario.checar_resultado_proximo(" petr4.sa ")
    assert r["tem_resultado_proximo"] is proximo
    assert r["dias_ate_resultado"] == dias and r["info_disponivel"]


@pytest.mark.parametrize("indices", [["2020-01-01"], [pd.NaT], ["errado"], [123], []])
def test_calendario_sem_agenda_futura_nao_confirma_ausencia(calendario_fake, indices):
    calendario_fake.get_earnings_dates.return_value = pd.DataFrame({"x": [1] * len(indices)}, index=indices)
    r = calendario.checar_resultado_proximo("PETR4")
    assert not r["info_disponivel"] and not r["tem_resultado_proximo"]


def test_calendario_nao_perde_evento_por_linha_invalida(calendario_fake):
    calendario_fake.get_earnings_dates.return_value = pd.DataFrame({"x": [1] * 4},
        index=["invalida", "2026-10-01", "2026-09-10", pd.NaT])
    assert calendario.checar_resultado_proximo("PETR4")["dias_ate_resultado"] == 2
    calendario_fake.get_earnings_dates.side_effect = RuntimeError("offline")
    r = calendario.checar_resultado_proximo("PETR4")
    assert not r["info_disponivel"] and not r["tem_resultado_proximo"]


@pytest.mark.parametrize("valor", [-1, True, 1.5, "5"])
def test_calendario_parametro_invalido(valor):
    with pytest.raises(ValueError):
        calendario.checar_resultado_proximo("PETR4", valor)


@pytest.mark.parametrize("valor", ["", "abc", "0", "-1", "NaN", "1.5"])
def test_config_invalida_nao_derruba_import(monkeypatch, valor):
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", valor)
    monkeypatch.setenv("GEMINI_MAX_RETRIES", valor)
    monkeypatch.setenv("GEMINI_MODEL", " ")
    cfg = runpy.run_path(str(Path(ai_analyzer.__file__).with_name("config.py")))
    assert cfg["GEMINI_TIMEOUT_SECONDS"] == 45 and cfg["GEMINI_MAX_RETRIES"] == 3
    assert cfg["GEMINI_MODEL"] == AIAnalyzer.DEFAULT_MODEL


def test_config_preserva_modelos_explicitos(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", " personalizado ")
    monkeypatch.setenv("CARLOS_model", " outro ")
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "1")
    cfg = runpy.run_path(str(Path(ai_analyzer.__file__).with_name("config.py")))
    assert cfg["GEMINI_MODEL"] == "personalizado" and cfg["CARLOS_model"] == "outro"
    assert cfg["GEMINI_TIMEOUT_SECONDS"] == 12 and cfg["GEMINI_MAX_RETRIES"] == 1


@pytest.mark.parametrize("kwargs", [{"max_retries": 0}, {"max_retries": True},
    {"max_retries": 1.5}, {"timeout_seconds": 0}, {"timeout_seconds": float("inf")}])
def test_construtor_rejeita_limites_invalidos(kwargs):
    with pytest.raises(ValueError):
        AIAnalyzer("fake", **kwargs)
