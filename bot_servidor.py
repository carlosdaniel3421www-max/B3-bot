"""
Bot do servidor — roda 24h na nuvem. Substitui o GitHub Actions pra dar
resposta IMEDIATA (sem delay de 5 min).

Faz duas coisas ao mesmo tempo:
  1. Atende seus comandos no Telegram em tempo real (long-polling):
       /registrar TICKER, /registrar TICKER DIRECAO PRECO STOP ALVO,
       /remover TICKER, /posicoes, /status TICKER, /propostas, /ajuda
  2. Dispara os relatórios nos horários certos (dias úteis):
       09:37 BRT  -> relatório da manhã
       13:13 BRT  -> relatório da tarde (prazo curto)

Para rodar na nuvem (Railway/Render/Fly ou um VPS):
    env: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, OPLAB_TOKEN
    comando: python bot_servidor.py
"""

import logging
import os
import threading
import time
from datetime import datetime

import schedule

import config
from telegram_bot import buscar_updates, processar_comando, responder, _ler_offset, _salvar_offset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

ULTIMO_OFFSET = _ler_offset()


def tratar_update(update: dict):
    """Processa um update do Telegram e responde se for um comando nosso."""
    global ULTIMO_OFFSET

    update_id = update.get("update_id", 0)
    if update_id > ULTIMO_OFFSET:
        ULTIMO_OFFSET = update_id

    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    msg_chat = str(msg.get("chat", {}).get("id", ""))
    if msg_chat != str(config.TELEGRAM_CHAT_ID):
        return  # ignora mensagens de outros chats

    texto = (msg.get("text") or "").strip()
    if not texto:
        return

    resposta = processar_comando(config.TELEGRAM_TOKEN, msg_chat, texto)
    if resposta:
        responder(config.TELEGRAM_TOKEN, msg_chat, resposta)
        print(f"[BOT] {texto} -> resposta enviada")


def loop_comandos():
    """Loop contínuo: busca mensagens novas em tempo real e responde na hora."""
    global ULTIMO_OFFSET
    print("[BOT] Atendente de comandos iniciado (long-polling).")
    while True:
        try:
            updates = buscar_updates(config.TELEGRAM_TOKEN, ULTIMO_OFFSET, timeout=50)
            for update in updates:
                tratar_update(update)
            _salvar_offset(ULTIMO_OFFSET)
        except Exception as e:
            logging.warning("Erro no loop de comandos: %s", e)
        time.sleep(1)


def _dia_util() -> bool:
    return datetime.now().weekday() < 5


def rodar_relatorio_manha():
    if not _dia_util():
        return
    print(f"[REPORTE] Rodando relatório da manhã {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    try:
        from relatorio_diario import gerar_e_enviar_relatorio
        gerar_e_enviar_relatorio(
            watchlist=config.WATCHLIST,
            periodo=config.PERIODO_HISTORICO,
            nivel_detalhe=config.NIVEL_DETALHE,
            arquivo_estado="estado.json",
            titulo="Relatório B3 — Manhã",
        )
    except Exception as e:
        logging.error("Falha no relatório da manhã: %s", e, exc_info=True)


def rodar_relatorio_tarde():
    if not _dia_util():
        return
    print(f"[REPORTE] Rodando relatório da tarde {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    try:
        from relatorio_tarde import gerar_e_enviar_relatorio_tarde
        gerar_e_enviar_relatorio_tarde()
    except Exception as e:
        logging.error("Falha no relatório da tarde: %s", e, exc_info=True)


def loop_relatorios():
    """Agenda os relatórios nos horários (hora local do servidor em BRT)."""
    print("[REPORTE] Agenda de relatórios iniciada (09:37 e 13:13 BRT, dias úteis).")
    schedule.every().day.at("09:37").do(rodar_relatorio_manha)
    schedule.every().day.at("13:13").do(rodar_relatorio_tarde)

    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logging.warning("Erro no loop de relatórios: %s", e)
        time.sleep(30)


def main():
    if config.TELEGRAM_TOKEN.startswith("COLOQUE") or config.TELEGRAM_CHAT_ID.startswith("COLOQUE"):
        print("ERRO: configure TELEGRAM_TOKEN e TELEGRAM_CHAT_ID (variáveis de ambiente).")
        return

    t_comandos = threading.Thread(target=loop_comandos, daemon=True)
    t_comandos.start()

    t_relatorios = threading.Thread(target=loop_relatorios, daemon=True)
    t_relatorios.start()

    print("[BOT] Servidor rodando 24h. Aguardando comandos...")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()