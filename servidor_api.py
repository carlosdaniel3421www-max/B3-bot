"""
Servidor 24/7 com webhook Telegram — roda no Render, Replit ou qualquer servidor.
Responde comandos INSTANTANEAMENTE (sem delay de 5 min do GitHub Actions).

Configuração (secrets no Render/Replit):
    TELEGRAM_TOKEN      (obrigatório) — token do seu bot
    TELEGRAM_CHAT_ID    (obrigatório) — seu chat id (só você pode usar)
    GEMINI_API_KEY      (opcional, para IA)
    CARLOS              (opcional, para Nemotron)
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
CHAT_ID_AUTORIZADO = str(getattr(config, "TELEGRAM_CHAT_ID", ""))

if not TOKEN:
    logger.error("TELEGRAM_TOKEN não configurado! Configure como secret no Render.")
    sys.exit(1)

if not CHAT_ID_AUTORIZADO:
    logger.warning("TELEGRAM_CHAT_ID não configurado! O servidor responderá QUALQUER pessoa.")
    logger.warning("Para segurança, configure TELEGRAM_CHAT_ID como secret no Render.")

WEBHOOK_URL = ""  # será preenchido ao iniciar


def _baixar_estado_do_github():
    """
    Na inicialização, baixa o posicoes.json do GitHub para restaurar o estado.
    O disco do Render é efêmero — sem isso, reinícios perdem as posições.
    """
    import requests as req

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        logger.info("GITHUB_TOKEN ausente — usando estado local (se houver).")
        return

    repo = "carlosdaniel3421www-max/B3-bot"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

    for arquivo in ("posicoes.json", "propostas.json"):
        url = f"https://api.github.com/repos/{repo}/contents/{arquivo}"
        try:
            resp = req.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                import base64
                conteudo = base64.b64decode(resp.json().get("content", "")).decode("utf-8")
                # Só restaura se o conteúdo baixado for um JSON válido não-vazio.
                # Evita sobrescrever o estado local com um arquivo vazio/corrompido
                # se o GitHub ainda não tiver processado o commit mais recente.
                import json as _json
                dados = _json.loads(conteudo)
                if dados is None:
                    logger.warning("Ignorando %s: conteúdo vazio no GitHub", arquivo)
                    continue
                with open(arquivo, "w", encoding="utf-8") as f:
                    f.write(conteudo)
                logger.info("Estado restaurado do GitHub: %s", arquivo)
            elif resp.status_code == 404:
                logger.info("Arquivo %s ainda não existe no GitHub — estado local mantido", arquivo)
        except Exception as e:
            logger.warning("Falha ao baixar %s do GitHub: %s", arquivo, e)


def _sanitizar_html(texto: str) -> str:
    """
    Escapa '<' e '>' que NÃO fazem parte de tags HTML permitidas pelo
    Telegram. Evita que conteúdo da IA (com <, >) quebre a formatação.
    """
    if not texto:
        return texto
    import re
    # Tags permitidas pelo Telegram (parse_mode=HTML)
    tags_permitidas = re.compile(
        r"(</?(?:b|strong|i|em|u|s|code|pre|tg-spoiler|a)\b[^>]*>)",
        re.IGNORECASE,
    )
    partes = tags_permitidas.split(texto)
    saida = []
    for i, parte in enumerate(partes):
        if i % 2 == 1:
            saida.append(parte)  # tag permitida — mantém como está
        else:
            saida.append(parte.replace("<", "&lt;").replace(">", "&gt;"))
    return "".join(saida)


def _responder_telegram(chat_id, texto):
    """Envia resposta pro Telegram via API."""
    import requests
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={
            "chat_id": chat_id,
            "text": _sanitizar_html(texto),
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

    # Filtro de segurança: só responde pro dono do bot
    if CHAT_ID_AUTORIZADO and chat_id != CHAT_ID_AUTORIZADO:
        logger.info("Ignorado comando de chat não autorizado: %s", chat_id)
        return jsonify({"ok": True})

    # Processa o comando (reusa toda a lógica do Telegram)
    logger.info("Comando recebido: %s", texto)
    try:
        resposta = processar_comando(TOKEN, chat_id, texto)
    except Exception as e:
        # Nunca deixa um erro de processamento virar silêncio pro usuário
        logger.exception("Erro inesperado ao processar comando %s: %s", texto, e)
        resposta = "⚠️ Erro interno ao processar o comando. Tente novamente em instantes."

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

    # Detecta a URL pública (Render, Replit, ou manual)
    dominio = (
        os.environ.get("RENDER_EXTERNAL_URL")       # Render
        or os.environ.get("REPLIT_DEV_DOMAIN")       # Replit
        or os.environ.get("WEBHOOK_URL")             # manual (configurar no secret)
    )
    if dominio:
        # Remove barra no final se tiver
        dominio = dominio.rstrip("/")
        if "/webhook" not in dominio:
            WEBHOOK_URL = f"{dominio}/webhook"
        else:
            WEBHOOK_URL = dominio
        logger.info("URL detectada: %s", WEBHOOK_URL)
    else:
        logger.warning("URL do servidor não detectada. Configure manualmente.")
        logger.info("Após rodar, execute este comando no terminal (substitua SUA_URL):")
        logger.info("  curl -X POST https://api.telegram.org/bot%s/setWebhook?url=SUA_URL/webhook", TOKEN)
        return False

    # Remove webhook antigo e registra o novo
    import requests
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
    # Restaura posições/propostas do GitHub antes de atender comandos
    _baixar_estado_do_github()
    _configurar_webhook()

    porta = int(os.environ.get("PORT", "8080"))
    logger.info("Servidor rodando na porta %s", porta)
    app.run(host="0.0.0.0", port=porta)