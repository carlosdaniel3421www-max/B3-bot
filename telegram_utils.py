"""
Módulo de envio de relatórios para o Telegram.

SETUP (uma vez só):
1. No Telegram, fale com @BotFather -> /newbot -> siga as instruções.
   Ele te dará um TOKEN (ex: 123456789:ABCdefGhIJKlmnOPQRstuVWXyz).
2. Fale com o bot que você criou (ou adicione ele num grupo) e mande
   qualquer mensagem, ex: "oi".
3. Rode `python telegram_utils.py --descobrir-chat-id SEU_TOKEN` para
   descobrir seu chat_id automaticamente.
4. Preencha TELEGRAM_TOKEN e TELEGRAM_CHAT_ID em config.py (ou variáveis
   de ambiente).
"""

from contextlib import ExitStack
from html import escape
from html.parser import HTMLParser
import json

import requests

HTTP_TIMEOUT = (5, 30)


def _dividir_html(texto: str, limite: int = 4096) -> list[str]:
    """Normaliza HTML e reabre tags nos blocos, contando unidades UTF-16.

    O limite inclui markup/entidades (conservador). Tags desconhecidas viram
    texto; atributos arbitrarios nao sao enviados para o parser do Telegram.
    """
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.eventos = []

        def handle_starttag(self, tag, attrs):
            atributos = dict(attrs)
            if tag in {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "tg-spoiler", "blockquote", "a"}:
                extra = ""
                if tag == "a":
                    href = atributos.get("href") or ""
                    if not href.startswith(("https://", "http://", "tg://")) or len(href) > 512:
                        self.handle_data(self.get_starttag_text())
                        return
                    extra = f' href="{escape(href, quote=True)}"'
                self.eventos.append(("abre", tag, f"<{tag}{extra}>"))
            else:
                self.handle_data(self.get_starttag_text())

        def handle_endtag(self, tag):
            self.eventos.append(("fecha", tag, f"</{tag}>"))

        def handle_data(self, data):
            self.eventos.extend(("texto", "", escape(c, quote=False)) for c in data)

    parser = Parser()
    parser.feed(texto)
    parser.close()
    blocos, pilha, partes = [], [], []
    tamanho = 0

    for tipo, tag, valor in parser.eventos:
        if tipo == "fecha" and (not pilha or pilha[-1][0] != tag):
            continue
        # Limita profundidade para que sempre caiba texto entre tags reabertas.
        if tipo == "abre" and len(pilha) >= 16:
            continue
        custo = len(valor.encode("utf-16-le")) // 2
        fechamento = sum(len(f"</{t}>") for t, _ in pilha)
        reserva = len(f"</{tag}>") if tipo == "abre" else -custo if tipo == "fecha" else 0
        if tamanho + custo + fechamento + reserva > limite:
            blocos.append("".join(partes) + "".join(f"</{t}>" for t, _ in reversed(pilha)))
            partes = [abertura for _, abertura in pilha]
            tamanho = sum(len(p.encode("utf-16-le")) // 2 for p in partes)
        if tipo == "abre":
            # Links grandes aninhados podem exceder o orcamento de markup.
            if tamanho + custo + fechamento + reserva > limite - 12:
                continue
            pilha.append((tag, valor))
        elif tipo == "fecha":
            pilha.pop()
        partes.append(valor)
        tamanho += custo
    if partes:
        blocos.append("".join(partes) + "".join(f"</{t}>" for t, _ in reversed(pilha)))
    return blocos


def enviar_mensagem(token: str, chat_id: str, texto: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    if not texto:
        return False
    try:
        for bloco in _dividir_html(texto):
            resposta = requests.post(url, data={
                "chat_id": chat_id, "text": bloco, "parse_mode": "HTML",
            }, timeout=HTTP_TIMEOUT)
            if not resposta.ok or resposta.json().get("ok") is not True:
                print(f"Erro ao enviar mensagem: HTTP {resposta.status_code}")
                return False
    except (requests.RequestException, ValueError):
        # Excecoes requests podem conter o token na URL; nao imprimi-las.
        print("Erro de transporte/resposta ao enviar mensagem.")
        return False
    return True


def enviar_imagem(token: str, chat_id: str, caminho_imagem: str, legenda: str = "") -> bool:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    # Legendas grandes seguem como mensagem para respeitar o limite de 1024.
    partes = _dividir_html(legenda, 1024) if legenda else []
    legenda_curta = partes[0] if len(partes) == 1 else ""
    try:
        with open(caminho_imagem, "rb") as img:
            resposta = requests.post(url, data={
                "chat_id": chat_id, "caption": legenda_curta, "parse_mode": "HTML",
            }, files={"photo": img}, timeout=HTTP_TIMEOUT)
        if not resposta.ok or resposta.json().get("ok") is not True:
            print(f"Erro ao enviar imagem: HTTP {resposta.status_code}")
            return False
    except (OSError, requests.RequestException, ValueError):
        print("Erro ao abrir/enviar imagem.")
        return False
    return enviar_mensagem(token, chat_id, legenda) if len(partes) > 1 else True


def enviar_album(token: str, chat_id: str, caminhos_imagens: list, legenda_primeira: str = "") -> bool:
    """
    Envia várias imagens juntas, como álbum (Telegram permite até 10 por vez).
    Se houver mais de 10, envia em blocos de 10.
    """
    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    if not caminhos_imagens:
        return False
    partes = _dividir_html(legenda_primeira, 1024) if legenda_primeira else []
    legenda_curta = partes[0] if len(partes) == 1 else ""

    for inicio in range(0, len(caminhos_imagens), 10):
        bloco = caminhos_imagens[inicio:inicio + 10]
        if len(bloco) == 1:
            if not enviar_imagem(token, chat_id, bloco[0], legenda_curta if inicio == 0 else ""):
                return False
            continue
        try:
            with ExitStack() as stack:
                media, arquivos = [], {}
                for i, caminho in enumerate(bloco):
                    chave = f"foto{i}"
                    media.append({
                        "type": "photo", "media": f"attach://{chave}",
                        **({"caption": legenda_curta, "parse_mode": "HTML"} if inicio == 0 and i == 0 and legenda_curta else {}),
                    })
                    arquivos[chave] = stack.enter_context(open(caminho, "rb"))
                resposta = requests.post(url, data={"chat_id": chat_id, "media": json.dumps(media)}, files=arquivos, timeout=HTTP_TIMEOUT)
                if not resposta.ok or resposta.json().get("ok") is not True:
                    print(f"Erro ao enviar album: HTTP {resposta.status_code}")
                    return False
        except (OSError, requests.RequestException, ValueError):
            print("Erro ao abrir/enviar album.")
            return False
    return enviar_mensagem(token, chat_id, legenda_primeira) if len(partes) > 1 else True


def descobrir_chat_id(token: str):
    """Ajuda a descobrir o chat_id: mande uma mensagem pro bot antes de rodar isso."""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        resposta = r.json()
        if not r.ok or resposta.get("ok") is not True:
            print("Falha ao consultar updates. Se houver webhook ativo, use o chat ja configurado.")
            return
    except (requests.RequestException, ValueError):
        print("Falha de transporte/resposta ao consultar updates.")
        return
    if not resposta.get("result"):
        print("Nenhuma mensagem encontrada. Mande um 'oi' para o bot no Telegram e tente de novo.")
        return
    for item in resposta["result"]:
        msg = item.get("message", {})
        chat = msg.get("chat", {})
        print(f"chat_id: {chat.get('id')}  |  nome: {chat.get('first_name', chat.get('title'))}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--descobrir-chat-id":
        descobrir_chat_id(sys.argv[2])
    else:
        print("Uso: python telegram_utils.py --descobrir-chat-id SEU_TOKEN")
