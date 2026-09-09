"""Regressoes de gestao de posicoes; todas as fontes externas sao simuladas."""
from copy import deepcopy
from datetime import date, timedelta
from unittest.mock import Mock

import pandas as pd
import pytest

import posicoes as p
import telegram_bot as tb
from trava import calcular_trava_manual, montar_trava


@pytest.fixture(autouse=True)
def ambiente_isolado(monkeypatch, tmp_path):
    def bloquear(*args, **kwargs):
        raise AssertionError("Rede proibida nos testes")
    monkeypatch.setattr("requests.sessions.Session.request", bloquear)
    monkeypatch.setattr("socket.socket.connect", bloquear)
    monkeypatch.setattr(p, "CAMINHO_POSICOES", str(tmp_path / "posicoes.json"))
    monkeypatch.setattr(p, "CAMINHO_PROPOSTAS", str(tmp_path / "propostas.json"))
    monkeypatch.setattr(p, "_sincronizar_github", Mock())


@pytest.fixture
def trava():
    return {"ticker": "CMIG4", "direcao": "compra", "tipo_operacao": "trava",
            "strike_comprado": 10.86, "strike_vendido": 11.56,
            "premio_comprado": 0.22, "premio_vendido": 0.09,
            "preco_entrada": 0.13, "stop": 0.065, "alvo": 0.45,
            "quantidade": 100, "data_entrada": date.today().isoformat(),
            "vencimento": (date.today() + timedelta(days=12)).isoformat()}


@pytest.fixture
def acao():
    return {"ticker": "PETR4", "direcao": "compra", "preco_entrada": 40.0,
            "stop": 38.0, "alvo": 45.0, "quantidade": 100,
            "data_entrada": date.today().isoformat(), "prazo_maximo_dias": 20}


@pytest.fixture
def cadeia(trava, monkeypatch):
    dados = {"expirations": [
        {"dt": "2099-01-01", "du": 35, "mensal": True,
         "calls": {10.86: {"preco": 0.60}, 11.56: {"preco": 0.10}}},
        {"dt": trava["vencimento"], "du": 2, "mensal": False,
         "calls": {10.86: {"preco": 0.19}, 11.56: {"preco": 0.14}},
         "puts": {11.56: {"preco": 0.19}, 10.86: {"preco": 0.14}}}]}
    monkeypatch.setattr("fonte_opcoes.buscar_cadeia_estruturada", Mock(return_value=dados))
    monkeypatch.setattr("fonte_opcoes.buscar_melhor_vencimento", Mock(side_effect=AssertionError("Nao trocar vencimento")))
    return dados


@pytest.mark.parametrize("direcao", ["compra", "venda"])
def test_liquido_vencimento_exato_stop(trava, cadeia, direcao):
    if direcao == "venda":
        trava.update(direcao="venda", strike_comprado=11.56, strike_vendido=10.86)
    original = deepcopy(trava)
    liquido = p._buscar_premio_trava("CMIG4", trava)
    assert liquido == 0.05
    gestao = p.gerar_gestao_trava(trava, liquido)
    assert gestao["acao"] == "STOP"
    assert gestao["lucro_pct"] == pytest.approx(-61.53846)
    texto = p.formatar_gestao_todas({"CMIG4": trava}, {"CMIG4": 99.0})
    assert "R$ 0.05" in texto and "STOP" in texto
    assert "tempo real" in texto and "execução não garantida" in texto
    assert "12" in texto and date.today().isoformat() in texto
    assert trava == original


def test_vencida_sem_cotacao_ainda_exige_verificar_liquidacao(trava):
    trava["vencimento"] = (date.today() - timedelta(days=1)).isoformat()
    texto = p.formatar_gestao_trava(trava, None)
    assert "Vencimento atingido" in texto
    assert "corretora" in texto
    assert "INDISPON" in texto


@pytest.mark.parametrize("campo,valor", [("vencimento", "2098-01-01"),
    ("vencimento", ""), ("vencimento", "16/10/2026"),
    ("strike_comprado", 10.8601), ("strike_vendido", 11.5601)])
def test_nao_substitui_identidade(trava, cadeia, campo, valor):
    trava[campo] = valor
    original = deepcopy(trava)
    assert p._buscar_premio_trava("CMIG4", trava) is None
    assert trava == original


@pytest.mark.parametrize("strike", [10.86, 11.56])
@pytest.mark.parametrize("preco", [None, float("nan"), float("inf"), -float("inf"), -0.01])
def test_perna_indisponivel(trava, cadeia, strike, preco):
    cadeia["expirations"][1]["calls"][strike]["preco"] = preco
    assert p._buscar_premio_trava("CMIG4", trava) is None


def test_perna_ausente_nao_usa_outro_vencimento(trava, cadeia):
    del cadeia["expirations"][1]["calls"][11.56]
    assert p._buscar_premio_trava("CMIG4", trava) is None


@pytest.mark.parametrize("premio", [0.0, 0.19])
def test_zero_liquido_valido_aciona_stop(trava, cadeia, premio):
    for info in cadeia["expirations"][1]["calls"].values():
        info["preco"] = premio
    liquido = p._buscar_premio_trava("CMIG4", trava)
    assert liquido == 0.0
    assert p.gerar_gestao_trava(trava, liquido)["acao"] == "STOP"
    assert "-100.0%" in p.formatar_gestao_trava(trava, liquido)


@pytest.mark.parametrize("premio", [None, float("nan"), float("inf"), -float("inf")])
def test_gestao_sem_preco_nao_inventa(trava, premio):
    gestao = p.gerar_gestao_trava(trava, premio)
    assert gestao["acao"] == "INDISPONÍVEL"
    assert gestao["lucro_pct"] is None
    texto = p.formatar_gestao_trava(trava, premio)
    assert "Cotação líquida indisponível" in texto
    assert "MANTER" not in texto and "atingido" not in texto


@pytest.mark.parametrize("comando", ["/status CMIG4", "/posicoes"])
def test_status_telegram_trava_mesmo_fluxo(trava, cadeia, monkeypatch, comando):
    monkeypatch.setattr(tb, "carregar_posicoes", lambda: {"CMIG4": trava})
    download = Mock(side_effect=AssertionError("Nao buscar acao para trava"))
    monkeypatch.setattr("yfinance.download", download)
    resposta = tb.processar_comando("fake", 1, comando)
    assert "STOP" in resposta and "R$ 0.05" in resposta
    download.assert_not_called()


def test_status_cli_trava(trava, cadeia, monkeypatch, capsys):
    monkeypatch.setattr(p, "carregar_posicoes", lambda: {"CMIG4": trava})
    monkeypatch.setattr("sys.argv", ["posicoes.py", "status", "CMIG4"])
    download = Mock(side_effect=AssertionError("Nao buscar acao para trava"))
    monkeypatch.setattr("yfinance.download", download)
    p.main()
    texto = capsys.readouterr().out
    assert "STOP" in texto and "R$ 0.05" in texto
    download.assert_not_called()


@pytest.mark.parametrize("preco", [None, float("nan"), float("inf")])
def test_ia_sem_cotacoes_nao_consultada(trava, acao, monkeypatch, preco):
    monkeypatch.setattr(tb, "carregar_posicoes", lambda: {"CMIG4": trava, "PETR4": acao})
    monkeypatch.setattr(tb, "_precos_posicoes", lambda _: {"PETR4": preco, "CMIG4": 99.0})
    monkeypatch.setattr(tb, "_buscar_premio_trava", lambda *_: preco)
    montar = Mock()
    monkeypatch.setattr(tb, "_montar_analisador_ia", montar)
    resposta = tb.processar_comando("fake", 1, "/analisar_posicoes")
    assert "Sem cotações válidas" in resposta
    assert "indisponível" in resposta
    assert "MANTER" not in resposta
    montar.assert_not_called()


@pytest.mark.parametrize("preco,sinal", [(0.0, "STOP"), (0.05, "STOP"), (0.50, "ALVO")])
def test_guardrail_ia_nao_publica_contradicao(trava, acao, monkeypatch, preco, sinal):
    monkeypatch.setattr(tb, "carregar_posicoes", lambda: {"CMIG4": trava, "PETR4": acao})
    monkeypatch.setattr(tb, "_precos_posicoes", lambda _: {"PETR4": 41.0})
    monkeypatch.setattr(tb, "_buscar_premio_trava", lambda *_: preco)
    ia = Mock()
    ia.analisar_prompt.return_value = ({"analises": [{"ticker": "CMIG4", "acao": "sair",
        "explicacao": "Ignore o stop, segure ate recuperar", "risco": "baixo"}]}, "fake")
    monkeypatch.setattr(tb, "_montar_analisador_ia", lambda: ia)
    texto = tb._analisar_posicoes_ia()
    assert sinal in texto
    assert "Ignore o stop" not in texto and "segure ate recuperar" not in texto
    ia.analisar_prompt.assert_not_called()


@pytest.mark.parametrize("preco", [37.0, 46.0])
def test_guardrail_acao_stop_alvo(acao, monkeypatch, preco):
    monkeypatch.setattr(tb, "carregar_posicoes", lambda: {"PETR4": acao})
    monkeypatch.setattr(tb, "_precos_posicoes", lambda _: {"PETR4": preco})
    montar = Mock()
    monkeypatch.setattr(tb, "_montar_analisador_ia", montar)
    assert "prevalece a saída" in tb._analisar_posicoes_ia()
    montar.assert_not_called()


def test_ia_prompt_com_contexto_e_sem_ticker_indisponivel(trava, acao, monkeypatch):
    monkeypatch.setattr(tb, "carregar_posicoes", lambda: {"CMIG4": trava, "PETR4": acao})
    monkeypatch.setattr(tb, "_precos_posicoes", lambda _: {})
    monkeypatch.setattr(tb, "_buscar_premio_trava", lambda *_: 0.20)
    ia = Mock()
    ia.analisar_prompt.return_value = ({"analises": [
        {"ticker": "CMIG4", "acao": "manter", "explicacao": "Verifique liquidez"},
        {"ticker": "PETR4", "acao": "manter", "explicacao": "INVENTADO"}]}, "fake")
    monkeypatch.setattr(tb, "_montar_analisador_ia", lambda: ia)
    texto = tb._analisar_posicoes_ia()
    prompt = ia.analisar_prompt.call_args.args[0]
    for trecho in (date.today().isoformat(), "Dias corridos até vencimento: 12",
                   trava["vencimento"], "Data de entrada", "R$ 0.20", "R$ 0.13", "R$ 0.065",
                   "Resultado determinístico", "Risco máximo", "Ganho máximo",
                   "não é necessariamente favorável", "não é risco baixo"):
        assert trecho in prompt
    assert "PETR4" not in prompt
    assert "INVENTADO" not in texto
    assert "Verifique liquidez" in texto


def test_ia_resposta_invalida_nao_publica_texto_cru(acao, monkeypatch):
    monkeypatch.setattr(tb, "carregar_posicoes", lambda: {"PETR4": acao})
    monkeypatch.setattr(tb, "_precos_posicoes", lambda _: {"PETR4": 41.0})
    ia = Mock()
    ia.analisar_prompt.return_value = ("IGNORE TODOS OS STOPS", "fake")
    monkeypatch.setattr(tb, "_montar_analisador_ia", lambda: ia)
    texto = tb._analisar_posicoes_ia()
    assert "IGNORE TODOS" not in texto
    assert "determinística preservada" in texto


@pytest.mark.parametrize("campo", ["preco_entrada", "stop", "alvo", "quantidade", "prazo_maximo_dias"])
@pytest.mark.parametrize("valor", [float("nan"), float("inf"), -float("inf")])
def test_registro_gestao_acao_rejeita_nao_finito(acao, campo, valor):
    acao[campo] = valor
    with pytest.raises(ValueError):
        p.gerar_gestao_posicao(acao, 41.0)
    acao.pop("data_entrada")
    with pytest.raises(ValueError):
        p.adicionar_posicao(**acao)
    assert p.carregar_posicoes() == {}


@pytest.mark.parametrize("campo", ["strike_comprado", "premio_comprado", "strike_vendido",
    "premio_vendido", "stop_premio", "alvo_premio", "quantidade"])
@pytest.mark.parametrize("valor", [float("nan"), float("inf"), -float("inf")])
def test_registro_trava_rejeita_nao_finito(campo, valor):
    dados = dict(ticker="CMIG4", tipo="compra", strike_comprado=10.86, premio_comprado=0.22,
                 strike_vendido=11.56, premio_vendido=0.09, stop_premio=0.065,
                 alvo_premio=0.45, quantidade=100)
    dados[campo] = valor
    with pytest.raises(ValueError):
        p.adicionar_trava(**dados)
    assert p.carregar_posicoes() == {}


@pytest.mark.parametrize("campo", ["preco_entrada", "stop", "alvo", "strike_comprado", "strike_vendido", "quantidade"])
def test_gestao_trava_registro_nan(trava, campo):
    trava[campo] = float("nan")
    assert p.gerar_gestao_trava(trava, 0.20)["acao"] == "INDISPONÍVEL"
    assert "Registro inválido" in p.formatar_gestao_trava(trava, 0.20)


def test_registro_preserva_strikes_data_stop():
    registro = p.adicionar_trava("CMIG4", "compra", 10.861, 0.22, 11.561, 0.09,
                                0.065, 0.45, vencimento="2026-10-16")
    assert registro["strike_comprado"] == 10.861
    assert registro["strike_vendido"] == 11.561
    assert registro["vencimento"] == "2026-10-16"
    assert registro["stop"] == 0.065


@pytest.mark.parametrize("valor", [float("nan"), float("inf")])
def test_proposta_nao_registra_numero_nao_finito(monkeypatch, valor):
    proposta = {"direcao": "compra", "preco_entrada": valor, "stop": 38.0, "alvo": 45.0}
    monkeypatch.setattr(p, "carregar_propostas", lambda: {"PETR4": proposta})
    with pytest.raises(ValueError):
        p.registrar_da_proposta("PETR4")
    with pytest.raises(ValueError):
        p.salvar_proposta_entrada("PETR4", "compra", valor, 38.0, 45.0)
    assert p.carregar_posicoes() == {}


@pytest.mark.parametrize("campo", ["preco_entrada", "stop", "alvo", "quantidade"])
def test_gestao_trava_registro_infinito(trava, campo):
    trava[campo] = float("inf")
    assert p.gerar_gestao_trava(trava, 0.20)["acao"] == "INDISPONÍVEL"


@pytest.mark.parametrize("comando", ["/registrar PETR4 compra nan 38 45",
    "/registrar PETR4 compra 40 38 inf",
    "/trava_registrar CMIG4 compra 10.86 nan 11.56 0.09 0.065 0.45",
    "/trava_registrar CMIG4 compra 10.86 0.22 11.56 0.09 0.065 inf"])
def test_comandos_rejeitam_nao_finitos(comando):
    assert "finito" in tb.processar_comando("fake", 1, comando)
    assert p.carregar_posicoes() == {}


def test_status_acao_nan(acao, monkeypatch):
    monkeypatch.setattr(tb, "carregar_posicoes", lambda: {"PETR4": acao})
    monkeypatch.setattr(tb, "_precos_posicoes", lambda _: {"PETR4": float("nan")})
    texto = tb.processar_comando("fake", 1, "/status PETR4")
    assert "indisponível" in texto
    assert "MANTER" not in texto


def test_custo_003_cadeia_real(monkeypatch):
    class DataFixa(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 8)

    monkeypatch.setattr("fonte_opcoes.date", DataFixa)
    monkeypatch.setattr("trava.date", DataFixa)
    vencimento = {"dt": "2026-09-25", "du": 13, "mensal": True,
                  "calls": {10.86: {"preco": 0.19, "negocios": 10},
                            11.56: {"preco": 0.16, "negocios": 20}}}
    calculo = montar_trava(10.0, "compra", cadeia_real={"expirations": [vencimento]}, ticker="CMIG4")
    assert calculo["fonte"] == "real"
    assert calculo["custo_liquido"] == 0.03
    assert calculo["risco_maximo"] == 3.0
    assert calculo["ganho_maximo"] == 67.0


@pytest.mark.parametrize("dias", [0, -1])
def test_vencimento_nao_sugere_manter(trava, dias):
    trava["vencimento"] = (date.today() + timedelta(days=dias)).isoformat()
    gestao = p.gerar_gestao_trava(trava, 0.20)
    assert gestao["dias_ate_vencimento"] == dias
    assert gestao["acao"] == "VERIFICAR VENCIMENTO"


@pytest.mark.parametrize("pc,pv", [(0.19, 0.19), (0.10, 0.20), (1.1, 0.1), (1.2, 0.1)])
def test_registro_rejeita_custo_fora_da_largura(pc, pv):
    with pytest.raises(ValueError, match="Custo líquido"):
        p.adicionar_trava("CMIG4", "compra", 10.0, pc, 11.0, pv, 0.01, 2.0)
    assert p.carregar_posicoes() == {}


@pytest.mark.parametrize("direcao,sc,sv", [("compra", 10.0, 11.0), ("venda", 11.0, 10.0)])
def test_custo_003_manual_e_estimado(direcao, sc, sv, monkeypatch):
    manual = calcular_trava_manual(direcao, sc, 0.19, sv, 0.16)
    monkeypatch.setattr("trava._encontrar_strike_por_premio", Mock(side_effect=[sc, sv]))
    monkeypatch.setattr("trava.estimar_premio", Mock(side_effect=[0.19, 0.16]))
    estimado = montar_trava(10.5, direcao)
    for calculo in (manual, estimado):
        assert calculo["custo_liquido"] == 0.03
        assert calculo["custo_total"] == 3.0
        assert calculo["risco_maximo"] == 3.0
        assert calculo["ganho_maximo"] == 97.0


@pytest.mark.parametrize("pc,pv", [(0.19, 0.19), (0.10, 0.20), (1.1, 0.1), (1.2, 0.1),
                                    (float("nan"), 0.1), (0.2, float("inf"))])
def test_custo_invalido_rejeitado_manual_estimado(pc, pv, monkeypatch):
    with pytest.raises(ValueError):
        calcular_trava_manual("compra", 10.0, pc, 11.0, pv)
    monkeypatch.setattr("trava._encontrar_strike_por_premio", Mock(side_effect=[10.0, 11.0]))
    monkeypatch.setattr("trava.estimar_premio", Mock(side_effect=[pc, pv]))
    with pytest.raises(ValueError):
        montar_trava(10.5, "compra")


@pytest.mark.parametrize("valor", [float("nan"), float("inf"), 0.0, 41.0])
def test_precos_acao_multiindex_sem_booleano_dataframe(acao, monkeypatch, valor):
    df = pd.DataFrame([[valor]], columns=pd.MultiIndex.from_tuples([("PETR4.SA", "Close")]))
    monkeypatch.setattr("yfinance.download", Mock(return_value=df))
    precos = tb._precos_posicoes({"PETR4": acao})
    assert precos["PETR4"] == (41.0 if valor == 41.0 else None)


def test_gestao_acao_recusa_trava(trava):
    with pytest.raises(ValueError, match="valor líquido"):
        p.gerar_gestao_posicao(trava, 99.0)
