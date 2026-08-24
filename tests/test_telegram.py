# -*- coding: utf-8 -*-
"""Testes do parser de comandos do Telegram (sem rede)."""
from unittest.mock import patch
from telegram_bot import processar_comando


def test_analisar_posicoes_sem_posicoes():
    with patch("telegram_bot.carregar_posicoes", return_value={}):
        resposta = processar_comando("fake", 1, "/analisar_posicoes")
        assert "Nenhuma posição" in resposta


def test_analisar_posicoes_sem_ia():
    posicoes = {
        "PETR4": {
            "ticker": "PETR4", "direcao": "compra",
            "preco_entrada": 43.11, "stop": 40.5, "alvo": 48.22,
            "quantidade": 100, "data_entrada": "2026-08-20", "prazo_maximo_dias": 20,
        }
    }
    with patch("telegram_bot.carregar_posicoes", return_value=posicoes):
        with patch("telegram_bot._precos_posicoes", return_value={"PETR4": 42.0}):
            with patch("telegram_bot._montar_analisador_ia", return_value=None):
                resposta = processar_comando("fake", 1, "/analisar_posicoes")
                assert "IA não configurada" in resposta


def test_analisar_posicoes_com_ia():
    posicoes = {
        "LREN3": {
            "ticker": "LREN3", "direcao": "venda", "tipo_operacao": "trava",
            "strike_comprado": 9.67, "strike_vendido": 8.47,
            "premio_comprado": 0.29, "premio_vendido": 0.08,
            "preco_entrada": 0.21, "stop": 0.10, "alvo": 0.42,
            "quantidade": 100, "vencimento": "2026-10-16",
            "data_entrada": "2026-08-24", "prazo_maximo_dias": 20,
        }
    }
    # Mock analisador
    analisador_mock = type("Analisador", (), {
        "_call_nemotron": lambda self, p: {"analises": [
            {"ticker": "LREN3", "acao": "manter", "explicacao": "dentro do plano",
             "risco": "liquidez"},
        ]},
        "_call_gemini": lambda self, c, p, i, modelo=None: None,
        "_get_client": lambda self: None,
        "model": "x",
    })()
    with patch("telegram_bot.carregar_posicoes", return_value=posicoes):
        with patch("telegram_bot._precos_posicoes", return_value={"LREN3": 10.83}):
            with patch("telegram_bot._montar_analisador_ia", return_value=analisador_mock):
                resposta = processar_comando("fake", 1, "/analisar_posicoes")
                assert "Análise das posições" in resposta
                assert "LREN3" in resposta
                assert "MANTER" in resposta


def test_comando_nao_reconhecido():
    resposta = processar_comando("fake", 1, "/naoexiste")
    assert resposta is None



def test_ajuda_lista_comandos():
    resposta = processar_comando("fake", 1, "/ajuda")
    assert "/registrar" in resposta
    assert "/remover" in resposta


def test_relatorio_sem_token():
    resposta = processar_comando("fake", 1, "/relatorio")
    assert "GITHUB_TOKEN" in resposta
    assert "não configurado" in resposta


def test_relatorio_com_token():
    with patch("telegram_bot.getattr") as mock_getattr:
        # Simula GITHUB_TOKEN configurado + requests.post mockado
        with patch("telegram_bot.requests.post") as mock_post:
            mock_post.return_value.status_code = 204
            # Override do getattr para retornar token
            original = __import__('telegram_bot').__dict__.copy()
            import telegram_bot as tb
            # Mock direto: o getattr do config precisa retornar o token
            with patch.object(tb.config, 'GITHUB_TOKEN', 'fake_token'):
                resposta = tb.processar_comando("fake", 1, "/relatorio")
    assert "Relatório acionado" in resposta


def test_registrar_sem_argumentos():
    resposta = processar_comando("fake", 1, "/registrar")
    assert "Uso:" in resposta


def test_registrar_manual_valores_invalidos():
    resposta = processar_comando("fake", 1, "/registrar PETR4 compra abc xyz 123")
    assert resposta is not None


def test_registrar_manual_sucesso():
    with patch("telegram_bot.adicionar_posicao") as mock_add:
        mock_add.return_value = {
            "ticker": "PETR4", "direcao": "compra",
            "preco_entrada": 43.11, "stop": 40.50, "alvo": 48.22,
        }
        resposta = processar_comando("fake", 1, "/registrar PETR4 compra 43.11 40.50 48.22")
        assert "PETR4" in resposta
        assert "registrada" in resposta.lower()
        mock_add.assert_called_once()


def test_registrar_pela_proposta():
    with patch("telegram_bot.registrar_da_proposta") as mock_reg:
        mock_reg.return_value = ({"ticker": "VALE3"}, "ok")
        resposta = processar_comando("fake", 1, "/registrar VALE3")
        assert resposta == "ok"
        mock_reg.assert_called_once_with("VALE3", quantidade=0)


def test_remover_sem_argumentos():
    resposta = processar_comando("fake", 1, "/remover")
    assert "Uso:" in resposta


def test_remover_sucesso():
    with patch("telegram_bot.remover_posicao") as mock_rem:
        mock_rem.return_value = True
        resposta = processar_comando("fake", 1, "/remover PETR4")
        assert "removida" in resposta


def test_remover_nao_encontrada():
    with patch("telegram_bot.remover_posicao") as mock_rem:
        mock_rem.return_value = False
        resposta = processar_comando("fake", 1, "/remover PETR4")
        assert "não está registrada" in resposta


def test_status_sem_argumentos():
    resposta = processar_comando("fake", 1, "/status")
    assert "Uso:" in resposta


def test_propostas_vazio():
    with patch("telegram_bot.carregar_propostas") as mock_prop:
        mock_prop.return_value = {}
        resposta = processar_comando("fake", 1, "/propostas")
        assert "Nenhuma proposta" in resposta


def test_posicoes_vazio():
    with patch("telegram_bot.carregar_posicoes") as mock_pos:
        mock_pos.return_value = {}
        resposta = processar_comando("fake", 1, "/posicoes")
        assert "Nenhuma posição aberta" in resposta


def test_trava_registrar_sem_argumentos():
    resposta = processar_comando("fake", 1, "/trava_registrar")
    assert "Uso:" in resposta


def test_trava_registrar_sucesso():
    with patch("telegram_bot.adicionar_trava") as mock_add:
        mock_add.return_value = {
            "ticker": "CMIG4", "direcao": "compra",
            "strike_comprado": 10.86, "strike_vendido": 11.56,
            "premio_comprado": 0.22, "premio_vendido": 0.09,
            "preco_entrada": 0.13, "stop": 0.065, "alvo": 0.45,
        }
        resposta = processar_comando(
            "fake", 1,
            "/trava_registrar CMIG4 compra 10.86 0.22 11.56 0.09 0.065 0.45",
        )
        assert "TRAVA registrada" in resposta
        assert "CMIG4" in resposta
        mock_add.assert_called_once()


def test_trava_registrar_erro():
    with patch("telegram_bot.adicionar_trava", side_effect=ValueError("Stop deve ser MENOR")):
        resposta = processar_comando(
            "fake", 1,
            "/trava_registrar CMIG4 compra 10.86 0.22 11.56 0.09 0.065 0.45",
        )
        assert "Stop" in resposta


def test_trava_registrar_com_vencimento():
    with patch("telegram_bot.adicionar_trava") as mock_add:
        mock_add.return_value = {
            "ticker": "CMIG4", "direcao": "compra",
            "strike_comprado": 10.86, "strike_vendido": 11.56,
            "premio_comprado": 0.22, "premio_vendido": 0.09,
            "preco_entrada": 0.13, "stop": 0.065, "alvo": 0.45,
        }
        resposta = processar_comando(
            "fake", 1,
            "/trava_registrar CMIG4 compra 10.86 0.22 11.56 0.09 0.065 0.45 2026-10-16",
        )
        assert "TRAVA registrada" in resposta
        # Verifica que o vencimento foi passado corretamente
        args_chamada = mock_add.call_args
        assert args_chamada.kwargs.get("vencimento") == "2026-10-16"


def test_trava_registrar_valor_invalido():
    resposta = processar_comando(
        "fake", 1,
        "/trava_registrar CMIG4 compra 10.86 abc 11.56 0.09 0.065 0.45",
    )
    assert "Valor inválido" in resposta


def test_sanitizar_html_escapa_menores_maiores():
    from servidor_api import _sanitizar_html
    assert _sanitizar_html("a < b > c") == "a &lt; b &gt; c"


def test_sanitizar_html_preserva_tags_permitidas():
    from servidor_api import _sanitizar_html
    assert _sanitizar_html("<b>CMIG4</b> ok") == "<b>CMIG4</b> ok"
    assert _sanitizar_html("Trava <b>10.86</b> < 9.0") == "Trava <b>10.86</b> &lt; 9.0"


def test_sanitizar_html_vazio():
    from servidor_api import _sanitizar_html
    assert _sanitizar_html("") == ""
    assert _sanitizar_html(None) is None


def test_webhook_erro_processamento_nao_fica_silencioso():
    from unittest.mock import patch, MagicMock
    import servidor_api as sa

    update = {"message": {"chat": {"id": "1"}, "text": "/relatorio"}}
    with patch.object(sa, "CHAT_ID_AUTORIZADO", "1"):
        with patch.object(sa, "processar_comando", side_effect=RuntimeError("boom")):
            with patch.object(sa, "_responder_telegram") as mock_responder:
                with sa.app.test_request_context("/webhook", method="POST", json=update):
                    resp = sa.webhook()
                    assert resp.status_code == 200
                    mock_responder.assert_called_once()
                    texto = mock_responder.call_args[0][1]
                    assert "Erro interno" in texto
