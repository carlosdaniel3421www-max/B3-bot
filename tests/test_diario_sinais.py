# -*- coding: utf-8 -*-
"""Testes do diário de sinais (sem rede)."""
import os
from datetime import date, timedelta

from diario_sinais import (
    carregar_sinais, salvar_sinais, registrar_sinal,
    avaliar_sinal, atualizar_resultados, resumo_desempenho,
    formatar_resumo_desempenho,
)

CAMINHO_TEMP = "_test_sinais.json"


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


def test_avaliar_sinal_compra_lucro():
    sinal = {"direcao": "compra", "preco": 10.0}
    assert avaliar_sinal(sinal, 11.0) == "lucro"
    assert avaliar_sinal(sinal, 9.0) == "prejuizo"


def test_avaliar_sinal_venda_lucro():
    sinal = {"direcao": "venda", "preco": 10.0}
    assert avaliar_sinal(sinal, 9.0) == "lucro"
    assert avaliar_sinal(sinal, 11.0) == "prejuizo"


def test_avaliar_sinal_direcao_invalida():
    sinal = {"direcao": "neutro", "preco": 10.0}
    assert avaliar_sinal(sinal, 11.0) == "indefinido"


def test_atualizar_resultados_preenche_antigos():
    _limpar()
    # Registra um sinal de 15 dias atrás
    registrar_sinal("PETR4", "compra", 9, 43.11, arquivo=CAMINHO_TEMP)
    sinais = carregar_sinais(CAMINHO_TEMP)
    sinais["PETR4"][-1]["data"] = (date.today() - timedelta(days=15)).isoformat()
    salvar_sinais(sinais, CAMINHO_TEMP)

    # Preço atual acima -> lucro
    sinais = atualizar_resultados({"PETR4": 45.00}, dias_min=10, arquivo=CAMINHO_TEMP)
    assert sinais["PETR4"][0]["resultado"] == "lucro"
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
            {"data": "2026-01-01", "direcao": "compra", "score": 9, "preco": 10, "resultado": "lucro"},
            {"data": "2026-01-02", "direcao": "compra", "score": 8, "preco": 10, "resultado": "prejuizo"},
        ],
        "VALE3": [
            {"data": "2026-01-03", "direcao": "venda", "score": 9, "preco": 10, "resultado": "lucro"},
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
