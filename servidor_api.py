"""
Servidor 24/7 para o robô B3-bot — roda no Replit continuamente.
Usa WEBHOOK do Telegram (resposta instantânea, sem delay de 5 min).

Quando você manda um comando no Telegram, o Telegram chama este servidor
na hora, o robô processa e responde imediatamente.

USO (no Replit):
    python servidor_api.py

Configuração (secrets no Replit):
    TELEGRAM_TOKEN    (obrigatório)
    GEMINI_API_KEY    (opcional, para IA)
    CARLOS            (opcional, para Nemotron)
"""

import json
import logging
import os
import sys

from flask import Flask, request, jsonify

import config
from telegram_bot import processar_comando

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

TOKEN = getattr(config, "TELEGRAM_TOKEN", "")
if not TOKEN:
    logger.error("TELEGRAM_TOKEN não configurado! Configure como secret no Replit.")
    sys.exit(1)

WEBHOOK_URL = ""  # será preenchido ao iniciar


def _responder_telegram(chat_id, texto):
    """Envia resposta pro Telegram via API."""
    import requests
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={
            "chat_id": chat_id,
            "text": texto,
            "parse_mode": "HTML",
        })
        if not r.ok:
            logger.warning("Falha ao responder: %s", r.text)
    except Exception as e:
        logger.warning("Erro ao responder: %s", e)


@app.route("/webhook", methods=["POST"])
def webhook():
    """Recebe updates do Telegram em tempo real (webhook)."""
    try:
        update = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False}), 400

    if not update:
        return jsonify({"ok": False}), 400

    # Extrai mensagem do update
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return jsonify({"ok": True})  # ignora outros tipos de update

    chat_id = str(msg.get("chat", {}).get("id", ""))
    texto = msg.get("text") or ""

    if not texto or not chat_id:
        return jsonify({"ok": True})

    # Processa o comando (reusa toda a lógica do Telegram)
    logger.info("Comando recebido: %s", texto)
    resposta = processar_comando(TOKEN, chat_id, texto)

    if resposta:
        _responder_telegram(chat_id, resposta)
    else:
        _responder_telegram(chat_id, "❓ Não entendi. Use /ajuda pra ver os comandos.")

    return jsonify({"ok": True})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "webhook": bool(WEBHOOK_URL)})


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "robô": "B3-bot servidor (webhook Telegram)",
        "webhook": WEBHOOK_URL or "não configurado",
        "health": "/health",
    })


def _configurar_webhook():
    """Registra o webhook no Telegram (substitui polling)."""
    global WEBHOOK_URL
    import requests

    # Descobre a URL pública do Replit
    # O Replit disponibiliza a URL em REPLIT_DEV_DOMAIN
    dominio = os.environ.get("REPLIT_DEV_DOMAIN")
    if dominio:
        WEBHOOK_URL = f"https://{dominio}/webhook"
    else:
        # Fallback: tenta detectar
        logger.warning("REPLIT_DEV_DOMAIN não encontrado. Configure manualmente.")
        logger.info("Após rodar, execute:")
        logger.info("  curl -X POST https://api.telegram.org/bot%s/setWebhook?url=SUA_URL/webhook", TOKEN)
        return False

    # Remove webhook antigo e registra o novo
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}"
    try:
        r = requests.get(url)
        data = r.json()
        if data.get("ok"):
            logger.info("Webhook registrado: %s", WEBHOOK_URL)
            return True
        else:
            logger.warning("Falha ao registrar webhook: %s", data)
            return False
    except Exception as e:
        logger.warning("Erro ao registrar webhook: %s", e)
        return False


if __name__ == "__main__":
    logger.info("Iniciando servidor B3-bot...")
    _configurar_webhook()

    porta = int(os.environ.get("PORT", "8080"))
    logger.info("Servidor rodando na porta %s", porta)
    app.run(host="0.0.0.0", port=porta)