"""
Servidor 24/7 para o robô B3-bot — roda continuamente (Replit/Render/Railway)
e responde comandos via HTTP em tempo real (sem delay de 5 min do GitHub Actions).

Endpoints:
  GET  /health            -> verificação de saúde
  POST /comando           -> processa um comando (ex: "trava compra 10.86 0.22 11.56 0.09")
  POST /comando          corpo: {"texto": "..."}

Respostas são em JSON. O site Lovable chama esses endpoints.

USO:
    python servidor_api.py          # porta da env PORT ou 8080
"""

import json
import logging
import os

from flask import Flask, request, jsonify

import config
from telegram_bot import processar_comando

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    """Endpoint simples pra saber se o servidor está de pé."""
    return jsonify({"status": "ok", "robô": "B3-bot ativo"})


@app.route("/comando", methods=["POST"])
def comando():
    """
    Processa um comando do site.
    Corpo: {"texto": "/trava compra 10.86 0.22 11.56 0.09"}
    Retorna: {"resposta": "...", "ok": true}
    """
    try:
        dados = request.get_json(force=True)
    except Exception:
        dados = {}

    texto = dados.get("texto", "").strip()
    if not texto:
        return jsonify({"ok": False, "resposta": "Texto vazio. Envie um comando."})

    token = getattr(config, "TELEGRAM_TOKEN", "")
    chat_id = str(getattr(config, "TELEGRAM_CHAT_ID", ""))

    # Reusa a MESMA lógica de comandos do Telegram
    resposta = processar_comando(token, chat_id, texto)
    if resposta is None:
        return jsonify({
            "ok": False,
            "resposta": "Comando não reconhecido. Envie /ajuda pra ver as opções."
        })

    return jsonify({"ok": True, "resposta": resposta})


@app.route("/ajuda", methods=["GET"])
def ajuda():
    """Lista os comandos disponíveis (sem precisar de POST)."""
    token = getattr(config, "TELEGRAM_TOKEN", "")
    chat_id = str(getattr(config, "TELEGRAM_CHAT_ID", ""))
    return jsonify({"ok": True, "resposta": processar_comando(token, chat_id, "/ajuda")})


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "robô": "B3-bot servidor",
        "endpoints": ["/health", "/comando", "/ajuda"],
        "uso": 'POST /comando com {"texto": "/trava compra 10.86 0.22 11.56 0.09"}'
    })


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", "8080"))
    logger.info("B3-bot servidor rodando na porta %s", porta)
    app.run(host="0.0.0.0", port=porta)
