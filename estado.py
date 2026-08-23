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


def score_suavizado(estado: dict, ticker: str, score_novo: int, janela: int = 3) -> int:
    """
    Calcula o score suavizado como média dos últimos `janela` scores.
    Guarda histórico no estado para evitar que um único dia extremo
    (ex: 10/10) vire 4/10 no dia seguinte por oscilação comum.
    """
    hoje = date.today().isoformat()
    if ticker not in estado:
        estado[ticker] = {}
    registro = estado[ticker]

    if "score_history" not in registro:
        registro["score_history"] = []
    if "ultima_data_score" not in registro:
        registro["ultima_data_score"] = ""

    # Só adiciona ao histórico se for um dia diferente
    if registro["ultima_data_score"] != hoje:
        registro["score_history"].append(score_novo)
        registro["ultima_data_score"] = hoje
        # Mantém só os últimos `janela` scores
        registro["score_history"] = registro["score_history"][-janela:]

    # Média dos últimos scores
    historico = registro["score_history"]
    if not historico:
        return score_novo
    media = round(sum(historico) / len(historico))
    # Garante que fica entre 0 e 10
    return max(0, min(10, media))


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


def atualizar_estado(estado: dict, ticker: str, score: int, direcao: str, nivel_detalhe: int, margem_saida: int = 2) -> dict:
    """
    Atualiza (ou remove) a entrada do ativo no estado, conforme o nível atual.

    margem_saida: só considera o sinal REALMENTE encerrado (e limpa a memória)
    quando o score cai mais que essa margem abaixo do nível de detalhe. Isso
    evita "flapping" — um ativo oscilando entre 5 e 6, por exemplo, não
    dispara o plano completo de novo a cada dia que toca 6, porque enquanto
    ele estiver na "zona de amortecimento" (nivel_detalhe - margem_saida até
    nivel_detalhe), a memória do alerta anterior é preservada.
    """
    limite_saida = nivel_detalhe - margem_saida

    if score >= nivel_detalhe:
        anterior = estado.get(ticker, {})
        estado[ticker] = {
            "score": score,
            "direcao": direcao,
            "data_primeiro_alerta": anterior.get("data_primeiro_alerta", date.today().isoformat())
                                     if anterior.get("direcao") == direcao else date.today().isoformat(),
        }
    elif score < limite_saida:
        estado.pop(ticker, None)  # caiu de vez -> esquece, próxima subida conta como sinal novo
    # else: está na zona de amortecimento -> não mexe no estado, preserva a memória

    return estado
