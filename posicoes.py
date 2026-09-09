"""
Gestão de posições abertas — o robô agora acompanha as operações que você
abriu e te diz exatamente O QUE FAZER a cada dia (proteger lucro, mover
stop, fechar, etc).

USO (linha de comando):
    python posicoes.py adicionar PETR4 compra 43.11 40.50 48.22
    python posicoes.py adicionar VALE3 venda 72.50 74.00 68.00 --quantidade 300
    python posicoes.py listar
    python posicoes.py remover PETR4
    python posicoes.py status PETR4   # mostra gestão da posição com preço atual

Formato do registro (posicoes.json):
    {
        "PETR4": {
            "ticker": "PETR4",
            "direcao": "compra" | "venda",
            "preco_entrada": 43.11,
            "stop": 40.50,
            "alvo": 48.22,
            "quantidade": 100,
            "data_entrada": "2026-08-19",
            "prazo_maximo_dias": 20
        }
    }

Regras de gestão automática (quando o robô roda o relatório diário):
    - Preço <= stop (compra): SAIR AGORA — stop atingido
    - Preço >= alvo (compra): FECHAR — alvo atingido
    - Preço em 50% do caminho até o alvo: mover stop para o preço de entrada
      (breakeven) — trade sem risco
    - Preço em 75% do caminho: considerar fechar parcial (trava lucro)
    - Prazo máximo de holding expirado: fechar por tempo
    - Demais casos: manter posição com stop/alvo originais
"""

import argparse
import json
import logging
import math
import os
import sys
import tempfile
import threading
from functools import wraps
from datetime import date, datetime, timedelta

import requests

CAMINHO_POSICOES = "posicoes.json"
CAMINHO_PROPOSTAS = "propostas.json"
DIAS_UTEIS_POR_SEMANA = 5.0

# Frações do caminho preço-entrada -> alvo onde aplicamos regras
FRACAO_BREAKEVEN = 0.5    # 50% do caminho: move stop pro breakeven
FRACAO_FECHAR_PARCIAL = 0.75  # 75% do caminho: trava lucro parcial

# Limites de segurança
STOP_MINIMO_PCT = 0.02   # nunca sugere stop menor que 2% do preço
ALVO_MAXIMO_PCT = 0.30   # nunca sugere alvo maior que 30% do preço (opções mais curtas)
_persistencia_lock = threading.RLock()


def _serializar(funcao):
    """Protege o ciclo leitura/alteracao/gravacao entre threads deste processo."""
    @wraps(funcao)
    def executar(*args, **kwargs):
        with _persistencia_lock:
            return funcao(*args, **kwargs)
    return executar


def _carregar_json(caminho):
    def sem_duplicatas(pares):
        resultado = {}
        for chave, valor in pares:
            if chave in resultado:
                raise ValueError(f"Chave duplicada: {chave}")
            resultado[chave] = valor
        return resultado
    try:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f, object_pairs_hook=sem_duplicatas)
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as e:
        raise ValueError(f"Nao foi possivel ler {caminho}; arquivo preservado") from e
    if not isinstance(dados, dict) or not all(isinstance(v, dict) for v in dados.values()):
        raise ValueError(f"Estrutura invalida em {caminho}; arquivo preservado")
    return dados


def _salvar_json(caminho, dados):
    if not isinstance(dados, dict) or not all(isinstance(v, dict) for v in dados.values()):
        raise ValueError("Persistencia exige um mapa de registros")
    conteudo = json.dumps(dados, ensure_ascii=False, indent=2, allow_nan=False)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                         dir=os.path.dirname(os.path.abspath(caminho))) as f:
            temporario = f.name
            f.write(conteudo)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, caminho)
    finally:
        if temporario and os.path.exists(temporario):
            os.unlink(temporario)
    if not _sincronizar_github(caminho) and os.environ.get("GITHUB_TOKEN"):
        logging.error("%s salvo localmente, mas NAO persistido no GitHub", caminho)


def numero_finito(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def _validar_numeros(*valores):
    if not all(numero_finito(v) for v in valores):
        raise ValueError("Valores devem ser números finitos")


def carregar_posicoes() -> dict:
    return _carregar_json(CAMINHO_POSICOES)


@_serializar
def salvar_posicoes(posicoes: dict):
    _salvar_json(CAMINHO_POSICOES, posicoes)


REPO_GITHUB = "carlosdaniel3421www-max/B3-bot"
BRANCH_GITHUB = "main"


def _sincronizar_github(arquivo: str):
    """
    Faz commit do arquivo (ex: posicoes.json) no GitHub via API de Contents.
    Usa o GITHUB_TOKEN. Assim as posições persistem mesmo quando o Render
    reinicia (disco efêmero). Falha silenciosa se token ausente.
    """
    import base64
    import urllib.parse
    import requests

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return False

    nome_arquivo = os.path.basename(arquivo)
    if not os.path.exists(arquivo):
        logging.warning("Arquivo %s não existe para sincronizar com o GitHub", arquivo)
        return False
    with open(arquivo, "r", encoding="utf-8") as f:
        conteudo = f.read()

    # Busca o SHA atual do arquivo (necessário para atualizar)
    nome_codificado = urllib.parse.quote(nome_arquivo, safe="")
    url_arquivo = f"https://api.github.com/repos/{REPO_GITHUB}/contents/{nome_codificado}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

    try:
        resp = requests.get(url_arquivo, headers=headers, params={"ref": BRANCH_GITHUB}, timeout=15)
        sha = None
        if resp.status_code == 200:
            sha = resp.json().get("sha")
        elif resp.status_code != 404:
            return False

        payload = {
            "message": f"Atualiza {nome_arquivo} [skip ci]",
            "content": base64.b64encode(conteudo.encode("utf-8")).decode("utf-8"),
            "branch": BRANCH_GITHUB,
        }
        if sha:
            payload["sha"] = sha

        resp = requests.put(url_arquivo, json=payload, headers=headers, timeout=15)
        return resp.status_code in (200, 201)
    except Exception as e:
        logging.warning("Falha ao sincronizar %s no GitHub: %s", arquivo, e)
        return False


# ---------------------------------------------------------------------------
# PROPOSTAS: o robô sugere uma entrada (ENV). Você decide registrar ou não.
# ---------------------------------------------------------------------------

def carregar_propostas() -> dict:
    return _carregar_json(CAMINHO_PROPOSTAS)


@_serializar
def salvar_propostas(propostas: dict):
    _salvar_json(CAMINHO_PROPOSTAS, propostas)


@_serializar
def salvar_proposta_entrada(ticker: str, direcao: str, preco: float,
                            stop: float, alvo: float, prazo_maximo_dias: int = 20,
                            plano_setup: dict = None) -> dict:
    """Salva a proposta de entrada que o robô fez, pra você confirmar depois."""
    _validar_numeros(preco, stop, alvo, prazo_maximo_dias)
    direcao = direcao.lower()
    if (direcao not in ("compra", "venda") or not ticker.strip()
            or prazo_maximo_dias <= 0 or int(prazo_maximo_dias) != prazo_maximo_dias
            or min(preco, stop, alvo) <= 0
            or not (stop < preco < alvo if direcao == "compra" else alvo < preco < stop)):
        raise ValueError("Proposta invalida: confira direcao, precos e prazo")
    ticker = ticker.upper()
    propostas = carregar_propostas()
    proposta = {
        "ticker": ticker,
        "direcao": direcao,
        "preco_entrada": preco,
        "stop": stop,
        "alvo": alvo,
        "prazo_maximo_dias": prazo_maximo_dias,
        "data_proposta": date.today().isoformat(),
    }
    if plano_setup is not None:
        if (plano_setup.get("estado") != "candidato" or plano_setup.get("direcao") != direcao
                or plano_setup.get("gatilho") != preco or plano_setup.get("stop") != stop
                or plano_setup.get("alvo") != alvo):
            raise ValueError("Plano de setup inconsistente com proposta")
        proposta["plano_setup"] = dict(plano_setup)
        proposta["estado_entrada"] = "candidato"
    propostas[ticker] = proposta
    salvar_propostas(propostas)
    return proposta


@_serializar
def registrar_da_proposta(ticker: str, quantidade: int = 0) -> tuple:
    """
    Registra uma posição a partir da proposta mais recente do robô.
    Retorna (posicao, mensagem).
    """
    ticker = ticker.upper()
    propostas = carregar_propostas()
    if ticker not in propostas:
        return None, f"⚠️ Não achei proposta de entrada pra {ticker}. O robô só propõe quando dá ENTRAR (score ≥ 8) num relatório recente."

    proposta = propostas[ticker]
    if proposta.get("estado_entrada") == "candidato":
        return None, ("Candidato aguardando gatilho, nao e entrada executada. Use /gatilho para conferir "
                      "o plano; apos operar, registre manualmente o preco e a quantidade reais.")
    _validar_numeros(proposta.get("preco_entrada"), proposta.get("stop"), proposta.get("alvo"),
                     proposta.get("prazo_maximo_dias", 20), quantidade)
    posicoes = carregar_posicoes()
    if ticker in posicoes:
        return posicoes[ticker], f"{ticker} ja registrada; posicao preservada, proposta nao aplicada."

    # Sem prazo de validade no schema legado, nao executar sinal de outro dia.
    if proposta.get("data_proposta") != date.today().isoformat():
        return None, "Proposta expirada ou sem data valida; gere um novo relatorio."
    if proposta.get("ticker", ticker) != ticker or proposta.get("direcao") not in ("compra", "venda"):
        raise ValueError("Identidade/direcao invalida na proposta")
    posicao = adicionar_posicao(ticker, proposta["direcao"], proposta["preco_entrada"],
                                proposta["stop"], proposta["alvo"], quantidade,
                                proposta.get("prazo_maximo_dias", 20))
    return posicao, f"✅ <b>{ticker}</b> registrada ({posicao['direcao']}). Entrada R$ {posicao['preco_entrada']} · Stop R$ {posicao['stop']} · Alvo R$ {posicao['alvo']}. Agora acompanho todo dia."


@_serializar
def adicionar_posicao(ticker: str, direcao: str, preco_entrada: float,
                      stop: float, alvo: float, quantidade: int = 0,
                      prazo_maximo_dias: int = 20) -> dict:
    """Adiciona (ou atualiza) uma posição aberta."""
    ticker = ticker.upper()
    direcao = direcao.lower()
    if direcao not in ("compra", "venda"):
        raise ValueError("direcao deve ser 'compra' ou 'venda'")

    _validar_numeros(preco_entrada, stop, alvo, quantidade, prazo_maximo_dias)
    if not ticker.strip() or int(quantidade) != quantidade or int(prazo_maximo_dias) != prazo_maximo_dias:
        raise ValueError("Ticker obrigatorio; quantidade e prazo devem ser inteiros")
    if quantidade < 0 or prazo_maximo_dias <= 0:
        raise ValueError("Quantidade deve ser não negativa e prazo positivo")
    if preco_entrada <= 0 or stop <= 0 or alvo <= 0:
        raise ValueError("Preços devem ser maiores que zero")

    # Validação de sanidade do stop/alvo
    if direcao == "compra":
        if stop >= preco_entrada:
            raise ValueError("Stop deve ser MENOR que o preço de entrada (compra)")
        if alvo <= preco_entrada:
            raise ValueError("Alvo deve ser MAIOR que o preço de entrada (compra)")
    else:
        if stop <= preco_entrada:
            raise ValueError("Stop deve ser MAIOR que o preço de entrada (venda)")
        if alvo >= preco_entrada:
            raise ValueError("Alvo deve ser MENOR que o preço de entrada (venda)")

    posicoes = carregar_posicoes()
    if posicoes.get(ticker, {}).get("tipo_operacao") == "trava":
        raise ValueError("Ja existe uma trava neste ticker; registro preservado")
    posicao = {
        "ticker": ticker,
        "direcao": direcao,
        "preco_entrada": preco_entrada,
        "stop": stop,
        "alvo": alvo,
        "quantidade": quantidade,
        "data_entrada": posicoes.get(ticker, {}).get("data_entrada", date.today().isoformat()),
        "prazo_maximo_dias": prazo_maximo_dias,
    }
    posicoes[ticker] = posicao
    salvar_posicoes(posicoes)
    return posicao


@_serializar
def adicionar_trava(ticker: str, tipo: str, strike_comprado: float, premio_comprado: float,
                    strike_vendido: float, premio_vendido: float,
                    stop_premio: float, alvo_premio: float,
                    quantidade: int = 100, vencimento: str = "") -> dict:
    """
    Registra uma TRAVA montada (Bull/Bear Spread) como posição aberta.
    O "preco_entrada" é o custo líquido por contrato (débito).
    O "stop" e "alvo" são valores no PRÊMIO da trava (em R$ por contrato).
    """
    ticker = ticker.upper()
    tipo = tipo.lower()
    if tipo not in ("compra", "venda"):
        raise ValueError("tipo deve ser 'compra' ou 'venda'")

    _validar_numeros(strike_comprado, strike_vendido, premio_comprado,
                     premio_vendido, stop_premio, alvo_premio, quantidade)
    if not ticker.strip() or int(quantidade) != quantidade:
        raise ValueError("Ticker obrigatorio e quantidade inteira")
    if min(strike_comprado, strike_vendido, premio_comprado) <= 0 or premio_vendido < 0:
        raise ValueError("Strikes e prêmio comprado devem ser positivos; prêmio vendido não negativo")
    if quantidade <= 0 or stop_premio < 0:
        raise ValueError("Quantidade deve ser positiva e stop não negativo")
    if vencimento:
        date.fromisoformat(vencimento)
    largura = (strike_vendido - strike_comprado) if tipo == "compra" else (strike_comprado - strike_vendido)
    custo_liquido = round(premio_comprado - premio_vendido, 10)
    if not 0 < custo_liquido < largura:
        raise ValueError("Custo líquido da trava deve ser positivo e menor que a largura dos strikes na direção registrada")

    if stop_premio >= custo_liquido:
        raise ValueError("Stop no prêmio deve ser MENOR que o custo da trava")
    if alvo_premio <= custo_liquido:
        raise ValueError("Alvo no prêmio deve ser MAIOR que o custo da trava")
    if alvo_premio > largura and not math.isclose(alvo_premio, largura):
        raise ValueError("Alvo nao pode exceder a largura da trava")

    posicoes = carregar_posicoes()
    if ticker in posicoes and posicoes[ticker].get("tipo_operacao") != "trava":
        raise ValueError("Ja existe uma posicao neste ticker; registro preservado")
    posicao = {
        "ticker": ticker,
        "direcao": tipo,
        "tipo_operacao": "trava",
        "strike_comprado": strike_comprado,
        "strike_vendido": strike_vendido,
        "premio_comprado": premio_comprado,
        "premio_vendido": premio_vendido,
        "preco_entrada": custo_liquido,           # débito por contrato
        "stop": stop_premio,                     # stop no valor líquido
        "alvo": alvo_premio,                     # alvo no valor líquido
        "quantidade": quantidade,
        "vencimento": vencimento,
        "data_entrada": posicoes.get(ticker, {}).get("data_entrada", date.today().isoformat()),
        "prazo_maximo_dias": 20,
    }
    posicoes[ticker] = posicao
    salvar_posicoes(posicoes)
    return posicao


def gerar_gestao_trava(trava: dict, preco_atual_premio: float | None) -> dict:
    """Decisão sobre o valor líquido, tanto para bull call quanto bear put."""
    hoje = date.today()
    try:
        dias = (date.fromisoformat(trava.get("vencimento", "")) - hoje).days
    except (ValueError, TypeError):
        dias = None
    resultado = {"acao": "INDISPONÍVEL", "lucro_pct": None,
                 "data_atual": hoje.isoformat(), "dias_ate_vencimento": dias,
                 "preco_atual": None}
    campos = ("preco_entrada", "stop", "alvo", "strike_comprado", "strike_vendido")
    if (not all(numero_finito(trava.get(c)) for c in campos)
            or not all(numero_finito(trava[c]) for c in (
                "quantidade", "premio_comprado", "premio_vendido", "prazo_maximo_dias") if c in trava)):
        resultado["motivo"] = "Registro inválido: valores devem ser números finitos."
        return resultado
    custo, stop, alvo = (trava[c] for c in campos[:3])
    largura = (trava["strike_vendido"] - trava["strike_comprado"]
               if trava.get("direcao") == "compra"
               else trava["strike_comprado"] - trava["strike_vendido"])
    if (trava.get("direcao") not in ("compra", "venda")
            or not 0 < custo < largura or not 0 <= stop < custo < alvo
            or alvo > largura + 1e-9
            or min(trava["strike_comprado"], trava["strike_vendido"]) <= 0
            or trava.get("quantidade", 0) < 0
            or int(trava.get("quantidade", 0)) != trava.get("quantidade", 0)
            or trava.get("prazo_maximo_dias", 20) <= 0
            or int(trava.get("prazo_maximo_dias", 20)) != trava.get("prazo_maximo_dias", 20)
            or trava.get("premio_comprado", custo) <= 0
            or trava.get("premio_vendido", 0) < 0
            or ("premio_comprado" in trava and "premio_vendido" in trava
                and not math.isclose(trava["premio_comprado"] - trava["premio_vendido"], custo,
                                     abs_tol=1e-9))
            or (trava.get("vencimento") and dias is None)):
        resultado["motivo"] = "Registro inválido: confira débito, strikes, stop, alvo e quantidade."
        return resultado
    resultado.update(risco_maximo=custo, ganho_maximo=largura - custo)
    if (not numero_finito(preco_atual_premio) or preco_atual_premio < 0
            or preco_atual_premio > largura + 1e-9):
        resultado["motivo"] = ("Cotação líquida indisponível: são necessários preços finitos das duas pernas "
                               "nos strikes e vencimento exatos registrados. Sem recomendação de manter/sair.")
        return resultado
    resultado["preco_atual"] = preco_atual_premio
    resultado["lucro_pct"] = (preco_atual_premio - custo) / custo * 100
    if preco_atual_premio <= stop:
        resultado["acao"] = "STOP"
    elif preco_atual_premio >= alvo:
        resultado["acao"] = "ALVO"
    elif dias is not None and dias <= 0:
        resultado["acao"] = "VERIFICAR VENCIMENTO"
    else:
        resultado["acao"] = "MANTER PLANO"
    return resultado


def formatar_gestao_trava(trava: dict, preco_atual_premio: float | None) -> str:
    """Compara o fechamento líquido das duas pernas ao débito registrado."""
    gestao = gerar_gestao_trava(trava, preco_atual_premio)
    custo = trava.get("preco_entrada", 0)
    stop = trava.get("stop", 0)
    alvo = trava.get("alvo", 0)
    direcao = trava.get("direcao", "compra")

    emoji = "🟢" if direcao == "compra" else "🔴"
    linhas = [f"{emoji} <b>{trava['ticker']}</b> — TRAVA ({trava.get('strike_comprado','?')}/{trava.get('strike_vendido','?')})"]
    linhas.append(f"  Data atual: {gestao['data_atual']} | Vencimento: {trava.get('vencimento') or 'não registrado'}")
    dias = gestao["dias_ate_vencimento"]
    linhas.append(f"  Dias corridos até vencimento: {dias if dias is not None else 'indisponível'}")
    if dias is not None and dias <= 0:
        linhas.append("Vencimento atingido: verifique exercicio/liquidacao com a corretora, mesmo sem cotacao disponivel.")
    linhas.append("  Referência de fechamento do último pregão, não tempo real; execução não garantida. Confirme bid/ask e liquidez das duas pernas.")
    if "risco_maximo" not in gestao:
        linhas.append("  " + gestao["motivo"])
        return "\n".join(linhas)

    linhas.append(f"  💰 Débito por contrato: R$ {custo:.2f}")
    qtd = trava.get("quantidade", 0)
    if qtd:
        linhas.append(f"  📦 Contratos: {qtd} | Custo total: R$ {custo * qtd:.2f}")
    linhas.append(f"  🛑 Stop no prêmio líquido: R$ {stop:g} | 🎯 Alvo no prêmio líquido: R$ {alvo:g}")

    linhas.append(f"  Risco máximo teórico: R$ {gestao['risco_maximo']:.2f} | Ganho máximo teórico: R$ {gestao['ganho_maximo']:.2f} por contrato, antes de custos, com ambas as pernas intactas.")
    linhas.append("  Risco limitado não significa risco baixo: pode perder todo o débito. Tempo não é necessariamente favorável; há risco de liquidez, exercício e custos.")
    if gestao["preco_atual"] is not None:
        linhas.append(f"  📊 Valor líquido da trava (comprada - vendida): R$ {preco_atual_premio:.2f} ({gestao['lucro_pct']:+.1f}%)")
    linhas.append(f"  Resultado determinístico: <b>{gestao['acao']}</b>")
    if gestao["acao"] == "STOP":
        linhas.append("  <b>STOP no prêmio atingido no fechamento: priorize encerrar a trava, confirmando preços executáveis.</b>")
    elif gestao["acao"] == "ALVO":
        linhas.append("  <b>ALVO atingido no fechamento: priorize realizar, confirmando preços executáveis.</b>")
    elif gestao["acao"] == "VERIFICAR VENCIMENTO":
        linhas.append("  Verifique exercício/liquidação com a corretora; não prolongue a posição automaticamente.")
    elif gestao["acao"] == "INDISPONÍVEL":
        linhas.append("  " + gestao["motivo"])

    return "\n".join(linhas)


@_serializar
def remover_posicao(ticker: str) -> bool:
    posicoes = carregar_posicoes()
    if ticker.upper() in posicoes:
        del posicoes[ticker.upper()]
        salvar_posicoes(posicoes)
        return True
    return False


def _dias_corridos(data_entrada: str) -> int:
    try:
        d_entrada = datetime.strptime(data_entrada, "%Y-%m-%d").date()
        return (date.today() - d_entrada).days
    except (ValueError, TypeError):
        logging.warning("Data de entrada inválida no posicoes.json: %r", data_entrada)
        return 0


def _projecao_dias_uteis(dias_corridos: int) -> int:
    """Aproximação de dias corridos -> dias úteis (fins de semana removidos)."""
    return max(1, int(dias_corridos * DIAS_UTEIS_POR_SEMANA / 7.0))


def gerar_gestao_posicao(posicao: dict, preco_atual: float) -> dict:
    """
    Dado o preço atual do ativo, retorna as instruções de gestão da posição.

    Retorna dict com: acao, emoji, instrucoes, pct_no_caminho, lucro_pct
    """
    if posicao.get("tipo_operacao") == "trava":
        raise ValueError("Use gerar_gestao_trava com o valor líquido das duas pernas, nunca o preço da ação")
    _validar_numeros(preco_atual, *(posicao.get(c) for c in ("preco_entrada", "stop", "alvo")),
                     posicao.get("quantidade", 0), posicao.get("prazo_maximo_dias", 20))
    if (min(preco_atual, posicao["preco_entrada"], posicao["stop"], posicao["alvo"]) <= 0
            or posicao.get("quantidade", 0) < 0 or posicao.get("prazo_maximo_dias", 20) <= 0
            or posicao.get("direcao") not in ("compra", "venda")):
        raise ValueError("Registro/preço inválido para gestão")
    ticker = posicao.get("ticker")
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("Ticker ausente ou invalido")
    direcao = posicao["direcao"]
    entrada = posicao["preco_entrada"]
    stop = posicao["stop"]
    alvo = posicao["alvo"]
    prazo_max = posicao.get("prazo_maximo_dias", 20)
    if (not (entrada < alvo and stop < alvo if direcao == "compra" else alvo < entrada and alvo < stop)
            or int(posicao.get("quantidade", 0)) != posicao.get("quantidade", 0)
            or int(prazo_max) != prazo_max):
        raise ValueError("Registro invalido: alvo, stop, quantidade ou prazo incoerentes")
    try:
        inicio = date.fromisoformat(posicao["data_entrada"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("Data de entrada invalida") from e
    if inicio > date.today():
        raise ValueError("Data de entrada futura")
    # Conta dias de segunda a sexta; feriados B3 nao estao disponiveis aqui.
    dias_uteis = sum((inicio + timedelta(days=i)).weekday() < 5
                     for i in range(1, (date.today() - inicio).days + 1))

    if direcao == "compra":
        lucro_pct = (preco_atual - entrada) / entrada * 100
        caminho_total = alvo - entrada
        pct_no_caminho = 0.0 if caminho_total <= 0 else max(0.0, min(1.0, (preco_atual - entrada) / caminho_total))
        stop_atingido = preco_atual <= stop
        alvo_atingido = preco_atual >= alvo
        breakeven = preco_atual >= entrada + FRACAO_BREAKEVEN * caminho_total
        parcial_75 = preco_atual >= entrada + FRACAO_FECHAR_PARCIAL * caminho_total
    else:  # venda
        lucro_pct = (entrada - preco_atual) / entrada * 100
        caminho_total = entrada - alvo
        pct_no_caminho = 0.0 if caminho_total <= 0 else max(0.0, min(1.0, (entrada - preco_atual) / caminho_total))
        stop_atingido = preco_atual >= stop
        alvo_atingido = preco_atual <= alvo
        breakeven = preco_atual <= entrada - FRACAO_BREAKEVEN * caminho_total
        parcial_75 = preco_atual <= entrada - FRACAO_FECHAR_PARCIAL * caminho_total

    tempo_expirado = dias_uteis >= prazo_max

    # --- Decisão de ação (prioridade: stop > alvo > tempo > parcial > breakeven > manter) ---
    if stop_atingido:
        acao, emoji = "SAIR AGORA", "🔴"
        instrucoes = [f"Stop atingido (preço {preco_atual:.2f}; stop {stop:.2f}).", "Priorize encerrar, confirmando preços executáveis."]
    elif alvo_atingido:
        acao, emoji = "FECHAR", "✅"
        instrucoes = [f"Alvo atingido (preço {preco_atual:.2f}; alvo {alvo:.2f}).", "Priorize realizar, confirmando preços executáveis."]
    elif tempo_expirado:
        acao, emoji = "FECHAR POR TEMPO", "⏰"
        instrucoes = [f"Prazo máximo de {prazo_max} dias úteis atingido ({dias_uteis} dias).", "Feche a posição — o movimento não andou."]
    elif parcial_75:
        acao, emoji = "FECHAR PARCIAL", "💰"
        instrucoes = [f"Posição em {pct_no_caminho * 100:.0f}% do caminho até o alvo.", "Feche metade e trave o lucro; deixe o resto correr até o alvo.", f"Movimente o stop para {entrada:.2f} (breakeven) na parte restante."]
    elif breakeven:
        acao, emoji = "PROTEGER", "🟢"
        instrucoes = [f"Posição em {pct_no_caminho * 100:.0f}% do caminho até o alvo.", f"Movimente o stop para {entrada:.2f} (breakeven); gaps, custos e execução ainda oferecem risco."]
    else:
        acao, emoji = "MANTER", "🟡"
        instrucoes = [f"Posição em {pct_no_caminho * 100:.0f}% do caminho até o alvo.", f"Mantenha. Stop {stop:.2f} · Alvo {alvo:.2f}."]

    return {
        "ticker": ticker,
        "direcao": direcao,
        "acao": acao,
        "emoji": emoji,
        "instrucoes": instrucoes,
        "preco_atual": round(preco_atual, 2),
        "preco_entrada": entrada,
        "stop": stop,
        "alvo": alvo,
        "lucro_pct": round(lucro_pct, 2),
        "pct_no_caminho": round(pct_no_caminho * 100, 0),
        "dias_uteis": dias_uteis,
        "prazo_maximo_dias": prazo_max,
        "quantidade": posicao.get("quantidade", 0),
        "valor_total": round(preco_atual * posicao.get("quantidade", 0), 2),
    }


def formatar_gestao(gestao: dict) -> str:
    """Formata a gestão de UMA posição para o Telegram."""
    p = gestao
    linhas = [
        f"{p['emoji']} <b>{p['ticker']} — {p['acao']}</b> ({p['direcao'].upper()})",
        f"  Preço atual: R$ {p['preco_atual']:.2f} | Entrada: R$ {p['preco_entrada']:.2f} | Lucro: {p['lucro_pct']:+.2f}%",
        f"  Stop: R$ {p['stop']:.2f} · Alvo: R$ {p['alvo']:.2f} | {p['pct_no_caminho']:.0f}% do caminho | {p['dias_uteis']}/{p['prazo_maximo_dias']} dias úteis (seg-sex, sem descontar feriados)",
        "  Referência de fechamento, não tempo real; execução do stop/alvo não garantida.",
    ]
    if p.get("quantidade"):
        linhas.append(f"  📦 Quantidade: {p['quantidade']} | Valor total: R$ {p['valor_total']:.2f}")
    for inst in p["instrucoes"]:
        linhas.append(f"  • {inst}")
    return "\n".join(linhas)


def formatar_gestao_todas(posicoes: dict, precos: dict) -> str:
    """Formata o bloco completo de gestão de posições para o Telegram."""
    if not posicoes:
        return ""

    blocos = []
    for ticker, posicao in posicoes.items():
        preco = precos.get(ticker)
        if posicao.get("tipo_operacao") == "trava":
            premio_trava = _buscar_premio_trava(ticker, posicao)
            blocos.append(formatar_gestao_trava(posicao, premio_trava))
            continue
        if not numero_finito(preco) or preco <= 0:
            blocos.append(f"⚪ <b>{ticker}</b> — preço atual indisponível para gestão")
            continue
        try:
            blocos.append(formatar_gestao(gerar_gestao_posicao(posicao, preco)))
        except ValueError as e:
            blocos.append(f"{ticker}: gestão indisponível. {e}")

    if not blocos:
        return ""

    return "📋 <b>GESTÃO DE POSIÇÕES ABERTAS</b>\n" + "\n\n".join(blocos)


def _buscar_premio_trava(ticker: str, trava: dict) -> float | None:
    """Fechamento líquido das pernas exatas registradas; sem substituições."""
    try:
        from fonte_opcoes import buscar_cadeia_estruturada, cotacao_utilizavel
        strike_comprado = trava.get("strike_comprado")
        strike_vendido = trava.get("strike_vendido")
        vencimento = trava.get("vencimento")
        if (not numero_finito(strike_comprado) or not numero_finito(strike_vendido)
                or not vencimento or trava.get("direcao") not in ("compra", "venda")):
            return None
        date.fromisoformat(vencimento)
        tipo_opcao = "call" if trava.get("direcao") == "compra" else "put"
        cadeia = buscar_cadeia_estruturada(ticker)
        if not cadeia:
            return None
        venc = next((v for v in cadeia.get("expirations", []) if v.get("dt") == vencimento), None)
        if not venc:
            return None
        lado = venc.get("calls" if tipo_opcao == "call" else "puts", {})
        if not all(cotacao_utilizavel(lado.get(s) or {}, cadeia)
                   for s in (strike_comprado, strike_vendido)):
            return None
        comprado = (lado.get(strike_comprado) or {}).get("preco")
        vendido = (lado.get(strike_vendido) or {}).get("preco")
        if not all(numero_finito(p) and p >= 0 for p in (comprado, vendido)):
            return None
        liquido = round(comprado - vendido, 2)
        largura = abs(strike_comprado - strike_vendido)
        return liquido if numero_finito(liquido) and 0 <= liquido <= largura + 1e-9 else None
    except Exception as e:
        logging.warning("Falha ao buscar prêmio real da trava %s: %s", ticker, e)
        return None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Gestão de posições abertas")
    sub = parser.add_subparsers(dest="comando")

    p_add = sub.add_parser("adicionar", help="Registrar uma posição aberta")
    p_add.add_argument("ticker")
    p_add.add_argument("direcao", choices=["compra", "venda"])
    p_add.add_argument("preco_entrada", type=float)
    p_add.add_argument("stop", type=float)
    p_add.add_argument("alvo", type=float)
    p_add.add_argument("--quantidade", type=int, default=0)
    p_add.add_argument("--prazo-maximo", type=int, default=20)

    p_rem = sub.add_parser("remover", help="Remover posição (fechou a operação)")
    p_rem.add_argument("ticker")

    p_list = sub.add_parser("listar", help="Listar posições abertas")

    p_status = sub.add_parser("status", help="Mostrar gestão de uma posição com preço atual")
    p_status.add_argument("ticker")

    args = parser.parse_args()

    if args.comando == "adicionar":
        posicao = adicionar_posicao(
            args.ticker, args.direcao, args.preco_entrada,
            args.stop, args.alvo, args.quantidade, args.prazo_maximo
        )
        print(f"✅ Posição registrada: {posicao['ticker']} ({posicao['direcao']})")
        print(f"   Entrada {posicao['preco_entrada']} · Stop {posicao['stop']} · Alvo {posicao['alvo']}")

    elif args.comando == "remover":
        if remover_posicao(args.ticker):
            print(f"🗑️ Posição {args.ticker.upper()} removida (operação fechada).")
        else:
            print(f"⚠️ Posição {args.ticker.upper()} não encontrada.")

    elif args.comando == "listar":
        posicoes = carregar_posicoes()
        if not posicoes:
            print("Nenhuma posição aberta.")
        for ticker, p in posicoes.items():
            print(f"  {ticker} ({p['direcao']}) entrada {p['preco_entrada']} stop {p['stop']} alvo {p['alvo']}")

    elif args.comando == "status":
        posicoes = carregar_posicoes()
        ticker = args.ticker.upper()
        if ticker not in posicoes:
            print(f"⚠️ Posição {ticker} não encontrada.")
            sys.exit(1)
        if posicoes[ticker].get("tipo_operacao") == "trava":
            print(formatar_gestao_todas({ticker: posicoes[ticker]}, {}))
            return
        try:
            import yfinance as yf
            import pandas as pd
            df = yf.download(f"{ticker}.SA", period="5d", interval="1d", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.rename(columns=str.lower)
            preco = float(df["close"].iloc[-1])
        except Exception as e:
            print(f"⚠️ Não consegui buscar o preço atual: {e}")
            preco = float(input("Digite o preço atual: "))

        print(formatar_gestao_todas({ticker: posicoes[ticker]}, {ticker: preco}))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
