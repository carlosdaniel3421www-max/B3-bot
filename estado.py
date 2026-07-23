"""
Estado — lembra o que já foi alertado, pra não mandar o mesmo plano de
entrada todo santo dia enquanto o sinal continuar forte.

Guarda um arquivo estado.json com o último nível/direção alertado de cada
ativo. O workflow do GitHub Actions faz commit desse arquivo de volta pro
repositório depois de cada execução, então o "histórico" persiste entre
os dias (runners do GitHub Actions são descartáveis, então sem isso a
memória se perderia a cada execução).
"""

import json
import os
from datetime import date

CAMINHO_ESTADO_PADRAO = "estado.json"


def carregar_estado(arquivo: str = CAMINHO_ESTADO_PADRAO) -> dict:
    if not os.path.exists(arquivo):
        return {}
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def salvar_estado(estado: dict, arquivo: str = CAMINHO_ESTADO_PADRAO):
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def eh_alerta_novo(estado: dict, ticker: str, score: int, direcao: str, nivel_detalhe: int) -> bool:
    """
    Decide se esse é um alerta NOVO (deve mostrar plano completo) ou se já
    foi avisado antes na mesma direção (deve mostrar só a versão resumida).
    """
    if score < nivel_detalhe:
        return False  # nível baixo nunca gera plano completo

    anterior = estado.get(ticker)
    if anterior is None:
        return True
    if anterior.get("direcao") != direcao:
        return True
    if anterior.get("score", 0) < nivel_detalhe:
        return True
    return False


def atualizar_estado(estado: dict, ticker: str, score: int, direcao: str, nivel_detalhe: int) -> dict:
    """Atualiza (ou remove) a entrada do ativo no estado, conforme o nível atual."""
    if score >= nivel_detalhe:
        anterior = estado.get(ticker, {})
        estado[ticker] = {
            "score": score,
            "direcao": direcao,
            "data_primeiro_alerta": anterior.get("data_primeiro_alerta", date.today().isoformat())
                                     if anterior.get("direcao") == direcao else date.today().isoformat(),
        }
    else:
        estado.pop(ticker, None)  # sinal caiu de nível -> esquece, próxima vez que subir é "novo" de novo
    return estado
