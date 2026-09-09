"""
Servidor 24/7 com webhook Telegram — roda no Render, Replit ou qualquer servidor.
Recebe comandos sem o intervalo de polling do GitHub Actions.

Configuração (secrets no Render/Replit):
    TELEGRAM_TOKEN      (obrigatório) — token do seu bot
    TELEGRAM_CHAT_ID    (obrigatório) — seu chat id (só você pode usar)
    GEMINI_API_KEY      (opcional, para IA)
    CARLOS              (opcional, para Nemotron)

Deploy existente: render_start.sh e .replit executam este arquivo diretamente.
TELEGRAM_WEBHOOK_SECRET e opcional (1-256 caracteres A-Z, a-z, 0-9, _ e -).
Ao defini-lo, reinicie o servidor: setWebhook registra secret_token e /webhook
passa a exigir X-Telegram-Bot-Api-Secret-Token. Durante a troca, entregas com o
segredo anterior recebem 403 e o Telegram tenta novamente. Sem essa variavel,
o deploy legado continua funcionando, mas chat_id NAO autentica a origem:
quem souber o chat pode forjar updates. Chat ausente/invalido sempre bloqueia.
WEBHOOK_URL (HTTPS, com ou sem /webhook) prevalece sobre a URL do provedor.
REPLIT_DEV_DOMAIN pode ser apenas o hostname. Nao use polling simultaneamente.

Use uma unica instancia/processo. ACK 200 imediatamente apos enfileirar,
sem aguardar IA/envio. Fila em memoria: 32 aguardando e um unico worker de
negocio. Fila cheia retorna 503 antes de aceitar. Dedup atomico preserva
pendentes/em execucao e retém ate 100 updates, incluindo os concluidos.
Excecao de negocio gera um aviso, sem repetir a analise; envio tem no maximo
3 tentativas no worker, com intervalo de 1 segundo. Falha final e terminal,
sem reenfileirar em reentregas do Telegram enquanto estiver no cache.
NAO ha exactly-once nem fila duravel: reinicio perde comandos ja confirmados
e o cache de dedup; reentregas apos reinicio/expulsao podem duplicar efeitos.
Timeout de envio e resposta multipartes podem duplicar mensagens/blocos.
IA travada ocupa o unico worker, mas nao bloqueia ACK nem health HTTP.
/health e liveness local rapido, sem Telegram (usar no Render).
/ready valida startup e consulta getWebhookInfo (nao testa IA/persistencia).
Importar app via WSGI nao executa restauracao/registro e deixa ready indisponivel;
o comando de deploy suportado continua sendo python servidor_api.py.
GITHUB_TOKEN continua opcional; sem ele o disco efemero nao tem restauracao
remota. Com token, erro de download/validacao interrompe startup em vez de
servir estado possivelmente desatualizado; 404 mantem o comportamento legado.
"""

import hmac
import json
import logging
import os
import queue
import re
import tempfile
import threading
import time
from urllib.parse import urlsplit

from flask import Flask, request, jsonify

import config
from telegram_bot import processar_comando
from telegram_utils import enviar_mensagem

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

TOKEN = str(getattr(config, "TELEGRAM_TOKEN", "") or "").strip()
CHAT_ID_AUTORIZADO = str(getattr(config, "TELEGRAM_CHAT_ID", "") or "").strip()
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

WEBHOOK_URL = ""  # será preenchido ao iniciar
_estado_pronto = False

# Estados: pendente -> em_execucao -> enviado ou falha_envio (terminal).
_processados = {}
_MAX_RECENTES = 100
_comando_lock = threading.Lock()
_fila = queue.Queue(maxsize=32)
_worker = None
_MAX_TENTATIVAS_ENVIO = 3
_INTERVALO_RETRY = 1


def _configuracao_valida():
    return bool(
        TOKEN and TOKEN != "COLOQUE_SEU_TOKEN_AQUI"
        and re.fullmatch(r"-?[1-9][0-9]*", CHAT_ID_AUTORIZADO)
        and (not WEBHOOK_SECRET or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", WEBHOOK_SECRET))
    )


def _baixar_estado_do_github():
    """
    Na inicialização, baixa o posicoes.json do GitHub para restaurar o estado.
    O disco do Render é efêmero — sem isso, reinícios perdem as posições.
    """
    import requests as req

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        logger.info("GITHUB_TOKEN ausente — usando estado local (se houver).")
        return True

    repo = "carlosdaniel3421www-max/B3-bot"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

    sucesso = True
    for arquivo in ("posicoes.json", "propostas.json"):
        url = f"https://api.github.com/repos/{repo}/contents/{arquivo}"
        temporario = None
        try:
            resp = req.get(url, headers=headers, params={"ref": "main"}, timeout=(5, 15))
            if resp.status_code == 200:
                import base64
                conteudo = base64.b64decode(resp.json().get("content", "")).decode("utf-8")
                dados = json.loads(conteudo)
                if not isinstance(dados, dict) or not all(isinstance(v, dict) for v in dados.values()):
                    raise ValueError("Estado deve ser um mapa de registros JSON")
                # Mesmo diretorio para replace atomico; {} e um estado valido.
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=os.path.dirname(os.path.abspath(arquivo)),
                    prefix=f".{arquivo}.", suffix=".tmp", delete=False,
                ) as f:
                    temporario = f.name
                    json.dump(dados, f, ensure_ascii=False, allow_nan=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporario, arquivo)
                temporario = None
                logger.info("Estado restaurado do GitHub: %s", arquivo)
            elif resp.status_code == 404:
                logger.info("Arquivo %s ainda não existe no GitHub — estado local mantido", arquivo)
            else:
                sucesso = False
                logger.warning("Falha ao restaurar %s: HTTP %s", arquivo, resp.status_code)
        except Exception as e:
            sucesso = False
            logger.warning("Falha ao baixar %s do GitHub: %s", arquivo, type(e).__name__)
        finally:
            if temporario is not None:
                os.unlink(temporario)
    return sucesso


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
    return enviar_mensagem(TOKEN, chat_id, _sanitizar_html(texto))


def _consumir_fila(fila):
    """Unico consumidor; None encerra apos os itens anteriores (tambem em testes)."""
    while True:
        item = fila.get()
        try:
            if item is None:
                return
            update_id, chat_id, texto = item
            with _comando_lock:
                _processados[update_id] = "em_execucao"
            try:
                resposta = processar_comando(TOKEN, chat_id, texto)
                resposta = resposta or "Nao entendi. Use /ajuda para ver os comandos."
            except Exception as e:
                logger.error("Erro no update %s: %s", update_id, type(e).__name__)
                resposta = "Erro interno ao processar o comando. A analise nao sera repetida automaticamente."

            enviado = False
            for tentativa in range(_MAX_TENTATIVAS_ENVIO):
                try:
                    enviado = bool(_responder_telegram(chat_id, resposta))
                except Exception as e:
                    logger.warning("Falha no envio do update %s: %s", update_id, type(e).__name__)
                if enviado:
                    break
                if tentativa + 1 < _MAX_TENTATIVAS_ENVIO:
                    time.sleep(_INTERVALO_RETRY)
            with _comando_lock:
                _processados[update_id] = "enviado" if enviado else "falha_envio"
            if not enviado:
                logger.error("Envio do update %s esgotado; sem retry de negocio.", update_id)
        finally:
            fila.task_done()


@app.route("/webhook", methods=["POST"])
def webhook():
    """ACK apos enqueue atomico; duplicatas nao aguardam negocio/envio."""
    global _worker
    if not _configuracao_valida():
        return jsonify({"ok": False}), 503
    if WEBHOOK_SECRET and not hmac.compare_digest(
        request.headers.get("X-Telegram-Bot-Api-Secret-Token", "").encode("utf-8"),
        WEBHOOK_SECRET.encode("utf-8"),
    ):
        return jsonify({"ok": False}), 403
    try:
        update = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False}), 400

    if not isinstance(update, dict):
        return jsonify({"ok": False}), 400

    update_id = update.get("update_id")
    if type(update_id) is not int or update_id < 0:
        return jsonify({"ok": False}), 400

    # Extrai mensagem do update
    msg = update.get("message")
    if msg is None:
        return jsonify({"ok": True})  # ignora outros tipos de update
    if not isinstance(msg, dict) or not isinstance(msg.get("chat"), dict):
        return jsonify({"ok": False}), 400
    chat_id = str(msg["chat"].get("id", ""))
    texto = msg.get("text") or ""

    if not isinstance(texto, str):
        return jsonify({"ok": False}), 400

    if not texto or not chat_id:
        return jsonify({"ok": True})

    # Filtro de segurança: só responde pro dono do bot
    if chat_id != CHAT_ID_AUTORIZADO:
        logger.info("Ignorado comando de chat não autorizado: %s", chat_id)
        return jsonify({"ok": True})

    with _comando_lock:
        if update_id in _processados:
            return jsonify({"ok": True})
        concluido = None
        if len(_processados) >= _MAX_RECENTES:
            concluido = next((k for k, v in _processados.items() if v in {"enviado", "falha_envio"}), None)
            if concluido is None:
                return jsonify({"ok": False}), 503
        try:
            if _worker is None or not _worker.is_alive():
                _worker = threading.Thread(target=_consumir_fila, args=(_fila,), name="telegram-worker", daemon=True)
                _worker.start()
            _fila.put_nowait((update_id, chat_id, texto))
        except (queue.Full, RuntimeError):
            return jsonify({"ok": False}), 503
        # O worker so pode mudar o estado depois de liberarmos esta trava.
        _processados[update_id] = "pendente"
        if concluido is not None:
            del _processados[concluido]
    return jsonify({"ok": True})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/ready", methods=["GET"])
def ready():
    import requests

    pronto = False
    if _estado_pronto and _configuracao_valida() and WEBHOOK_URL:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo", timeout=(5, 15))
            data = r.json()
            pronto = bool(r.ok and data.get("ok") and data.get("result", {}).get("url") == WEBHOOK_URL)
        except (requests.RequestException, ValueError, AttributeError):
            pass
    return jsonify({"status": "ok" if pronto else "unavailable", "webhook": pronto}), 200 if pronto else 503


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "robô": "B3-bot servidor (webhook Telegram)",
        "webhook": WEBHOOK_URL or "não configurado",
        "health": "/health",
        "ready": "/ready",
    })


def _configurar_webhook():
    """Registra o webhook no Telegram (substitui polling)."""
    global WEBHOOK_URL
    import requests

    WEBHOOK_URL = ""
    if not _configuracao_valida():
        logger.error("Configure TELEGRAM_TOKEN, TELEGRAM_CHAT_ID e um segredo valido (se definido).")
        return False
    if not WEBHOOK_SECRET:
        logger.warning("Modo legado: sem TELEGRAM_WEBHOOK_SECRET, origem do webhook nao autenticada.")

    # Detecta a URL pública (Render, Replit, ou manual)
    dominio = (
        os.environ.get("WEBHOOK_URL")             # manual
        or os.environ.get("RENDER_EXTERNAL_URL")   # Render
        or os.environ.get("REPLIT_DEV_DOMAIN")       # Replit
    )
    if dominio:
        dominio = dominio.strip().rstrip("/")
        if "://" not in dominio:
            dominio = f"https://{dominio}"
        try:
            partes = urlsplit(dominio)
            partes.port  # valida portas malformadas antes de chamar requests
        except ValueError:
            logger.error("URL publica malformada.")
            return False
        if partes.scheme != "https" or not partes.hostname or partes.username or partes.password or partes.query or partes.fragment:
            logger.error("URL publica invalida: use HTTPS sem credenciais, query ou fragmento.")
            return False
        destino = dominio if partes.path.endswith("/webhook") else f"{dominio}/webhook"
    else:
        logger.warning("URL do servidor não detectada. Configure manualmente.")
        return False

    # Nao descarta updates pendentes. Lista explicita desfaz configuracao antiga.
    payload = {"url": destino, "allowed_updates": ["message"], "max_connections": 1,
               "secret_token": WEBHOOK_SECRET}
    try:
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json=payload, timeout=(5, 15))
        data = r.json()
        if r.ok and data.get("ok"):
            WEBHOOK_URL = destino
            logger.info("Webhook registrado: %s", WEBHOOK_URL)
            return True
        else:
            logger.warning("Falha ao registrar webhook: HTTP %s", r.status_code)
            return False
    except Exception as e:
        logger.warning("Erro ao registrar webhook: %s", type(e).__name__)
        return False


if __name__ == "__main__":
    logger.info("Iniciando servidor B3-bot...")
    # Restaura posições/propostas do GitHub antes de atender comandos
    _estado_pronto = _baixar_estado_do_github()
    if not _estado_pronto or not _configurar_webhook():
        raise SystemExit("Startup incompleto: restauracao/configuracao falhou.")

    porta = int(os.environ.get("PORT", "8080"))
    logger.info("Servidor rodando na porta %s", porta)
    app.run(host="0.0.0.0", port=porta, threaded=True)
