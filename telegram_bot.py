"""
Robô do Telegram — o "atendente" que lê seus comandos no chat e responde.

Quando o relatório diário propõe uma entrada (🟢 ENTRAR), você decide:
   - Manda "/registrar TICKER"  -> o robô registra a posição com o plano
                                    (entrada/stop/alvo) que ele sugeriu
   - Não manda nada             -> a proposta é ignorada, nada é registrado

Comandos disponíveis:
   /registrar TICKER      Registra a posição a partir da proposta do relatório
   /registrar TICKER QTD  Idem, informando a quantidade de ações
   /remover TICKER        Remove uma posição (você fechou a operação)
   /posicoes              Mostra TODAS as posições abertas + gestão (proteger/sair)
   /status TICKER         Mostra a gestão de UMA posição com o preço atual

Este script é chamado pelo GitHub Actions a cada poucos minutos. Ele só
processa mensagens novas (usa offset do Telegram) e as responde no chat.
"""

import json
import logging
import sys

import requests

import config
from diario_sinais import formatar_resumo_desempenho
from posicoes import (
    adicionar_posicao, carregar_posicoes, carregar_propostas, formatar_gestao_todas,
    gerar_gestao_posicao, remover_posicao, registrar_da_proposta,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CAMINHO_OFFSET = "telegram_offset.json"


def _ler_offset() -> int:
    try:
        with open(CAMINHO_OFFSET, "r", encoding="utf-8") as f:
            return json.load(f).get("last_update_id", 0)
    except Exception:
        return 0


def _salvar_offset(update_id: int):
    with open(CAMINHO_OFFSET, "w", encoding="utf-8") as f:
        json.dump({"last_update_id": update_id}, f)


def buscar_updates(token: str, offset: int, timeout: int = 30) -> list:
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        r = requests.get(url, params={"offset": offset + 1, "timeout": timeout}, timeout=timeout + 10)
        if not r.ok:
            logging.warning("getUpdates falhou: %s", r.text)
            return []
        return r.json().get("result", [])
    except Exception as e:
        logging.warning("Erro ao buscar updates: %s", e)
        return []


def responder(token: str, chat_id, texto: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": chat_id, "text": texto, "parse_mode": "HTML"})
        if not r.ok:
            logging.warning("Falha ao responder: %s", r.text)
    except Exception as e:
        logging.warning("Erro ao responder: %s", e)


def _precos_posicoes(posicoes: dict) -> dict:
    """Busca preços atuais de todas as posições (yfinance) pra gestão."""
    import pandas as pd
    import yfinance as yf

    precos = {}
    tickers = list(posicoes.keys())
    if not tickers:
        return precos
    try:
        df = yf.download(
            [f"{t}.SA" for t in tickers], period="5d", interval="1d",
            auto_adjust=True, progress=False, group_by="ticker",
        )
        for t in tickers:
            try:
                d = df.get(t) or df.get(f"{t}.SA")
                if d is None:
                    continue
                if isinstance(d.columns, pd.MultiIndex):
                    d.columns = d.columns.get_level_values(0)
                d = d.rename(columns=str.lower)
                precos[t] = float(d["close"].iloc[-1])
            except Exception:
                precos[t] = None
    except Exception as e:
        logging.warning("Falha ao buscar preços: %s", e)
    return precos


def processar_comando(token: str, chat_id, texto: str) -> str:
    """Processa um comando e devolve a resposta a enviar."""
    partes = texto.strip().split()
    comando = partes[0].lower().replace("@", "")
    args = partes[1:]

    if comando in ("/registrar", "/adicionar"):
        if not args:
            return "Uso: /registrar TICKER (usa a proposta do robô)\nou: /registrar TICKER DIRECAO PRECO STOP ALVO (registro manual de qualquer operação)"
        ticker = args[0].upper()

        # Registro manual: /registrar PETR4 compra 43.11 40.50 48.22 [QTD]
        if len(args) >= 5:
            try:
                direcao = args[1].lower()
                if direcao not in ("compra", "venda"):
                    return "⚠️ Direção inválida. Use: /registrar TICKER compra PRECO STOP ALVO [QTD]\nou: /registrar TICKER venda PRECO STOP ALVO [QTD]"
                preco = float(args[2])
                stop = float(args[3])
                alvo = float(args[4])
                if preco <= 0 or stop <= 0 or alvo <= 0:
                    return "⚠️ Preços precisam ser números positivos."
                if direcao == "compra" and not (stop < preco < alvo):
                    return "⚠️ Na compra, stop < entrada < alvo. Ex: /registrar PETR4 compra 43.11 40.50 48.22"
                if direcao == "venda" and not (alvo < preco < stop):
                    return "⚠️ Na venda, alvo < entrada < stop. Ex: /registrar PETR4 venda 43.11 44.50 40.00"
                quantidade = int(args[5]) if len(args) > 5 else 0
                posicao = adicionar_posicao(ticker, direcao, preco, stop, alvo, quantidade=quantidade)
                return f"✅ <b>{ticker}</b> registrada manualmente ({posicao['direcao']}). Entrada R$ {posicao['preco_entrada']} · Stop R$ {posicao['stop']} · Alvo R$ {posicao['alvo']}. Agora acompanho todo dia."
            except ValueError as e:
                return f"⚠️ Valor inválido: {e}. Use números com ponto (.) como separador decimal. Ex: 43.11"
            except Exception as e:
                logging.warning("Erro ao registrar %s manualmente: %s", ticker, e)
                return f"⚠️ Erro ao registrar: {str(e)[:200]}"

        # Registro pela proposta do robô: /registrar TICKER [QTD]
        quantidade = int(args[1]) if len(args) > 1 else 0
        posicao, msg = registrar_da_proposta(ticker, quantidade=quantidade)
        return msg

    if comando in ("/remover", "/sair", "/fechar"):
        if not args:
            return "Uso: /remover TICKER"
        ticker = args[0].upper()
        if remover_posicao(ticker):
            return f"🗑️ {ticker} removida (operação fechada). Bom trade!"
        return f"⚠️ {ticker} não está registrada."

    if comando in ("/posicoes", "/posicao"):
        posicoes = carregar_posicoes()
        if not posicoes:
            return "📋 Nenhuma posição aberta. Quando o robô sugerir ENTRAR, responda /registrar TICKER."
        precos = _precos_posicoes(posicoes)
        return formatar_gestao_todas(posicoes, precos)

    if comando in ("/status",):
        if not args:
            return "Uso: /status TICKER"
        ticker = args[0].upper()
        posicoes = carregar_posicoes()
        if ticker not in posicoes:
            return f"⚠️ {ticker} não está registrada. Propostas disponíveis: {', '.join(carregar_propostas().keys()) or 'nenhuma'}."
        precos = _precos_posicoes({ticker: posicoes[ticker]})
        preco = precos.get(ticker)
        if preco is None:
            return f"⚠️ Preço de {ticker} indisponível no momento."
        gestao = gerar_gestao_posicao(posicoes[ticker], preco)
        from posicoes import formatar_gestao
        return formatar_gestao(gestao)

    if comando in ("/propostas", "/proposta"):
        propostas = carregar_propostas()
        if not propostas:
            return "Nenhuma proposta pendente. O robô propõe quando um ativo dá ENTRAR (score ≥ 8)."
        linhas = ["📌 <b>Propostas de entrada em aberto:</b>"]
        for t, p in propostas.items():
            linhas.append(
                f"  {t} ({p['direcao']}) entrada R$ {p['preco_entrada']} · "
                f"stop R$ {p['stop']} · alvo R$ {p['alvo']} — responda /registrar {t}"
            )
        return "\n".join(linhas)

    if comando in ("/sinais", "/desempenho", "/performance"):
        return formatar_resumo_desempenho()

    if comando in ("/help", "/ajuda", "/start", "/comandos"):
        return (
            "🤖 <b>Comandos do robô:</b>\n"
            "  /registrar TICKER — registra a posição que o robô propôs\n"
            "  /registrar TICKER DIRECAO PRECO STOP ALVO — registra QUALQUER\n"
            "    operação sua (ex: /registrar PETR4 compra 43.11 40.50 48.22)\n"
            "  /remover TICKER — remove a posição (fechou a operação)\n"
            "  /posicoes — mostra todas as posições + o que fazer hoje\n"
            "  /status TICKER — gestão de uma posição com preço atual\n"
            "  /propostas — propostas de entrada em aberto\n"
            "  /sinais — taxa de acerto dos sinais que o robô já emitiu"
        )

    return None


def main():
    token = getattr(config, "TELEGRAM_TOKEN", "")
    chat_id = str(getattr(config, "TELEGRAM_CHAT_ID", ""))
    if not token or not chat_id:
        logging.warning("TELEGRAM_TOKEN/TELEGRAM_CHAT_ID não configurados.")
        return

    offset = _ler_offset()
    updates = buscar_updates(token, offset)
    ultimo_id = offset

    for upd in updates:
        update_id = upd.get("update_id", 0)
        ultimo_id = max(ultimo_id, update_id)

        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            continue

        msg_chat = str(msg.get("chat", {}).get("id", ""))
        if msg_chat != chat_id:
            continue  # ignora mensagens de outros chats

        texto = msg.get("text") or ""
        if not texto:
            continue

        resposta = processar_comando(token, msg_chat, texto)
        if resposta:
            responder(token, msg_chat, resposta)
            logging.info("Comando %s processado para chat %s", texto, msg_chat)

    if ultimo_id != offset:
        _salvar_offset(ultimo_id)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()