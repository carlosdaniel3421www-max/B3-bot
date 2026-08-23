# -*- coding: utf-8 -*-
"""
Diário de sinais — registra cada sinal emitido pelo robô (ticker, direção,
score, preço e data) e permite comparar com o preço N dias depois pra medir
a taxa de acerto real ao longo do tempo.

Isso é DIFERENTE do backtest (que é retroativo): o diário é PROSPECTIVO,
medindo o robô rodando de verdade, dia após dia.

Formato do arquivo sinais.json:
    {
        "PETR4": [
            {"data": "2026-08-20", "direcao": "compra", "score": 9,
             "preco": 43.11, "resultado": null}
        ]
    }

    - `resultado` é preenchido depois (null até lá): "lucro" ou "prejuizo",
      comparando o preço atual com o preço do sinal após N dias.
"""

import json
import os
from datetime import date, timedelta

CAMINHO_SINAIS = "sinais.json"

DIAS_AVALIACAO_PADRAO = 10  # quantos dias úteis depois de medir o sinal


def carregar_sinais(arquivo: str = CAMINHO_SINAIS) -> dict:
    if not os.path.exists(arquivo):
        return {}
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def salvar_sinais(sinais: dict, arquivo: str = CAMINHO_SINAIS):
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(sinais, f, ensure_ascii=False, indent=2)


def registrar_sinal(ticker: str, direcao: str, score: int, preco: float,
                    arquivo: str = CAMINHO_SINAIS) -> dict:
    """
    Registra um sinal emitido hoje (sem resultado ainda).
    Se o mesmo ticker já teve um sinal HOJE, não duplica.
    """
    sinais = carregar_sinais(arquivo)
    hoje = date.today().isoformat()

    registros = sinais.setdefault(ticker, [])
    if registros and registros[-1].get("data") == hoje:
        return registros[-1]  # já registrou hoje, não duplica

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
    Define o resultado de um sinal: "lucro" se o preço atual está a favor
    da direção, "prejuizo" caso contrário. Preenche o campo `resultado`.
    """
    if sinal.get("resultado"):
        return sinal["resultado"]

    preco_entrada = sinal.get("preco", 0)
    if preco_entrada <= 0 or preco_atual <= 0:
        return "indefinido"

    if sinal.get("direcao") == "compra":
        resultado = "lucro" if preco_atual > preco_entrada else "prejuizo"
    elif sinal.get("direcao") == "venda":
        resultado = "lucro" if preco_atual < preco_entrada else "prejuizo"
    else:
        resultado = "indefinido"

    return resultado


def atualizar_resultados(precos: dict, dias_min: int = DIAS_AVALIACAO_PADRAO,
                         arquivo: str = CAMINHO_SINAIS) -> dict:
    """
    Percorre os sinais antigos (com pelo menos `dias_min` dias corridos) e
    preenche o resultado usando o preço atual. Retorna os sinais atualizados.
    """
    sinais = carregar_sinais(arquivo)
    mudou = False
    hoje = date.today()
    limite = hoje - timedelta(days=dias_min)

    for ticker, registros in list(sinais.items()):
        preco_atual = precos.get(ticker)
        if preco_atual is None:
            continue

        for sinal in registros:
            if sinal.get("resultado"):
                continue
            try:
                data_sinal = date.fromisoformat(sinal["data"])
            except (ValueError, KeyError):
                continue
            if data_sinal <= limite:
                sinal["resultado"] = avaliar_sinal(sinal, preco_atual)
                mudou = True

    if mudou:
        salvar_sinais(sinais, arquivo)
    return sinais


def resumo_desempenho(sinais: dict = None) -> dict:
    """
    Calcula a taxa de acerto a partir dos sinais já avaliados.
    """
    sinais = sinais if sinais is not None else carregar_sinais()

    total = 0
    acertos = 0
    por_direcao = {"compra": {"total": 0, "acertos": 0},
                   "venda": {"total": 0, "acertos": 0}}

    for registros in sinais.values():
        for sinal in registros:
            if not sinal.get("resultado"):
                continue
            if sinal["resultado"] not in ("lucro", "prejuizo"):
                continue
            total += 1
            direcao = sinal.get("direcao", "")
            if sinal["resultado"] == "lucro":
                acertos += 1
                if direcao in por_direcao:
                    por_direcao[direcao]["acertos"] += 1
            if direcao in por_direcao:
                por_direcao[direcao]["total"] += 1

    return {
        "total_avaliados": total,
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

    linhas = ["📊 <b>Desempenho dos sinais do robô</b>"]

    # Sinais pendentes de avaliação
    pendentes = 0
    for registros in sinais.values():
        pendentes += sum(1 for s in registros if not s.get("resultado"))

    if resumo["total_avaliados"] > 0:
        linhas.append(
            f"🎯 Taxa de acerto: <b>{resumo['taxa_acerto_pct']}%</b> "
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

    # Últimos sinais por ativo
    linhas.append("\n<i>Últimos sinais:</i>")
    for ticker, registros in list(sinais.items())[:15]:
        if not registros:
            continue
        s = registros[-1]
        emoji = {"lucro": "✅", "prejuizo": "❌", "indefinido": "➖"}.get(s.get("resultado"), "⏳")
        linhas.append(f"  {emoji} {ticker} ({s.get('direcao')}) score {s.get('score')} em {s.get('data')}")

    return "\n".join(linhas)
