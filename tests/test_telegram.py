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
    assert "/posicoes" in resposta


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
