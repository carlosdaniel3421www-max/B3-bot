# -*- coding: utf-8 -*-
"""Testes do módulo estado (score suavizado, carregamento, etc.)."""
import json
import os
import tempfile
from datetime import date, timedelta
from estado import carregar_estado, salvar_estado, score_suavizado, atualizar_estado


def test_score_suavizado_primeiro_dia():
    estado = {}
    s = score_suavizado(estado, "PETR4", 10, "compra")
    assert s == 10
    assert estado["PETR4"]["score_history"] == [{"score": 10, "direcao": "compra"}]


def _historico(scores, direcao="compra", dias=1):
    return {"PETR4": {
        "score_history": [{"score": s, "direcao": direcao} for s in scores],
        "ultima_data_score": (date.today() - timedelta(days=dias)).isoformat(),
    }}


def test_score_suavizado_segundo_dia():
    estado = _historico([10])
    s = score_suavizado(estado, "PETR4", 4, "compra")
    assert s == 7  # (10 + 4) / 2 = 7
    assert estado == _historico([10, 4], dias=0)


def test_score_suavizado_terceiro_dia():
    estado = _historico([10, 4])
    s = score_suavizado(estado, "PETR4", 4, "compra")
    assert s == 6  # (10 + 4 + 4) / 3 = 6
    assert estado == _historico([10, 4, 4], dias=0)


def test_score_suavizado_nao_repete_mesmo_dia():
    estado = _historico([10], dias=0)
    s = score_suavizado(estado, "PETR4", 4, "compra")
    assert s == 4
    assert estado == _historico([4], dias=0)


def test_score_suavizado_inversao_e_atualizacao_mesmo_dia():
    estado = _historico([9, 9])
    assert score_suavizado(estado, "PETR4", 5, "venda") == 5
    assert score_suavizado(estado, "PETR4", 7, "venda") == 7
    historico = estado["PETR4"]["score_history"]
    assert len(historico) == 3
    assert historico[-1] == {"score": 7, "direcao": "venda"}
    estado["PETR4"]["ultima_data_score"] = "2020-01-01"
    # Nao reutiliza a compra antiga ao voltar a comprar.
    assert score_suavizado(estado, "PETR4", 6, "compra") == 6


def test_score_suavizado_descarta_legado_sem_direcao():
    estado = {"PETR4": {"score_history": [9, 9], "direcao": "compra"}}
    assert score_suavizado(estado, "PETR4", 5, "venda") == 5
    assert estado["PETR4"]["score_history"] == [{"score": 5, "direcao": "venda"}]


def test_score_suavizado_mantem_janela():
    estado = {"PETR4": {"score_history": [], "ultima_data_score": ""}}
    for i in range(1, 6):
        # Dias distintos: 5 dias atrás, 4, 3, 2, 1 (nunca hoje)
        estado["PETR4"]["ultima_data_score"] = (date.today() - timedelta(days=6 - i)).isoformat()
        score_suavizado(estado, "PETR4", i, "compra")
    # Janela = 3: só deve manter os últimos 3
    assert len(estado["PETR4"]["score_history"]) == 3
    assert estado == _historico([3, 4, 5], dias=0)


def test_score_suavizado_fora_limites():
    estado = {"PETR4": {"score_history": [], "ultima_data_score": ""}}
    s = score_suavizado(estado, "PETR4", -1, "compra")
    assert s >= 0
    s = score_suavizado(estado, "PETR4", 15, "compra")
    assert s <= 10


def test_carregar_estado_arquivo_inexistente():
    estado = carregar_estado("nao_existe.json")
    assert estado == {}


def test_carregar_estado_arquivo_valido():
    dados = {"TESTE": {"score": 7, "direcao": "compra", "data_primeiro_alerta": "2026-01-01"}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(dados, f)
        caminho = f.name
    try:
        estado = carregar_estado(caminho)
        assert estado["TESTE"]["score"] == 7
    finally:
        os.unlink(caminho)


def test_salvar_carregar_ciclo():
    dados = {"ATIVO": {"score": 5, "direcao": "venda", "data_primeiro_alerta": "2026-03-15"}}
    try:
        salvar_estado(dados, "_test_estado.json")
        carregado = carregar_estado("_test_estado.json")
        assert carregado["ATIVO"]["score"] == 5
        assert carregado["ATIVO"]["direcao"] == "venda"
    finally:
        if os.path.exists("_test_estado.json"):
            os.unlink("_test_estado.json")


def test_atualizar_estado_mantem_quando_acima_nivel():
    estado = {}
    atualizar_estado(estado, "PETR4", 8, "compra", nivel_detalhe=6, margem_saida=2)
    assert "PETR4" in estado
    assert estado["PETR4"]["score"] == 8


def test_atualizar_estado_remove_quando_abaixo_limite():
    estado = {"PETR4": {"score": 8, "direcao": "compra", "data_primeiro_alerta": "2026-01-01"}}
    atualizar_estado(estado, "PETR4", 3, "compra", nivel_detalhe=6, margem_saida=2)
    assert "PETR4" not in estado


def test_atualizar_estado_preserva_na_zona_amortecimento():
    estado = {"PETR4": {"score": 8, "direcao": "compra", "data_primeiro_alerta": "2026-01-01"}}
    atualizar_estado(estado, "PETR4", 5, "compra", nivel_detalhe=6, margem_saida=2)
    # 5 está na zona de amortecimento (6-2=4 até 6) -> não mexe
    assert "PETR4" in estado
    assert estado["PETR4"]["score"] == 8
