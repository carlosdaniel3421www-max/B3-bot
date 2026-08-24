# -*- coding: utf-8 -*-
"""Testes do parser de comandos do Telegram (sem rede)."""
from unittest.mock import patch
from telegram_bot import processar_comando


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
