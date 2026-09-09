# -*- coding: utf-8 -*-
"""
Diário de sinais — registra cada sinal emitido pelo robô (ticker, direção,
score, preço e data) e compara com o fechamento da N-esima sessão posterior
para medir acerto direcional, não PnL de operações com stop/alvo ou opções.

Isso é DIFERENTE do backtest (que é retroativo): o diário é PROSPECTIVO,
medindo o robô rodando de verdade, dia após dia.

Formato do arquivo sinais.json:
    {
        "PETR4": [
            {"data": "2026-08-20", "direcao": "compra", "score": 9,
             "preco": 43.11, "resultado": null}
        ]
    }

    - `resultado`: "acerto" ou "erro" direcional (empate conta como erro).
    - Registros antigos "lucro"/"prejuizo" são preservados, mas não entram
      na taxa de janela fixa, pois não têm fechamento histórico validado.
"""

import json
import logging
import math
import os
import tempfile
import threading
from datetime import date
from functools import wraps
from html import escape
from numbers import Real

import pandas as pd

CAMINHO_SINAIS = "sinais.json"

DIAS_AVALIACAO_PADRAO = 10  # quantos dias úteis depois de medir o sinal
_persistencia_lock = threading.RLock()


def _serializar(funcao):
    """Serializa threads locais, nao processos/hosts nem snapshots externos."""
    @wraps(funcao)
    def executar(*args, **kwargs):
        with _persistencia_lock:
            return funcao(*args, **kwargs)
    return executar


def _validar_estrutura(sinais):
    if not isinstance(sinais, dict) or not all(
        isinstance(ticker, str) and ticker.strip() and isinstance(registros, list)
        and all(isinstance(sinal, dict) for sinal in registros)
        for ticker, registros in sinais.items()
    ):
        raise ValueError("Sinais devem ser um mapa de listas de registros")


def _preco_valido(preco):
    return (isinstance(preco, Real) and not isinstance(preco, bool)
            and math.isfinite(preco) and preco > 0)


def carregar_sinais(arquivo: str = CAMINHO_SINAIS) -> dict:
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
            sinais = json.load(f, object_pairs_hook=sem_duplicatas, parse_constant=constante_invalida)
        _validar_estrutura(sinais)
        return sinais
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        raise ValueError(f"Nao foi possivel ler {arquivo}; arquivo preservado") from exc


@_serializar
def salvar_sinais(sinais: dict, arquivo: str = CAMINHO_SINAIS):
    _validar_estrutura(sinais)
    conteudo = json.dumps(sinais, ensure_ascii=False, indent=2, allow_nan=False)
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


@_serializar
def registrar_sinal(ticker: str, direcao: str, score: int, preco: float,
                    arquivo: str = CAMINHO_SINAIS) -> dict:
    """
    Registra um sinal emitido hoje (sem resultado ainda).
    Se o mesmo ticker já teve um sinal HOJE, não duplica.
    """
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("Ticker invalido")
    ticker = ticker.strip().upper().removesuffix(".SA")
    if not ticker or direcao not in ("compra", "venda"):
        raise ValueError("Ticker/direcao invalido")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 10:
        raise ValueError("Score deve ser inteiro de 0 a 10")
    if not _preco_valido(preco) or round(preco, 2) <= 0:
        raise ValueError("Preco deve ser finito e positivo em centavos")
    sinais = carregar_sinais(arquivo)
    hoje = date.today().isoformat()

    registros = sinais.setdefault(ticker, [])
    for registro in registros:
        if registro.get("data") == hoje:
            return registro  # Primeiro sinal do dia prevalece, mesmo com lista fora de ordem.

    sinal = {
        "data": hoje,
        "direcao": direcao,
        "score": score,
        "preco": round(preco, 2),
        "resultado": None,
    }
    registros.append(sinal)
    salvar_sinais(sinais, arquivo)
    return sinal


def avaliar_sinal(sinal: dict, preco_atual: float) -> str:
    """
    Compara a direção com o preço fornecido, sem afirmar uma janela temporal.
    Não altera o sinal nem simula PnL, stop/alvo ou custos.
    """
    if not isinstance(sinal, dict):
        return "indefinido"
    if sinal.get("resultado") in ("acerto", "erro", "lucro", "prejuizo"):
        return sinal["resultado"]

    preco_entrada = sinal.get("preco", 0)
    if not _preco_valido(preco_entrada) or not _preco_valido(preco_atual):
        return "indefinido"

    if sinal.get("direcao") == "compra":
        resultado = "acerto" if preco_atual > preco_entrada else "erro"
    elif sinal.get("direcao") == "venda":
        resultado = "acerto" if preco_atual < preco_entrada else "erro"
    else:
        resultado = "indefinido"

    return resultado


def buscar_historico_fechamentos(ticker: str, inicio: date, fim: date) -> pd.Series:
    """Fronteira de rede mockável: Close em [inicio, fim), auto_adjust=False.

    Depende da integridade das sessões fornecidas pelo Yahoo; não reconcilia
    eventos corporativos com o preço registrado na emissão do sinal.
    """
    import yfinance as yf

    simbolo = ticker.upper()
    if not simbolo.endswith(".SA"):
        simbolo += ".SA"
    df = yf.download(simbolo, start=inicio.isoformat(), end=fim.isoformat(),
                     interval="1d", auto_adjust=False, progress=False)
    if df.empty:
        return pd.Series(dtype=float)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"]


@_serializar
def atualizar_resultados(precos: dict, dias_min: int = DIAS_AVALIACAO_PADRAO,
                         arquivo: str = CAMINHO_SINAIS) -> dict:
    """
    Avalia no fechamento da `dias_min`-esima sessão ESTRITAMENTE após o sinal.
    Mantém a interface do relatório: `precos` não fornece a janela histórica
    e seus valores não são usados como fechamento. Busca todos os tickers
    pendentes, inclusive os que saíram da watchlist. Sem histórico, aguarda.
    Exclui a sessão de hoje para nunca usar uma barra ainda em formação.
    O lock inclui a busca: serializa threads locais, nao processos distintos.
    Datas de emissao/hoje usam o fuso do processo (configure America/Sao_Paulo).
    """
    if isinstance(dias_min, bool) or not isinstance(dias_min, int) or dias_min < 1:
        raise ValueError("dias_min deve ser um inteiro positivo (sessões).")
    sinais = carregar_sinais(arquivo)
    mudou = False
    hoje = date.today()

    for ticker, registros in list(sinais.items()):
        pendentes = []
        for sinal in registros:
            if sinal.get("resultado"):
                continue
            try:
                data_sinal = date.fromisoformat(sinal["data"])
                if sinal["data"] != data_sinal.isoformat():
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            if data_sinal < hoje:
                pendentes.append((sinal, data_sinal))
        if not pendentes:
            continue

        try:
            historico = buscar_historico_fechamentos(ticker, min(d for _, d in pendentes), hoje)
            if not isinstance(historico, pd.Series) or pd.api.types.is_numeric_dtype(historico.index.dtype):
                raise ValueError("Historico deve ser Series com indice temporal")
            historico = historico.copy()
            indice = pd.to_datetime(historico.index)
            if indice.hasnans:
                raise ValueError("Historico contem data ausente")
            if indice.tz is not None:
                indice = indice.tz_convert("America/Sao_Paulo")
            historico.index = indice.date
            historico = historico.sort_index(kind="stable")
            # Duplicatas não representam sessões adicionais. Não eliminar NaNs:
            # isso deslocaria a N-esima sessão para uma data incorreta.
            if historico.groupby(level=0).nunique(dropna=False).gt(1).any():
                raise ValueError("Fechamentos conflitantes na mesma sessao")
            historico = historico[~historico.index.duplicated(keep="last")]
            historico = historico[historico.index < hoje]
        except Exception as exc:
            logging.warning("Histórico indisponível para avaliar %s: %s", ticker, exc)
            continue

        for sinal, data_sinal in pendentes:
            sessoes = historico[historico.index > data_sinal]
            if len(sessoes) < dias_min:
                continue
            try:
                fechamento = sessoes.iloc[dias_min - 1]
                if not _preco_valido(fechamento):
                    continue
                fechamento = float(fechamento)
                resultado = avaliar_sinal(sinal, fechamento)
            except (TypeError, ValueError):
                continue
            if resultado == "indefinido":
                continue
            sinal.update({
                "resultado": resultado,
                "metodo_avaliacao": "fechamento_n_sessoes",
                "sessoes_avaliacao": dias_min,
                "data_avaliacao": sessoes.index[dias_min - 1].isoformat(),
                "preco_avaliacao": fechamento,
            })
            mudou = True

    if mudou:
        salvar_sinais(sinais, arquivo)
    return sinais


def resumo_desempenho(sinais: dict = None) -> dict:
    """
    Taxa direcional de sinais com janela histórica validada (não PnL).
    Confia no marcador escrito pelo avaliador, sem revalidar historico remoto;
    agrega diferentes N e sinais correlacionados, sem inferencia estatistica.
    """
    sinais = sinais if sinais is not None else carregar_sinais()
    _validar_estrutura(sinais)

    total = 0
    acertos = 0
    legados = 0
    por_direcao = {"compra": {"total": 0, "acertos": 0},
                   "venda": {"total": 0, "acertos": 0}}

    for registros in sinais.values():
        for sinal in registros:
            if not sinal.get("resultado"):
                continue
            if sinal.get("metodo_avaliacao") != "fechamento_n_sessoes":
                legados += 1
                continue
            if sinal["resultado"] not in ("acerto", "erro") or sinal.get("direcao") not in ("compra", "venda"):
                continue
            total += 1
            direcao = sinal.get("direcao", "")
            if sinal["resultado"] == "acerto":
                acertos += 1
                if direcao in por_direcao:
                    por_direcao[direcao]["acertos"] += 1
            if direcao in por_direcao:
                por_direcao[direcao]["total"] += 1

    return {
        "total_avaliados": total,
        "total_sem_janela_validada": legados,
        "acertos": acertos,
        "taxa_acerto_pct": round((acertos / total) * 100, 1) if total > 0 else 0,
        "por_direcao": por_direcao,
    }


def formatar_resumo_desempenho() -> str:
    """Formata o resumo de desempenho para envio no Telegram."""
    sinais = carregar_sinais()
    if not sinais:
        return "📊 <b>Diário de sinais</b>\nAinda não há sinais registrados. O robô registra automaticamente cada ENTRAR emitido."

    resumo = resumo_desempenho(sinais)

    linhas = ["📊 <b>Acerto direcional dos sinais</b>",
              f"Fechamento da N-esima sessão após o sinal (padrão: {DIAS_AVALIACAO_PADRAO}).",
              "A taxa agrega as janelas registradas, que podem ter N diferentes.",
              "Não é PnL: não considera stop, alvo, custos ou prêmio de opções."]

    # Sinais pendentes de avaliação
    pendentes = 0
    for registros in sinais.values():
        pendentes += sum(1 for s in registros if not s.get("resultado"))

    if resumo["total_avaliados"] > 0:
        linhas.append(
            f"🎯 Taxa de acerto direcional: <b>{resumo['taxa_acerto_pct']}%</b> "
            f"({resumo['acertos']}/{resumo['total_avaliados']} sinais avaliados)"
        )
        c = resumo["por_direcao"]["compra"]
        v = resumo["por_direcao"]["venda"]
        if c["total"] > 0:
            linhas.append(f"  • Compras: {c['acertos']}/{c['total']} certas")
        if v["total"] > 0:
            linhas.append(f"  • Vendas: {v['acertos']}/{v['total']} certas")
    else:
        linhas.append("Ainda não há sinais com resultado avaliado (aguardando janela de avaliação).")

    if pendentes > 0:
        linhas.append(f"⏳ {pendentes} sinal(is) aguardando avaliação.")
    if resumo["total_sem_janela_validada"]:
        linhas.append(f"{resumo['total_sem_janela_validada']} resultado(s) legado(s) sem janela validada, fora da taxa.")

    # Últimos sinais por ativo
    linhas.append("\n<i>Últimos sinais:</i>")
    for ticker, registros in list(sinais.items())[:15]:
        if not registros:
            continue
        s = registros[-1]
        emoji = {"acerto": "✅", "erro": "❌", "lucro": "➖", "prejuizo": "➖", "indefinido": "➖"}.get(str(s.get("resultado")), "⏳")
        detalhe = f"{ticker} ({s.get('direcao')}) score {s.get('score')} em {s.get('data')}"
        linhas.append(f"  {emoji} {escape(detalhe)}")

    return "\n".join(linhas)
