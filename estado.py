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
import tempfile
from datetime import date

CAMINHO_ESTADO_PADRAO = "estado.json"


def carregar_estado(arquivo: str = CAMINHO_ESTADO_PADRAO) -> dict:
    def constante_invalida(valor):
        raise ValueError(f"Constante JSON nao finita: {valor}")

    def sem_duplicatas(pares):
        dados = {}
        for chave, valor in pares:
            if chave in dados:
                raise ValueError(f"Chave duplicada: {chave}")
            dados[chave] = valor
        return dados
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            estado = json.load(f, object_pairs_hook=sem_duplicatas, parse_constant=constante_invalida)
        _validar_estado(estado)
        return estado
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        raise ValueError(f"Nao foi possivel ler {arquivo}; arquivo preservado") from exc


def salvar_estado(estado: dict, arquivo: str = CAMINHO_ESTADO_PADRAO):
    """Substituicao atomica; o chamador deve serializar ciclos ler/alterar/salvar."""
    _validar_estado(estado)
    conteudo = json.dumps(estado, ensure_ascii=False, indent=2, allow_nan=False)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                         dir=os.path.dirname(os.path.abspath(arquivo))) as f:
            temporario = f.name
            f.write(conteudo)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, arquivo)
    finally:
        if temporario and os.path.exists(temporario):
            os.unlink(temporario)


def _validar_score(score):
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 10:
        raise ValueError("Score/nivel deve ser inteiro de 0 a 10")


def _validar_estado(estado):
    if not isinstance(estado, dict):
        raise ValueError("Estado deve ser um mapa de registros")
    for ticker, registro in estado.items():
        if not isinstance(ticker, str) or not ticker.strip() or not isinstance(registro, dict):
            raise ValueError("Registro de estado invalido")
        if "score" in registro:
            _validar_score(registro["score"])
        if "direcao" in registro and registro["direcao"] not in ("compra", "venda", "neutro"):
            raise ValueError("Direcao invalida")
        for campo in ("ultima_data_score", "data_primeiro_alerta"):
            valor = registro.get(campo, "")
            if valor != "":
                if not isinstance(valor, str) or date.fromisoformat(valor).isoformat() != valor:
                    raise ValueError("Data do estado deve ser ISO YYYY-MM-DD")
        historico = registro.get("score_history", [])
        if not isinstance(historico, list):
            raise ValueError("Historico de scores deve ser lista")
        for amostra in historico:
            if isinstance(amostra, dict):
                _validar_score(amostra.get("score"))
                if amostra.get("direcao") not in ("compra", "venda", "neutro"):
                    raise ValueError("Direcao de amostra invalida")
            else:
                _validar_score(amostra)  # Formato numerico legado, descartado na suavizacao.


def score_suavizado(estado: dict, ticker: str, score_novo: int, direcao: str, janela: int = 3) -> int:
    """
    Calcula a média dos últimos `janela` scores na direção atual,
    sem atravessar uma inversão. A execução mais recente substitui a do dia.
    """
    if isinstance(janela, bool) or not isinstance(janela, int) or janela < 1:
        raise ValueError("Janela deve ser inteiro positivo")
    if isinstance(score_novo, bool) or not isinstance(score_novo, int):
        raise ValueError("Score deve ser inteiro finito")
    if direcao not in ("compra", "venda", "neutro"):
        raise ValueError("Direcao invalida")
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("Ticker invalido")
    _validar_estado(estado)
    # Mantem o clamp da interface existente, antes de persistir a amostra.
    score_novo = max(0, min(10, score_novo))
    hoje = date.today().isoformat()
    if ticker not in estado:
        estado[ticker] = {}
    registro = estado[ticker]

    historico = list(registro.get("score_history", []))
    # O formato legado não permite inferir a direção de cada amostra.
    if any(not isinstance(amostra, dict) for amostra in historico):
        historico = []
    amostra = {"score": score_novo, "direcao": direcao}
    if historico and registro.get("ultima_data_score") == hoje:
        historico[-1] = amostra
    else:
        historico.append(amostra)
    historico = historico[-janela:]
    registro["score_history"] = historico
    registro["ultima_data_score"] = hoje

    scores = []
    for amostra in reversed(historico):
        if amostra["direcao"] != direcao:
            break
        scores.append(amostra["score"])
    media = round(sum(scores) / len(scores))
    # Garante que fica entre 0 e 10
    return max(0, min(10, media))


def eh_alerta_novo(estado: dict, ticker: str, score: int, direcao: str, nivel_detalhe: int) -> bool:
    """
    Decide se esse é um alerta NOVO (deve mostrar plano completo) ou se já
    foi avisado antes na mesma direção (deve mostrar só a versão resumida).
    """
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("Ticker invalido")
    _validar_estado(estado)
    _validar_score(score)
    _validar_score(nivel_detalhe)
    if direcao not in ("compra", "venda", "neutro"):
        raise ValueError("Direcao invalida")
    if direcao == "neutro" or score < nivel_detalhe:
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
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("Ticker invalido")
    _validar_estado(estado)
    _validar_score(score)
    _validar_score(nivel_detalhe)
    if isinstance(margem_saida, bool) or not isinstance(margem_saida, int) or not 0 <= margem_saida <= nivel_detalhe:
        raise ValueError("Margem deve ser inteira entre zero e nivel_detalhe")
    if direcao not in ("compra", "venda", "neutro"):
        raise ValueError("Direcao invalida")
    limite_saida = nivel_detalhe - margem_saida

    if direcao == "neutro":
        # Encerra o alerta, mas preserva a amostra neutra como barreira direcional.
        registro = estado.get(ticker, {})
        for campo in ("score", "direcao", "data_primeiro_alerta"):
            registro.pop(campo, None)
    elif score >= nivel_detalhe:
        anterior = estado.get(ticker, {})
        estado[ticker] = {
            "score": score,
            "direcao": direcao,
            "data_primeiro_alerta": anterior.get("data_primeiro_alerta", date.today().isoformat())
                                     if anterior.get("direcao") == direcao else date.today().isoformat(),
            # Preserva o histórico de scores para a suavização não quebrar
            "score_history": anterior.get("score_history", []),
            "ultima_data_score": anterior.get("ultima_data_score", ""),
        }
    elif score < limite_saida:
        estado.pop(ticker, None)  # caiu de vez -> esquece, próxima subida conta como sinal novo
    # else: está na zona de amortecimento -> não mexe no estado, preserva a memória

    return estado
