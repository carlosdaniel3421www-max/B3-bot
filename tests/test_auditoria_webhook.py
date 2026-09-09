"""Auditoria isolada: sem imports de negocio, rede ou JSONs reais."""

import base64
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import importlib.util
import io
import json
from pathlib import Path
import queue
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import telegram_utils as tu


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    def bloquear(*args, **kwargs):
        raise AssertionError("Rede proibida neste teste")
    monkeypatch.setattr(requests.sessions.Session, "request", bloquear)


@pytest.fixture
def sa(monkeypatch):
    caminho = Path(__file__).resolve().parents[1] / "servidor_api.py"
    spec = importlib.util.spec_from_file_location("servidor_auditoria_isolado", caminho)
    modulo = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as contexto:
        contexto.setitem(sys.modules, "config", SimpleNamespace(TELEGRAM_TOKEN="fake:token", TELEGRAM_CHAT_ID="1"))
        contexto.setitem(sys.modules, "telegram_bot", SimpleNamespace(processar_comando=Mock(return_value="ok")))
        contexto.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
        spec.loader.exec_module(modulo)
    modulo._responder_telegram = Mock(return_value=True)
    modulo.time = SimpleNamespace(sleep=Mock())
    yield modulo
    if modulo._worker is not None and modulo._worker.is_alive():
        modulo._fila.put(None, timeout=5)
        modulo._worker.join(timeout=5)
        assert not modulo._worker.is_alive()
        modulo._fila.join()


def resposta(data=None, status=200):
    return SimpleNamespace(ok=status == 200, status_code=status, json=lambda: data if data is not None else {"ok": True})


def update(numero=1, chat=1, texto="/ajuda"):
    return {"update_id": numero, "message": {"chat": {"id": chat}, "text": texto}}


@pytest.mark.parametrize("chat", ["", "None", "0", "COLOQUE_SEU_CHAT_ID_AQUI"])
def test_chat_fail_closed(sa, chat):
    sa.CHAT_ID_AUTORIZADO = chat
    assert sa.app.test_client().post("/webhook", json=update()).status_code == 503
    sa.processar_comando.assert_not_called()


def test_secret_obrigatorio_quando_configurado_e_legado_opcional(sa):
    cliente = sa.app.test_client()
    sa.WEBHOOK_SECRET = "segredo-123"
    for segredo in [None, "errado", "nao-ascii-\u00e1"]:
        headers = {} if segredo is None else {"X-Telegram-Bot-Api-Secret-Token": segredo}
        assert cliente.post("/webhook", json=update(), headers=headers).status_code == 403
    sa.processar_comando.assert_not_called()
    headers = {"X-Telegram-Bot-Api-Secret-Token": sa.WEBHOOK_SECRET}
    assert cliente.post("/webhook", json=update(chat=2), headers=headers).status_code == 200
    sa.processar_comando.assert_not_called()
    assert cliente.post("/webhook", json=update(), headers=headers).status_code == 200
    sa.WEBHOOK_SECRET = ""
    assert cliente.post("/webhook", json=update(2)).status_code == 200
    sa._fila.join()
    assert sa.processar_comando.call_count == 2


@pytest.mark.parametrize("payload", [None, [], [1], "x", {}, {"update_id": True}, {"update_id": -1}, {"update_id": "1"}, {"update_id": 1, "message": []}, {"update_id": 1, "message": {"chat": []}}, update(texto=[1])])
def test_payload_invalido_nao_crasha(sa, payload):
    assert sa.app.test_client().post("/webhook", json=payload).status_code == 400
    sa.processar_comando.assert_not_called()


def test_ignora_editadas_e_dedup(sa):
    cliente = sa.app.test_client()
    assert cliente.post("/webhook", json={"update_id": 1, "edited_message": update()["message"]}).status_code == 200
    sa.processar_comando.assert_not_called()
    for _ in range(3):
        assert cliente.post("/webhook", json=update()).status_code == 200
    sa._fila.join()
    sa.processar_comando.assert_called_once()
    sa._responder_telegram.assert_called_once()


def test_ack_imediato_dedup_concorrente_e_worker_unico(sa):
    entrou, liberar = threading.Event(), threading.Event()
    threads = []

    def comando(*args):
        threads.append(threading.get_ident())
        entrou.set()
        assert liberar.wait(5)
        return "ok"

    sa.processar_comando.side_effect = comando
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futuros = [executor.submit(lambda: sa.app.test_client().post("/webhook", json=update())) for _ in range(16)]
            assert all(f.result(timeout=2).status_code == 200 for f in futuros)
        assert entrou.wait(5)
        assert not liberar.is_set()
        worker = sa._worker
        assert sa._processados[1] == "em_execucao"
        for numero in [2, 2, 3, 3]:
            assert sa.app.test_client().post("/webhook", json=update(numero)).status_code == 200
        assert sa._processados[2] == sa._processados[3] == "pendente"
        assert sa._fila.qsize() == 2
        assert sa.processar_comando.call_count == 1
        assert sa._worker is worker
        assert sa.app.test_client().get("/health").status_code == 200
    finally:
        liberar.set()
    sa._fila.join()
    assert len(set(threads)) == 1
    assert sa.processar_comando.call_count == 3
    assert sa.app.test_client().post("/webhook", json=update()).status_code == 200
    sa._fila.join()
    assert sa.processar_comando.call_count == 3
    assert set(sa._processados.values()) == {"enviado"}


def test_falha_comando_avisa_uma_vez_e_worker_continua(sa):
    sa.processar_comando.side_effect = [RuntimeError("falha"), "ok"]
    cliente = sa.app.test_client()
    assert cliente.post("/webhook", json=update()).status_code == 200
    sa._fila.join()
    assert sa._processados[1] == "enviado"
    sa._responder_telegram.assert_called_once()
    assert "Erro interno" in sa._responder_telegram.call_args.args[1]
    for _ in range(3):
        assert cliente.post("/webhook", json=update()).status_code == 200
    sa._fila.join()
    sa.processar_comando.assert_called_once()
    sa._responder_telegram.assert_called_once()
    assert cliente.post("/webhook", json=update(2)).status_code == 200
    sa._fila.join()
    assert sa.processar_comando.call_count == 2


@pytest.mark.parametrize("falha", [False, requests.Timeout("fake:token")])
def test_falha_envio_retry_limitado_sem_repetir_negocio(sa, falha):
    sa._responder_telegram.side_effect = [falha, falha, True]
    cliente = sa.app.test_client()
    assert cliente.post("/webhook", json=update()).status_code == 200
    sa._fila.join()
    assert sa._responder_telegram.call_count == 3
    assert sa.time.sleep.call_count == 2
    assert sa._processados[1] == "enviado"
    assert cliente.post("/webhook", json=update()).status_code == 200
    sa._fila.join()
    sa.processar_comando.assert_called_once()
    assert sa._responder_telegram.call_count == 3


def test_envio_esgotado_terminal_sem_spam_e_worker_continua(sa):
    sa._responder_telegram.return_value = False
    cliente = sa.app.test_client()
    assert cliente.post("/webhook", json=update()).status_code == 200
    sa._fila.join()
    assert sa._processados[1] == "falha_envio"
    assert sa._responder_telegram.call_count == sa._MAX_TENTATIVAS_ENVIO
    for _ in range(5):
        assert cliente.post("/webhook", json=update()).status_code == 200
    sa._fila.join()
    sa.processar_comando.assert_called_once()
    assert sa._responder_telegram.call_count == sa._MAX_TENTATIVAS_ENVIO
    sa._responder_telegram.return_value = True
    assert cliente.post("/webhook", json=update(2)).status_code == 200
    sa._fila.join()
    assert sa._processados[2] == "enviado"


def test_fila_cheia_rejeita_antes_aceitar_e_dedup_pendente(sa):
    sa._fila = queue.Queue(maxsize=1)
    entrou, liberar = threading.Event(), threading.Event()

    def comando(*args):
        entrou.set()
        assert liberar.wait(5)
        return "ok"

    sa.processar_comando.side_effect = comando
    cliente = sa.app.test_client()
    try:
        assert cliente.post("/webhook", json=update()).status_code == 200
        assert entrou.wait(5)
        assert cliente.post("/webhook", json=update(2)).status_code == 200
        assert cliente.post("/webhook", json=update(3)).status_code == 503
        assert 3 not in sa._processados
        assert sa._fila.qsize() == 1
        for numero in [1, 2]:
            assert cliente.post("/webhook", json=update(numero)).status_code == 200
        assert sa.processar_comando.call_count == 1
    finally:
        liberar.set()
    sa._fila.join()
    assert cliente.post("/webhook", json=update(3)).status_code == 200
    sa._fila.join()
    assert sa.processar_comando.call_count == 3


def test_enqueue_falha_nao_confirma_nem_reserva_dedup(sa, monkeypatch):
    def enqueue(item):
        assert item == (1, "1", "/ajuda")
        assert 1 not in sa._processados
        assert sa._comando_lock.locked()
        raise queue.Full

    monkeypatch.setattr(sa._fila, "put_nowait", enqueue)
    assert sa.app.test_client().post("/webhook", json=update()).status_code == 503
    assert not sa._processados
    sa.processar_comando.assert_not_called()


def test_ack_apos_enqueue_e_reentrega_durante_envio(sa, monkeypatch):
    enfileirado, enviando, liberar = threading.Event(), threading.Event(), threading.Event()
    put_real = sa._fila.put_nowait

    def enqueue(item):
        assert sa._comando_lock.locked()
        put_real(item)
        enfileirado.set()

    def enviar(*args):
        enviando.set()
        assert liberar.wait(5)
        return True

    monkeypatch.setattr(sa._fila, "put_nowait", enqueue)
    sa._responder_telegram.side_effect = enviar
    cliente = sa.app.test_client()
    try:
        assert cliente.post("/webhook", json=update()).status_code == 200
        assert enfileirado.is_set()
        assert enviando.wait(5)
        assert sa._processados[1] == "em_execucao"
        for _ in range(5):
            assert cliente.post("/webhook", json=update()).status_code == 200
        sa.processar_comando.assert_called_once()
        sa._responder_telegram.assert_called_once()
        assert cliente.get("/health").status_code == 200
    finally:
        liberar.set()
    sa._fila.join()
    assert sa._processados[1] == "enviado"


def test_worker_start_falha_nao_aceita(sa, monkeypatch):
    monkeypatch.setattr(sa.threading.Thread, "start", Mock(side_effect=RuntimeError("falha")))
    assert sa.app.test_client().post("/webhook", json=update()).status_code == 503
    assert not sa._processados
    assert sa._fila.empty()


def test_cache_limitado_preserva_pendentes_e_execucao(sa):
    sa._MAX_RECENTES = 2
    sa._processados.update({1: "pendente", 2: "enviado"})
    cliente = sa.app.test_client()
    assert cliente.post("/webhook", json=update(3)).status_code == 200
    sa._fila.join()
    assert sa._processados == {1: "pendente", 3: "enviado"}
    with sa._comando_lock:
        sa._processados[3] = "em_execucao"
    assert cliente.post("/webhook", json=update(4)).status_code == 503
    assert len(sa._processados) == 2


@pytest.mark.parametrize("segredo", ["", "segredo_123"])
def test_registro_timeout_secret_updates_e_url(sa, monkeypatch, segredo):
    sa.WEBHOOK_SECRET = segredo
    monkeypatch.setenv("WEBHOOK_URL", "https://manual.example/base/")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://render.example")
    post = Mock(return_value=resposta())
    monkeypatch.setattr(requests, "post", post)
    assert sa._configurar_webhook()
    payload = post.call_args.kwargs["json"]
    assert payload == {"url": "https://manual.example/base/webhook", "secret_token": segredo, "allowed_updates": ["message"], "max_connections": 1}
    assert post.call_args.kwargs["timeout"] == (5, 15)
    assert "drop_pending_updates" not in payload


def test_replit_hostname_e_falha_registro(sa, monkeypatch):
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.setenv("REPLIT_DEV_DOMAIN", "teste.replit.dev")
    monkeypatch.setattr(requests, "post", Mock(return_value=resposta()))
    assert sa._configurar_webhook()
    assert sa.WEBHOOK_URL == "https://teste.replit.dev/webhook"
    monkeypatch.setattr(requests, "post", Mock(side_effect=requests.Timeout("fake:token")))
    assert not sa._configurar_webhook()
    assert sa.WEBHOOK_URL == ""


@pytest.mark.parametrize("url", ["http://example.com", "https://example.com?x=1", "https://user:password@example.com", "https://example.com/#x", "https://[", "https://example.com:abc"])
def test_url_invalida_nao_registra(sa, monkeypatch, url):
    monkeypatch.setenv("WEBHOOK_URL", url)
    assert not sa._configurar_webhook()


def test_health_local_e_readiness_remoto_sem_token_no_log(sa, monkeypatch, caplog):
    cliente = sa.app.test_client()
    assert cliente.get("/health").status_code == 200
    assert cliente.get("/ready").status_code == 503
    sa.WEBHOOK_URL = "https://example.com/webhook"
    assert cliente.get("/ready").status_code == 503
    sa._estado_pronto = True
    get = Mock(return_value=resposta({"ok": True, "result": {"url": sa.WEBHOOK_URL}}))
    monkeypatch.setattr(requests, "get", get)
    assert cliente.get("/ready").status_code == 200
    assert get.call_args.kwargs["timeout"] == (5, 15)
    get.return_value = resposta({"ok": True, "result": {"url": ""}})
    assert cliente.get("/ready").status_code == 503
    get.side_effect = requests.Timeout(sa.TOKEN)
    assert cliente.get("/ready").status_code == 503
    get.reset_mock()
    assert cliente.get("/health").status_code == 200
    get.assert_not_called()
    monkeypatch.setenv("WEBHOOK_URL", sa.WEBHOOK_URL)
    monkeypatch.setattr(requests, "post", Mock(side_effect=requests.Timeout(sa.TOKEN)))
    assert not sa._configurar_webhook()
    assert sa.TOKEN not in caplog.text


@pytest.mark.parametrize("conteudo", ["[]", "null", "1", '"texto"', "{quebrado", '{"valor": NaN}', '{"PETR4": []}', '{"PETR4": {"valor": NaN}}'])
def test_restauracao_invalida_preserva_local(sa, monkeypatch, tmp_path, conteudo):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    for nome in ("posicoes.json", "propostas.json"):
        (tmp_path / nome).write_text('{"local": true}', encoding="utf-8")
    get = Mock(return_value=resposta({"content": base64.b64encode(conteudo.encode()).decode()}))
    monkeypatch.setattr(requests, "get", get)
    assert not sa._baixar_estado_do_github()
    for nome in ("posicoes.json", "propostas.json"):
        assert json.loads((tmp_path / nome).read_text()) == {"local": True}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("dados", [{}, {"PETR4": {"quantidade": 10}}])
def test_restauracao_dict_atomica(sa, monkeypatch, tmp_path, dados):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    conteudo = base64.b64encode(json.dumps(dados).encode()).decode()
    get = Mock(return_value=resposta({"content": conteudo}))
    monkeypatch.setattr(requests, "get", get)
    replace_real = sa.os.replace
    chamadas = []

    def replace(origem, destino):
        assert Path(origem).parent == tmp_path
        assert json.loads(Path(origem).read_text()) == dados
        chamadas.append(destino)
        replace_real(origem, destino)

    monkeypatch.setattr(sa.os, "replace", replace)
    assert sa._baixar_estado_do_github()
    assert chamadas == ["posicoes.json", "propostas.json"]
    assert get.call_args.kwargs["params"] == {"ref": "main"}
    assert get.call_args.kwargs["timeout"] == (5, 15)
    assert not list(tmp_path.glob("*.tmp"))


def test_replace_falha_preserva_local_e_limpa_temp(sa, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    for nome in ("posicoes.json", "propostas.json"):
        (tmp_path / nome).write_text('{"local": 1}')
    monkeypatch.setattr(requests, "get", Mock(return_value=resposta({"content": "e30="})))
    monkeypatch.setattr(sa.os, "replace", Mock(side_effect=OSError("falha")))
    assert not sa._baixar_estado_do_github()
    assert json.loads((tmp_path / "posicoes.json").read_text()) == {"local": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_restauracao_opcional_404_e_http_falha(sa, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert sa._baixar_estado_do_github()
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    get = Mock(return_value=resposta(status=404))
    monkeypatch.setattr(requests, "get", get)
    assert sa._baixar_estado_do_github()
    get.return_value = resposta(status=403)
    assert not sa._baixar_estado_do_github()
    assert not list(tmp_path.iterdir())


class HTMLValido(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pilha, self.texto = [], []

    def handle_starttag(self, tag, attrs):
        self.pilha.append(tag)

    def handle_endtag(self, tag):
        assert self.pilha.pop() == tag

    def handle_data(self, data):
        self.texto.append(data)


@pytest.mark.parametrize("conteudo", ["x" * 9000, "\U0001f600" * 4097, "a & b < c > d " * 500, "&amp;" * 4100], ids=["ascii", "utf16", "comparadores", "entidades"])
def test_html_longo_preserva_texto_tags_entidades_e_limite(monkeypatch, conteudo):
    original = f'<b>inicio <i>{conteudo}</i> fim</b>'
    post = Mock(return_value=resposta())
    monkeypatch.setattr(requests, "post", post)
    assert tu.enviar_mensagem("fake", "1", original)
    assert post.call_count > 1
    textos = []
    for chamada in post.call_args_list:
        bloco = chamada.kwargs["data"]["text"]
        assert len(bloco.encode("utf-16-le")) // 2 <= 4096
        parser = HTMLValido()
        parser.feed(bloco)
        parser.close()
        assert not parser.pilha
        textos.extend(parser.texto)
        assert chamada.kwargs["timeout"] == tu.HTTP_TIMEOUT
    esperado = HTMLParser(convert_charrefs=True)
    texto_esperado = []
    esperado.handle_data = texto_esperado.append
    esperado.feed(original)
    esperado.close()
    assert "".join(textos) == "".join(texto_esperado)


def test_html_link_e_tags_nao_suportadas():
    blocos = tu._dividir_html('<a href="https://example.com/?a=1&amp;b=2">' + "x" * 9000 + '</a><script>bad</script>')
    for bloco in blocos:
        parser = HTMLValido()
        parser.feed(bloco)
        assert not parser.pilha
        assert "<script>" not in bloco
        assert len(bloco) <= 4096
    assert 'href="https://example.com/?a=1&amp;b=2"' in blocos[1]


@pytest.mark.parametrize("resultado", [requests.Timeout("fake:token"), resposta({"ok": False}), resposta(status=429)])
def test_envio_falha_sem_expor_token(monkeypatch, capsys, resultado):
    post = Mock(side_effect=resultado) if isinstance(resultado, Exception) else Mock(return_value=resultado)
    monkeypatch.setattr(requests, "post", post)
    assert not tu.enviar_mensagem("fake:token", "1", "teste")
    assert "fake:token" not in capsys.readouterr().out


def test_album_onze_fotos_e_legenda_longa(monkeypatch):
    arquivos = []

    def abrir(*args, **kwargs):
        arquivo = io.BytesIO(b"fake image")
        arquivos.append(arquivo)
        return arquivo

    monkeypatch.setattr("builtins.open", abrir)
    post = Mock(return_value=resposta())
    monkeypatch.setattr(requests, "post", post)
    assert tu.enviar_album("fake", "1", [f"foto{i}" for i in range(11)], "<b>" + "x" * 5000 + "</b>")
    assert [c.args[0].rsplit("/", 1)[-1] for c in post.call_args_list] == ["sendMediaGroup", "sendPhoto", "sendMessage", "sendMessage"]
    assert all(f.closed for f in arquivos)
    assert all(c.kwargs["timeout"] == tu.HTTP_TIMEOUT for c in post.call_args_list)


def test_album_fecha_arquivos_quando_abertura_falha(monkeypatch):
    primeiro = io.BytesIO(b"foto")
    monkeypatch.setattr("builtins.open", Mock(side_effect=[primeiro, OSError("ausente")]))
    assert not tu.enviar_album("fake", "1", ["a", "b"])
    assert primeiro.closed


def test_descobrir_timeout(monkeypatch, capsys):
    get = Mock(side_effect=requests.Timeout("fake:token"))
    monkeypatch.setattr(requests, "get", get)
    tu.descobrir_chat_id("fake:token")
    assert get.call_args.kwargs["timeout"] == tu.HTTP_TIMEOUT
    assert "fake:token" not in capsys.readouterr().out


def test_workflows_guardas_persistencia_e_ci():
    raiz = Path(__file__).resolve().parents[1]
    polling = (raiz / ".github/workflows/telegram_bot.yml").read_text(encoding="utf-8")
    relatorio = (raiz / ".github/workflows/relatorio.yml").read_text(encoding="utf-8")
    testes = (raiz / ".github/workflows/testes.yml").read_text(encoding="utf-8")
    assert "inputs.servidor_parado" in polling
    assert "getWebhookInfo" in polling
    assert 'GITHUB_TOKEN: ""' in polling
    assert "git pull" not in polling and "--rebase" not in polling
    assert 'git push origin "HEAD:refs/heads/$BRANCH"' in polling
    assert "group: relatorio-estado-${{ github.ref }}" in polling and "group: relatorio-estado-${{ github.ref }}" in relatorio
    assert "actions/upload-artifact@v4" in polling
    assert "persist-credentials: false" in testes


def test_yaml_workflows_e_sintaxe_guarda_polling():
    yaml = pytest.importorskip("yaml")
    raiz = Path(__file__).resolve().parents[1] / ".github/workflows"
    for caminho in raiz.glob("*.yml"):
        dados = yaml.load(caminho.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        assert "on" in dados and "jobs" in dados
        if caminho.name == "telegram_bot.yml":
            steps = dados["jobs"]["processar-comandos"]["steps"]
            guarda = next(s["run"] for s in steps if "getWebhookInfo" in s.get("run", ""))
            codigo = guarda.split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
            compile(codigo, "guarda_polling", "exec")
