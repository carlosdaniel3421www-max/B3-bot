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
