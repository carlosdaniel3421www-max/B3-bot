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

import requests


def enviar_mensagem(token: str, chat_id: str, texto: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resposta = requests.post(url, data={
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",
    })
    if not resposta.ok:
        print(f"Erro ao enviar mensagem: {resposta.text}")
    return resposta.ok


def enviar_imagem(token: str, chat_id: str, caminho_imagem: str, legenda: str = "") -> bool:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    with open(caminho_imagem, "rb") as img:
        resposta = requests.post(url, data={
            "chat_id": chat_id,
            "caption": legenda,
            "parse_mode": "HTML",
        }, files={"photo": img})
    if not resposta.ok:
        print(f"Erro ao enviar imagem: {resposta.text}")
    return resposta.ok


def enviar_album(token: str, chat_id: str, caminhos_imagens: list, legenda_primeira: str = "") -> bool:
    """
    Envia várias imagens juntas, como álbum (Telegram permite até 10 por vez).
    Se houver mais de 10, envia em blocos de 10.
    """
    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    ok_geral = True

    for inicio in range(0, len(caminhos_imagens), 10):
        bloco = caminhos_imagens[inicio:inicio + 10]
        media = []
        arquivos = {}
        for i, caminho in enumerate(bloco):
            chave = f"foto{i}"
            media.append({
                "type": "photo",
                "media": f"attach://{chave}",
                **({"caption": legenda_primeira, "parse_mode": "HTML"} if (inicio == 0 and i == 0 and legenda_primeira) else {}),
            })
            arquivos[chave] = open(caminho, "rb")

        try:
            import json
            resposta = requests.post(url, data={"chat_id": chat_id, "media": json.dumps(media)}, files=arquivos)
            if not resposta.ok:
                print(f"Erro ao enviar álbum: {resposta.text}")
                ok_geral = False
        finally:
            for f in arquivos.values():
                f.close()

    return ok_geral


def descobrir_chat_id(token: str):
    """Ajuda a descobrir o chat_id: mande uma mensagem pro bot antes de rodar isso."""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    resposta = requests.get(url).json()
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
