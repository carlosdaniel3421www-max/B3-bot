"""
Gestão de posições abertas — o robô agora acompanha as operações que você
abriu e te diz exatamente O QUE FAZER a cada dia (proteger lucro, mover
stop, fechar, etc).

USO (linha de comando):
    python posicoes.py adicionar PETR4 compra 43.11 40.50 48.22
    python posicoes.py adicionar VALE3 venda 72.50 74.00 68.00 --quantidade 300
    python posicoes.py listar
    python posicoes.py remover PETR4
    python posicoes.py status PETR4   # mostra gestão da posição com preço atual

Formato do registro (posicoes.json):
    {
        "PETR4": {
            "ticker": "PETR4",
            "direcao": "compra" | "venda",
            "preco_entrada": 43.11,
            "stop": 40.50,
            "alvo": 48.22,
            "quantidade": 100,
            "data_entrada": "2026-08-19",
            "prazo_maximo_dias": 20
        }
    }

Regras de gestão automática (quando o robô roda o relatório diário):
    - Preço <= stop (compra): SAIR AGORA — stop atingido
    - Preço >= alvo (compra): FECHAR — alvo atingido
    - Preço em 50% do caminho até o alvo: mover stop para o preço de entrada
      (breakeven) — trade sem risco
    - Preço em 75% do caminho: considerar fechar parcial (trava lucro)
    - Prazo máximo de holding expirado: fechar por tempo
    - Demais casos: manter posição com stop/alvo originais
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime

import requests

CAMINHO_POSICOES = "posicoes.json"
CAMINHO_PROPOSTAS = "propostas.json"
DIAS_UTEIS_POR_SEMANA = 5.0

# Frações do caminho preço-entrada -> alvo onde aplicamos regras
FRACAO_BREAKEVEN = 0.5    # 50% do caminho: move stop pro breakeven
FRACAO_FECHAR_PARCIAL = 0.75  # 75% do caminho: trava lucro parcial

# Limites de segurança
STOP_MINIMO_PCT = 0.02   # nunca sugere stop menor que 2% do preço
ALVO_MAXIMO_PCT = 0.30   # nunca sugere alvo maior que 30% do preço (opções mais curtas)


def carregar_posicoes() -> dict:
    if not os.path.exists(CAMINHO_POSICOES):
        return {}
    try:
        with open(CAMINHO_POSICOES, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def salvar_posicoes(posicoes: dict):
    with open(CAMINHO_POSICOES, "w", encoding="utf-8") as f:
        json.dump(posicoes, f, ensure_ascii=False, indent=2)
    # Sincroniza com o GitHub para persistir além do disco efêmero do Render
    _sincronizar_github(CAMINHO_POSICOES)


REPO_GITHUB = "carlosdaniel3421www-max/B3-bot"
BRANCH_GITHUB = "main"


def _sincronizar_github(arquivo: str):
    """
    Faz commit do arquivo (ex: posicoes.json) no GitHub via API de Contents.
    Usa o GITHUB_TOKEN. Assim as posições persistem mesmo quando o Render
    reinicia (disco efêmero). Falha silenciosa se token ausente.
    """
    import base64
    import requests

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return False

    nome_arquivo = os.path.basename(arquivo)
    with open(arquivo, "r", encoding="utf-8") as f:
        conteudo = f.read()

    # Busca o SHA atual do arquivo (necessário para atualizar)
    url_arquivo = f"https://api.github.com/repos/{REPO_GITHUB}/contents/{nome_arquivo}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}

    try:
        resp = requests.get(url_arquivo, headers=headers, timeout=15)
        sha = None
        if resp.status_code == 200:
            sha = resp.json().get("sha")

        payload = {
            "message": f"Atualiza {nome_arquivo} [skip ci]",
            "content": base64.b64encode(conteudo.encode("utf-8")).decode("utf-8"),
            "branch": BRANCH_GITHUB,
        }
        if sha:
            payload["sha"] = sha

        resp = requests.put(url_arquivo, json=payload, headers=headers, timeout=15)
        return resp.status_code in (200, 201)
    except Exception as e:
        logging.warning("Falha ao sincronizar %s no GitHub: %s", arquivo, e)
        return False


# ---------------------------------------------------------------------------
# PROPOSTAS: o robô sugere uma entrada (ENV). Você decide registrar ou não.
# ---------------------------------------------------------------------------

def carregar_propostas() -> dict:
    if not os.path.exists(CAMINHO_PROPOSTAS):
        return {}
    try:
        with open(CAMINHO_PROPOSTAS, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def salvar_propostas(propostas: dict):
    with open(CAMINHO_PROPOSTAS, "w", encoding="utf-8") as f:
        json.dump(propostas, f, ensure_ascii=False, indent=2)


def salvar_proposta_entrada(ticker: str, direcao: str, preco: float,
                            stop: float, alvo: float, prazo_maximo_dias: int = 20) -> dict:
    """Salva a proposta de entrada que o robô fez, pra você confirmar depois."""
    ticker = ticker.upper()
    propostas = carregar_propostas()
    proposta = {
        "ticker": ticker,
        "direcao": direcao,
        "preco_entrada": round(preco, 2),
        "stop": round(stop, 2),
        "alvo": round(alvo, 2),
        "prazo_maximo_dias": prazo_maximo_dias,
        "data_proposta": date.today().isoformat(),
    }
    propostas[ticker] = proposta
    salvar_propostas(propostas)
    return proposta


def registrar_da_proposta(ticker: str, quantidade: int = 0) -> tuple:
    """
    Registra uma posição a partir da proposta mais recente do robô.
    Retorna (posicao, mensagem).
    """
    ticker = ticker.upper()
    propostas = carregar_propostas()
    if ticker not in propostas:
        return None, f"⚠️ Não achei proposta de entrada pra {ticker}. O robô só propõe quando dá ENTRAR (score ≥ 8) num relatório recente."

    proposta = propostas[ticker]
    posicoes = carregar_posicoes()
    if ticker in posicoes:
        posicao = posicoes[ticker]
        posicao.update({
            "direcao": proposta["direcao"],
            "preco_entrada": proposta["preco_entrada"],
            "stop": proposta["stop"],
            "alvo": proposta["alvo"],
            "prazo_maximo_dias": proposta.get("prazo_maximo_dias", 20),
        })
        salvar_posicoes(posicoes)
        return posicao, f"ℹ️ {ticker} já estava registrada — atualizada com os valores da proposta de {proposta['data_proposta']} (entrada R$ {posicao['preco_entrada']} · stop R$ {posicao['stop']} · alvo R$ {posicao['alvo']})."

    posicao = {
        "ticker": ticker,
        "direcao": proposta["direcao"],
        "preco_entrada": proposta["preco_entrada"],
        "stop": proposta["stop"],
        "alvo": proposta["alvo"],
        "quantidade": quantidade,
        "data_entrada": date.today().isoformat(),
        "prazo_maximo_dias": proposta.get("prazo_maximo_dias", 20),
    }
    posicoes[ticker] = posicao
    salvar_posicoes(posicoes)
    return posicao, f"✅ <b>{ticker}</b> registrada ({posicao['direcao']}). Entrada R$ {posicao['preco_entrada']} · Stop R$ {posicao['stop']} · Alvo R$ {posicao['alvo']}. Agora acompanho todo dia."


def adicionar_posicao(ticker: str, direcao: str, preco_entrada: float,
                      stop: float, alvo: float, quantidade: int = 0,
                      prazo_maximo_dias: int = 20) -> dict:
    """Adiciona (ou atualiza) uma posição aberta."""
    ticker = ticker.upper()
    direcao = direcao.lower()
    if direcao not in ("compra", "venda"):
        raise ValueError("direcao deve ser 'compra' ou 'venda'")

    if preco_entrada <= 0 or stop <= 0 or alvo <= 0:
        raise ValueError("Preços devem ser maiores que zero")

    # Validação de sanidade do stop/alvo
    if direcao == "compra":
        if stop >= preco_entrada:
            raise ValueError("Stop deve ser MENOR que o preço de entrada (compra)")
        if alvo <= preco_entrada:
            raise ValueError("Alvo deve ser MAIOR que o preço de entrada (compra)")
    else:
        if stop <= preco_entrada:
            raise ValueError("Stop deve ser MAIOR que o preço de entrada (venda)")
        if alvo >= preco_entrada:
            raise ValueError("Alvo deve ser MENOR que o preço de entrada (venda)")

    posicoes = carregar_posicoes()
    posicao = {
        "ticker": ticker,
        "direcao": direcao,
        "preco_entrada": round(preco_entrada, 2),
        "stop": round(stop, 2),
        "alvo": round(alvo, 2),
        "quantidade": quantidade,
        "data_entrada": date.today().isoformat(),
        "prazo_maximo_dias": prazo_maximo_dias,
    }
    posicoes[ticker] = posicao
    salvar_posicoes(posicoes)
    return posicao


def adicionar_trava(ticker: str, tipo: str, strike_comprado: float, premio_comprado: float,
                    strike_vendido: float, premio_vendido: float,
                    stop_premio: float, alvo_premio: float,
                    quantidade: int = 100, vencimento: str = "") -> dict:
    """
    Registra uma TRAVA montada (Bull/Bear Spread) como posição aberta.
    O "preco_entrada" é o custo líquido por contrato (débito).
    O "stop" e "alvo" são valores no PRÊMIO da trava (em R$ por contrato).
    """
    ticker = ticker.upper()
    tipo = tipo.lower()
    if tipo not in ("compra", "venda"):
        raise ValueError("tipo deve ser 'compra' ou 'venda'")

    custo_liquido = round(premio_comprado - premio_vendido, 2)
    if custo_liquido <= 0:
        raise ValueError("Custo líquido da trava deve ser maior que zero")

    if stop_premio >= custo_liquido:
        raise ValueError("Stop no prêmio deve ser MENOR que o custo da trava")
    if alvo_premio <= custo_liquido:
        raise ValueError("Alvo no prêmio deve ser MAIOR que o custo da trava")

    posicoes = carregar_posicoes()
    posicao = {
        "ticker": ticker,
        "direcao": tipo,
        "tipo_operacao": "trava",
        "strike_comprado": round(strike_comprado, 2),
        "strike_vendido": round(strike_vendido, 2),
        "premio_comprado": round(premio_comprado, 2),
        "premio_vendido": round(premio_vendido, 2),
        "preco_entrada": custo_liquido,           # débito por contrato
        "stop": round(stop_premio, 2),            # stop no PRÊMIO
        "alvo": round(alvo_premio, 2),            # alvo no PRÊMIO
        "quantidade": quantidade,
        "vencimento": vencimento,
        "data_entrada": date.today().isoformat(),
        "prazo_maximo_dias": 20,
    }
    posicoes[ticker] = posicao
    salvar_posicoes(posicoes)
    return posicao


def formatar_gestao_trava(trava: dict, preco_atual_premio: float) -> str:
    """
    Formata a gestão de uma TRAVA registrada, comparando o prêmio atual da
    perna comprada com o custo da trava (débito). Mostra lucro/stop no prêmio.
    """
    custo = trava.get("preco_entrada", 0)
    stop = trava.get("stop", 0)
    alvo = trava.get("alvo", 0)
    direcao = trava.get("direcao", "compra")

    emoji = "🟢" if direcao == "compra" else "🔴"
    linhas = [f"{emoji} <b>{trava['ticker']}</b> — TRAVA ({trava.get('strike_comprado','?')}/{trava.get('strike_vendido','?')})"]

    linhas.append(f"  💰 Débito por contrato: R$ {custo:.2f}")
    linhas.append(f"  🛑 Stop no prêmio: R$ {stop:.2f} | 🎯 Alvo no prêmio: R$ {alvo:.2f}")

    if preco_atual_premio:
        lucro_pct = (preco_atual_premio - custo) / custo * 100 if custo else 0
        linhas.append(f"  📊 Prêmio atual da perna comprada: R$ {preco_atual_premio:.2f} ({lucro_pct:+.1f}%)")
        if preco_atual_premio <= stop:
            linhas.append("  ⚠️ <b>STOP no prêmio atingido — considere fechar!</b>")
        elif preco_atual_premio >= alvo:
            linhas.append("  ✅ <b>ALVO atingido — feche a trava e realize o lucro!</b>")
        elif preco_atual_premio > custo:
            linhas.append("  ✅ Trava no lucro. Pode segurar ou fechar parcial.")

    venc = trava.get("vencimento")
    if venc:
        linhas.append(f"  📅 Vencimento: {venc}")

    return "\n".join(linhas)


def remover_posicao(ticker: str) -> bool:
    posicoes = carregar_posicoes()
    if ticker.upper() in posicoes:
        del posicoes[ticker.upper()]
        salvar_posicoes(posicoes)
        return True
    return False


def _dias_corridos(data_entrada: str) -> int:
    try:
        d_entrada = datetime.strptime(data_entrada, "%Y-%m-%d").date()
        return (date.today() - d_entrada).days
    except (ValueError, TypeError):
        logging.warning("Data de entrada inválida no posicoes.json: %r", data_entrada)
        return 0


def _projecao_dias_uteis(dias_corridos: int) -> int:
    """Aproximação de dias corridos -> dias úteis (fins de semana removidos)."""
    return max(1, int(dias_corridos * DIAS_UTEIS_POR_SEMANA / 7.0))


def gerar_gestao_posicao(posicao: dict, preco_atual: float) -> dict:
    """
    Dado o preço atual do ativo, retorna as instruções de gestão da posição.

    Retorna dict com: acao, emoji, instrucoes, pct_no_caminho, lucro_pct
    """
    ticker = posicao["ticker"]
    direcao = posicao["direcao"]
    entrada = posicao["preco_entrada"]
    stop = posicao["stop"]
    alvo = posicao["alvo"]
    prazo_max = posicao.get("prazo_maximo_dias", 20)
    dias_corridos = _dias_corridos(posicao.get("data_entrada", date.today().isoformat()))
    dias_uteis = _projecao_dias_uteis(dias_corridos)

    if direcao == "compra":
        lucro_pct = (preco_atual - entrada) / entrada * 100
        caminho_total = alvo - entrada
        pct_no_caminho = 0.0 if caminho_total <= 0 else max(0.0, min(1.0, (preco_atual - entrada) / caminho_total))
        stop_atingido = preco_atual <= stop
        alvo_atingido = preco_atual >= alvo
        breakeven = preco_atual >= entrada + FRACAO_BREAKEVEN * caminho_total
        parcial_75 = preco_atual >= entrada + FRACAO_FECHAR_PARCIAL * caminho_total
    else:  # venda
        lucro_pct = (entrada - preco_atual) / entrada * 100
        caminho_total = entrada - alvo
        pct_no_caminho = 0.0 if caminho_total <= 0 else max(0.0, min(1.0, (entrada - preco_atual) / caminho_total))
        stop_atingido = preco_atual >= stop
        alvo_atingido = preco_atual <= alvo
        breakeven = preco_atual <= entrada - FRACAO_BREAKEVEN * caminho_total
        parcial_75 = preco_atual <= entrada - FRACAO_FECHAR_PARCIAL * caminho_total

    tempo_expirado = dias_uteis >= prazo_max

    # --- Decisão de ação (prioridade: stop > alvo > tempo > parcial > breakeven > manter) ---
    if stop_atingido:
        acao, emoji = "SAIR AGORA", "🔴"
        instrucoes = [f"Stop atingido (preço {preco_atual:.2f} <= stop {stop:.2f}).", "Feche a posição imediatamente, sem esperar."]
    elif alvo_atingido:
        acao, emoji = "FECHAR", "✅"
        instrucoes = [f"Alvo atingido (preço {preco_atual:.2f} >= alvo {alvo:.2f}).", "Feche e registre o lucro."]
    elif tempo_expirado:
        acao, emoji = "FECHAR POR TEMPO", "⏰"
        instrucoes = [f"Prazo máximo de {prazo_max} dias úteis atingido ({dias_uteis} dias).", "Feche a posição — o movimento não andou."]
    elif parcial_75:
        acao, emoji = "FECHAR PARCIAL", "💰"
        instrucoes = [f"Posição em {pct_no_caminho * 100:.0f}% do caminho até o alvo.", "Feche metade e trave o lucro; deixe o resto correr até o alvo.", f"Movimente o stop para {entrada:.2f} (breakeven) na parte restante."]
    elif breakeven:
        acao, emoji = "PROTEGER", "🟢"
        instrucoes = [f"Posição em {pct_no_caminho * 100:.0f}% do caminho até o alvo.", f"Movimente o stop para {entrada:.2f} (breakeven) — trade sem risco."]
    else:
        acao, emoji = "MANTER", "🟡"
        instrucoes = [f"Posição em {pct_no_caminho * 100:.0f}% do caminho até o alvo.", f"Mantenha. Stop {stop:.2f} · Alvo {alvo:.2f}."]

    return {
        "ticker": ticker,
        "direcao": direcao,
        "acao": acao,
        "emoji": emoji,
        "instrucoes": instrucoes,
        "preco_atual": round(preco_atual, 2),
        "preco_entrada": entrada,
        "stop": stop,
        "alvo": alvo,
        "lucro_pct": round(lucro_pct, 2),
        "pct_no_caminho": round(pct_no_caminho * 100, 0),
        "dias_uteis": dias_uteis,
        "prazo_maximo_dias": prazo_max,
    }


def formatar_gestao(gestao: dict) -> str:
    """Formata a gestão de UMA posição para o Telegram."""
    p = gestao
    linhas = [
        f"{p['emoji']} <b>{p['ticker']} — {p['acao']}</b> ({p['direcao'].upper()})",
        f"  Preço atual: R$ {p['preco_atual']:.2f} | Entrada: R$ {p['preco_entrada']:.2f} | Lucro: {p['lucro_pct']:+.2f}%",
        f"  Stop: R$ {p['stop']:.2f} · Alvo: R$ {p['alvo']:.2f} | {p['pct_no_caminho']:.0f}% do caminho | {p['dias_uteis']}/{p['prazo_maximo_dias']} dias úteis",
    ]
    for inst in p["instrucoes"]:
        linhas.append(f"  • {inst}")
    return "\n".join(linhas)


def formatar_gestao_todas(posicoes: dict, precos: dict) -> str:
    """Formata o bloco completo de gestão de posições para o Telegram."""
    if not posicoes:
        return ""

    blocos = []
    for ticker, posicao in posicoes.items():
        preco = precos.get(ticker)
        # Se for trava, formata com a gestão de trava.
        # O preço da AÇÃO não é o prêmio da opção — passa None (sem comparação
        # automática; o usuário confere o prêmio real no home broker).
        if posicao.get("tipo_operacao") == "trava":
            blocos.append(formatar_gestao_trava(posicao, None))
            continue
        if preco is None or preco <= 0:
            blocos.append(f"⚪ <b>{ticker}</b> — preço atual indisponível para gestão")
            continue
        blocos.append(formatar_gestao(gerar_gestao_posicao(posicao, preco)))

    if not blocos:
        return ""

    return "📋 <b>GESTÃO DE POSIÇÕES ABERTAS</b>\n" + "\n\n".join(blocos)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Gestão de posições abertas")
    sub = parser.add_subparsers(dest="comando")

    p_add = sub.add_parser("adicionar", help="Registrar uma posição aberta")
    p_add.add_argument("ticker")
    p_add.add_argument("direcao", choices=["compra", "venda"])
    p_add.add_argument("preco_entrada", type=float)
    p_add.add_argument("stop", type=float)
    p_add.add_argument("alvo", type=float)
    p_add.add_argument("--quantidade", type=int, default=0)
    p_add.add_argument("--prazo-maximo", type=int, default=20)

    p_rem = sub.add_parser("remover", help="Remover posição (fechou a operação)")
    p_rem.add_argument("ticker")

    p_list = sub.add_parser("listar", help="Listar posições abertas")

    p_status = sub.add_parser("status", help="Mostrar gestão de uma posição com preço atual")
    p_status.add_argument("ticker")

    args = parser.parse_args()

    if args.comando == "adicionar":
        posicao = adicionar_posicao(
            args.ticker, args.direcao, args.preco_entrada,
            args.stop, args.alvo, args.quantidade, args.prazo_maximo
        )
        print(f"✅ Posição registrada: {posicao['ticker']} ({posicao['direcao']})")
        print(f"   Entrada {posicao['preco_entrada']} · Stop {posicao['stop']} · Alvo {posicao['alvo']}")

    elif args.comando == "remover":
        if remover_posicao(args.ticker):
            print(f"🗑️ Posição {args.ticker.upper()} removida (operação fechada).")
        else:
            print(f"⚠️ Posição {args.ticker.upper()} não encontrada.")

    elif args.comando == "listar":
        posicoes = carregar_posicoes()
        if not posicoes:
            print("Nenhuma posição aberta.")
        for ticker, p in posicoes.items():
            print(f"  {ticker} ({p['direcao']}) entrada {p['preco_entrada']} stop {p['stop']} alvo {p['alvo']}")

    elif args.comando == "status":
        posicoes = carregar_posicoes()
        ticker = args.ticker.upper()
        if ticker not in posicoes:
            print(f"⚠️ Posição {ticker} não encontrada.")
            sys.exit(1)
        try:
            import yfinance as yf
            import pandas as pd
            df = yf.download(f"{ticker}.SA", period="5d", interval="1d", auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.rename(columns=str.lower)
            preco = float(df["close"].iloc[-1])
        except Exception as e:
            print(f"⚠️ Não consegui buscar o preço atual: {e}")
            preco = float(input("Digite o preço atual: "))

        gestao = gerar_gestao_posicao(posicoes[ticker], preco)
        print(formatar_gestao(gestao))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()