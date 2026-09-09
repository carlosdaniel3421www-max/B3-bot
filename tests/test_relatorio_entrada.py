"""Fluxo real do relatorio com IO isolado e servicos externos mockados."""
from datetime import date, timedelta
from unittest.mock import Mock

import pandas as pd
import pytest

import diario_sinais
import fonte_opcoes
import posicoes
import relatorio_diario as rd
import trava
from estado import carregar_estado, salvar_estado


@pytest.fixture
def ambiente(monkeypatch, tmp_path):
    monkeypatch.setattr(rd.config, "EXIGIR_SETUP", False)
    monkeypatch.chdir(tmp_path)
    # Impede inclusive sincronizacao de propostas por commit via API GitHub.
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("Sem rede")))
    monkeypatch.setattr("socket.create_connection", Mock(side_effect=AssertionError("Sem rede")))
    monkeypatch.setattr(posicoes, "_sincronizar_github", Mock())
    monkeypatch.setattr(rd, "validar_configuracao", Mock())
    monkeypatch.setattr(rd.config, "WATCHLIST", [])
    monkeypatch.setattr(rd, "avaliar_regime_ibov", Mock(return_value={"regime": "indisponivel"}))
    monkeypatch.setattr(rd, "plotar_grafico", Mock())
    monkeypatch.setattr(rd, "montar_gestao_posicoes", Mock(return_value=""))
    monkeypatch.setattr(rd, "enviar_album", Mock())
    monkeypatch.setattr(rd, "enviar_mensagem", Mock())
    monkeypatch.setattr(rd.time, "sleep", Mock())
    monkeypatch.setattr(rd, "checar_risco_noticias", Mock(return_value={
        "bloquear_entrada": False, "noticias": [{"titulo": "Noticia atual"}],
    }))
    monkeypatch.setattr(rd, "checar_resultado_proximo", Mock(return_value={"tem_resultado_proximo": False}))
    monkeypatch.setattr(rd, "sugerir_stop_alvo", Mock(return_value={
        "preco_entrada": 10, "stop": 9, "alvo": 12,
    }))
    monkeypatch.setattr(rd, "sugerir_parametros_opcao_com_preco", Mock(return_value={
        "tipo_opcao": "CALL", "strike_sugerido_aprox": 10,
        "vencimento_sugerido": "2026-10-16", "premio": 0.5,
    }))
    monkeypatch.setattr(rd, "calcular_tamanho_posicao", Mock(return_value={
        "quantidade_acoes": 100, "valor_posicao": 1000,
        "valor_em_risco": 100, "pct_capital_em_risco": 1,
    }))
    monkeypatch.setattr(diario_sinais, "registrar_sinal", Mock())
    monkeypatch.setattr(diario_sinais, "atualizar_resultados", Mock())
    analisador = Mock(ultimo_provedor="gemini", ultimo_erro_nemotron=None)
    analisador.format_telegram_message.return_value = "Opiniao"
    analisador._call_nemotron.return_value = {"fazer_trava": True}
    monkeypatch.setattr(rd, "_montar_analisador_ia", Mock(return_value=analisador))
    monkeypatch.setattr(fonte_opcoes, "buscar_cadeia_estruturada", Mock(return_value={}))
    monkeypatch.setattr(trava, "montar_trava", Mock(return_value={}))
    monkeypatch.setattr(trava, "formatar_trava", Mock(return_value="Estrutura"))

    def executar(score, direcao="compra", anteriores=(9, 9), nivel_detalhe=6):
        salvar_estado({"PETR4": {
            "score_history": [{"score": s, "direcao": "compra"} for s in anteriores],
            "ultima_data_score": (date.today() - timedelta(days=1)).isoformat(),
        }})
        posicoes.salvar_propostas({"PETR4": {"antiga": True}, "OUTRO": {"intacta": True}})
        resultado = {
            "ticker": "PETR4", "score": score, "direcao": direcao,
            "preco": 10, "motivos": ["Filtro atual preservado"],
            "df": pd.DataFrame([{
                "ema21": 10, "ema200": 9, "rsi": 60, "macd": 0.1,
                "volume": 1000, "atr": 0.3, "suporte": 9, "resistencia": 12,
            }]),
        }
        monkeypatch.setattr(rd, "rodar_screener", Mock(return_value=[resultado]))
        rd.gerar_e_enviar_relatorio(watchlist=["PETR4"], nivel_detalhe=nivel_detalhe)
        mensagem = "\n".join(c.args[2] for c in rd.enviar_mensagem.call_args_list)
        return resultado, mensagem, analisador

    return executar


@pytest.mark.parametrize("score,direcao,anteriores,final", [
    (5, "venda", (9, 9), 5),
    (7, "compra", (9, 9), 7),
    (6, "compra", (9, 9), 6),
    (9, "compra", (6, 6), 7),
    (9, "neutro", (9, 9), 9),
])
def test_bloqueado_nao_propoe_nem_aciona_consumidores(ambiente, score, direcao, anteriores, final):
    resultado, mensagem, analisador = ambiente(score, direcao, anteriores)
    assert resultado["score"] == final
    assert resultado["score_bruto"] == score
    assert resultado["entrada_permitida"] is False
    assert resultado["motivo_bloqueio"]
    assert posicoes.carregar_propostas() == {"OUTRO": {"intacta": True}}
    diario_sinais.registrar_sinal.assert_not_called()
    analisador.analyze_asset.assert_not_called()
    fonte_opcoes.buscar_cadeia_estruturada.assert_not_called()
    assert "<b>ENTRAR" not in mensagem
    assert "/registrar PETR4" not in mensagem
    assert "Filtro atual preservado" in mensagem
    if direcao != "neutro" and final >= 6:
        for detalhe in ("AGUARDAR", "<b>Stop</b>", "<b>Alvo</b>", "<b>Tamanho:</b>", "<b>Op\u00e7\u00e3o:</b>"):
            assert detalhe in mensagem
    historico = carregar_estado()["PETR4"]["score_history"]
    assert historico[-1] == {"score": score, "direcao": direcao}


@pytest.mark.parametrize("cancelamento", ["noticia", "calendario"])
@pytest.mark.parametrize("nivel_detalhe", [6, 10])
def test_cancelamento_compartilhado(ambiente, cancelamento, nivel_detalhe):
    if cancelamento == "noticia":
        rd.checar_risco_noticias.return_value = {
            "bloquear_entrada": True, "alertas": [{"motivo": "Fraude <grave>"}],
        }
        motivo = "Fraude <grave>"
    else:
        rd.checar_resultado_proximo.return_value = {
            "tem_resultado_proximo": True, "dias_ate_resultado": 2,
            "data_resultado": "2026-09-10",
        }
        motivo = "resultado trimestral"
    resultado, mensagem, analisador = ambiente(9, nivel_detalhe=nivel_detalhe)
    assert resultado["score"] == resultado["score_bruto"] == 9
    assert resultado["entrada_permitida"] is False
    assert motivo in resultado["motivo_bloqueio"]
    assert resultado["veredito"]["veredito"] == "EVITAR"
    assert "<b>EVITAR:</b> PETR4" in mensagem
    assert "CANCELADO" in mensagem
    assert "<b>ENTRAR" not in mensagem
    assert "/registrar PETR4" not in mensagem
    if cancelamento == "noticia":
        assert "Fraude &lt;grave&gt;" in mensagem
    assert posicoes.carregar_propostas() == {"OUTRO": {"intacta": True}}
    rd.sugerir_stop_alvo.assert_not_called()
    diario_sinais.registrar_sinal.assert_not_called()
    analisador.analyze_asset.assert_not_called()
    fonte_opcoes.buscar_cadeia_estruturada.assert_not_called()


def test_entrada_liberada_preserva_plano_e_consumidores(ambiente):
    resultado, mensagem, analisador = ambiente(9, anteriores=(7, 9))
    assert resultado["score_bruto"] == 9
    assert resultado["score"] == 8
    assert resultado["entrada_permitida"] is True
    assert resultado["motivo_bloqueio"] == ""
    assert "<b>ENTRAR:</b> PETR4" in mensagem
    assert "/registrar PETR4" in mensagem
    propostas = posicoes.carregar_propostas()
    assert propostas["PETR4"]["stop"] == 9
    assert propostas["OUTRO"] == {"intacta": True}
    diario_sinais.registrar_sinal.assert_called_once_with("PETR4", "compra", 8, 10)
    assert analisador.analyze_asset.call_args.kwargs["score"] == 8
    assert analisador.analyze_asset.call_args.kwargs["news"] == [{"titulo": "Noticia atual"}]
    rd.checar_risco_noticias.assert_called_once()
    fonte_opcoes.buscar_cadeia_estruturada.assert_called_once_with("PETR4")


def test_diario_nao_repete_screener_e_avisa_ibov_ausente(ambiente):
    _, mensagem, _ = ambiente(7)
    rd.rodar_screener.assert_called_once()
    diario_sinais.atualizar_resultados.assert_called_once_with({})
    assert "filtro de mercado nao aplicado" in mensagem


def test_reexecucao_mesmo_dia_atualiza_score_e_remove_proposta(ambiente):
    resultado, _, analisador = ambiente(9)
    resultado["score"] = 5
    resultado["direcao"] = "venda"
    diario_sinais.registrar_sinal.reset_mock()
    analisador.analyze_asset.reset_mock()
    fonte_opcoes.buscar_cadeia_estruturada.reset_mock()
    rd.gerar_e_enviar_relatorio(watchlist=["PETR4"], nivel_detalhe=6)
    assert resultado["score"] == resultado["score_bruto"] == 5
    historico = carregar_estado()["PETR4"]["score_history"]
    assert len(historico) == 3
    assert historico[-1] == {"score": 5, "direcao": "venda"}
    assert posicoes.carregar_propostas() == {"OUTRO": {"intacta": True}}
    diario_sinais.registrar_sinal.assert_not_called()
    analisador.analyze_asset.assert_not_called()
    fonte_opcoes.buscar_cadeia_estruturada.assert_not_called()
