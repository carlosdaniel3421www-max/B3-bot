"""
Robô do Telegram — o "atendente" que lê seus comandos no chat e responde.

Quando o relatório diário propõe uma entrada (🟢 ENTRAR), você decide:
   - Manda "/registrar TICKER"  -> o robô registra a posição com o plano
                                    (entrada/stop/alvo) que ele sugeriu
   - Não manda nada             -> a proposta é ignorada, nada é registrado

Comandos disponíveis:
   /registrar TICKER      Registra a posição a partir da proposta do relatório
   /registrar TICKER QTD  Idem, informando a quantidade de ações
   /remover TICKER        Remove uma posição (você fechou a operação)
   /posicoes              Mostra TODAS as posições abertas + gestão (proteger/sair)
   /status TICKER         Mostra a gestão de UMA posição com o preço atual

Este script é chamado pelo GitHub Actions a cada poucos minutos. Ele só
processa mensagens novas (usa offset do Telegram) e as responde no chat.
"""

import json
import logging
import sys
from datetime import date

import requests

import config
from diario_sinais import formatar_resumo_desempenho
from ai_analyzer import AIAnalyzer
from telegram_utils import enviar_mensagem
from trava import calcular_trava_manual, formatar_trava_manual
from posicoes import (
    adicionar_posicao, adicionar_trava, carregar_posicoes, carregar_propostas,
    formatar_gestao_todas, gerar_gestao_posicao, remover_posicao, registrar_da_proposta,
    _buscar_premio_trava, formatar_gestao_trava, gerar_gestao_trava,
    formatar_gestao, numero_finito,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CAMINHO_OFFSET = "telegram_offset.json"


def _ler_offset() -> int:
    try:
        with open(CAMINHO_OFFSET, "r", encoding="utf-8") as f:
            return json.load(f).get("last_update_id", 0)
    except Exception:
        return 0


def _salvar_offset(update_id: int):
    with open(CAMINHO_OFFSET, "w", encoding="utf-8") as f:
        json.dump({"last_update_id": update_id}, f)


def buscar_updates(token: str, offset: int, timeout: int = 30) -> list:
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        r = requests.get(url, params={"offset": offset + 1, "timeout": timeout}, timeout=timeout + 10)
        if not r.ok:
            logging.warning("getUpdates falhou: %s", r.text)
            return []
        return r.json().get("result", [])
    except Exception as e:
        logging.warning("Erro ao buscar updates: %s", e)
        return []


def responder(token: str, chat_id, texto: str):
    return enviar_mensagem(token, chat_id, texto)


def _precos_posicoes(posicoes: dict) -> dict:
    """Busca preços atuais de todas as posições (yfinance) pra gestão."""
    import pandas as pd
    import yfinance as yf
    from b3_swing_analyzer import _yf_lock

    precos = {}
    tickers = [t for t, p in posicoes.items() if p.get("tipo_operacao") != "trava"]
    if not tickers:
        return precos
    try:
        with _yf_lock:
            df = yf.download(
                [f"{t}.SA" for t in tickers], period="5d", interval="1d",
                auto_adjust=False, threads=False, timeout=15,
                progress=False, group_by="ticker",
            )
        for t in tickers:
            try:
                d = df.get(t)
                if d is None:
                    d = df.get(f"{t}.SA")
                if d is None and len(tickers) == 1 and not isinstance(df.columns, pd.MultiIndex):
                    d = df
                if d is None:
                    continue
                if isinstance(d.columns, pd.MultiIndex):
                    d.columns = d.columns.get_level_values(0)
                d = d.rename(columns=str.lower)
                indice = pd.to_datetime(d.index)
                if indice.tz is not None:
                    indice = indice.tz_convert("America/Sao_Paulo")
                d = d.loc[indice.date < pd.Timestamp.now(tz="America/Sao_Paulo").date()]
                preco = float(d["close"].iloc[-1])
                precos[t] = preco if numero_finito(preco) and preco > 0 else None
            except Exception:
                precos[t] = None
    except Exception as e:
        logging.warning("Falha ao buscar preços: %s", e)
    return precos


def processar_comando(token: str, chat_id, texto: str) -> str:
    """Processa um comando e devolve a resposta a enviar."""
    partes = texto.strip().split()
    if not partes:
        return None
    comando = partes[0].lower().split("@", 1)[0]
    args = partes[1:]

    if comando == "/carteira":
        from carteira import avaliar_carteira, formatar_resumo_carteira
        return formatar_resumo_carteira(avaliar_carteira(
            carregar_posicoes(), config.CAPITAL_DISPONIVEL, config.RISCO_MAX_CARTEIRA_PCT,
            config.EXPOSICAO_MAX_SETOR_PCT, config.SETORES, date.today().isoformat(),
        ))

    if comando == "/gatilho":
        if len(args) != 4:
            return "Uso: /gatilho TICKER PRECO_ATUAL ATR DATA_COTACAO (AAAA-MM-DD). Nao envia ordens."
        from setups import validar_gatilho
        try:
            proposta = carregar_propostas().get(args[0].upper(), {})
            plano = proposta.get("plano_setup")
            if not plano:
                return "Sem candidato com setup registrado; gere novo relatorio."
            if date.fromisoformat(args[3]) != date.today():
                return "Informe a data de hoje para conferir a cotacao; nao use precos antigos."
            validado = validar_gatilho(plano, float(args[1]), float(args[2]), args[3])
            import html
            return (f"<b>{html.escape(args[0].upper())}: {validado['estado'].upper()}</b>\n"
                    + html.escape(validado["motivo"]) +
                    "\nConferencia com dados MANUAIS, nao cotacao certificada nem execucao. "
                    "Reavalie /carteira e custos. Registre somente operacoes realmente executadas.")
        except (TypeError, ValueError):
            return "Dados invalidos; confira preco, ATR e data AAAA-MM-DD."

    if comando in ("/registrar", "/adicionar"):
        if not args:
            return "Uso: /registrar TICKER (usa a proposta do robô)\nou: /registrar TICKER DIRECAO PRECO STOP ALVO (registro manual de qualquer operação)"
        ticker = args[0].upper()

        # Registro manual: /registrar PETR4 compra 43.11 40.50 48.22 [QTD]
        if len(args) >= 5:
            try:
                direcao = args[1].lower()
                if direcao not in ("compra", "venda"):
                    return "⚠️ Direção inválida. Use: /registrar TICKER compra PRECO STOP ALVO [QTD]\nou: /registrar TICKER venda PRECO STOP ALVO [QTD]"
                preco = float(args[2])
                stop = float(args[3])
                alvo = float(args[4])
                if not all(numero_finito(p) and p > 0 for p in (preco, stop, alvo)):
                    return "⚠️ Preços precisam ser números finitos e positivos."
                if direcao == "compra" and not (stop < preco < alvo):
                    return "⚠️ Na compra, stop < entrada < alvo. Ex: /registrar PETR4 compra 43.11 40.50 48.22"
                if direcao == "venda" and not (alvo < preco < stop):
                    return "⚠️ Na venda, alvo < entrada < stop. Ex: /registrar PETR4 venda 43.11 44.50 40.00"
                quantidade = int(args[5]) if len(args) > 5 else 0
                posicao = adicionar_posicao(ticker, direcao, preco, stop, alvo, quantidade=quantidade)
                return f"✅ <b>{ticker}</b> registrada manualmente ({posicao['direcao']}). Entrada R$ {posicao['preco_entrada']} · Stop R$ {posicao['stop']} · Alvo R$ {posicao['alvo']}. Agora acompanho todo dia."
            except ValueError as e:
                return f"⚠️ Valor inválido: {e}. Use números com ponto (.) como separador decimal. Ex: 43.11"
            except Exception as e:
                logging.warning("Erro ao registrar %s manualmente: %s", ticker, e)
                return f"⚠️ Erro ao registrar: {str(e)[:200]}"

        # Registro pela proposta do robô: /registrar TICKER [QTD]
        try:
            quantidade = int(args[1]) if len(args) > 1 else 0
            posicao, msg = registrar_da_proposta(ticker, quantidade=quantidade)
            return msg
        except ValueError as e:
            return f"⚠️ Valor inválido: {e}"

    if comando in ("/remover", "/sair", "/fechar"):
        if not args:
            return "Uso: /remover TICKER"
        ticker = args[0].upper()
        if remover_posicao(ticker):
            return f"🗑️ {ticker} removida (operação fechada). Bom trade!"
        return f"⚠️ {ticker} não está registrada."

    if comando in ("/posicoes", "/posicao"):
        posicoes = carregar_posicoes()
        if not posicoes:
            return "📋 Nenhuma posição aberta. Quando o robô sugerir ENTRAR, responda /registrar TICKER."
        precos = _precos_posicoes(posicoes)
        return formatar_gestao_todas(posicoes, precos)

    if comando in ("/status",):
        if not args:
            return "Uso: /status TICKER"
        ticker = args[0].upper()
        posicoes = carregar_posicoes()
        if ticker not in posicoes:
            return f"⚠️ {ticker} não está registrada. Propostas disponíveis: {', '.join(carregar_propostas().keys()) or 'nenhuma'}."
        precos = _precos_posicoes({ticker: posicoes[ticker]})
        return formatar_gestao_todas({ticker: posicoes[ticker]}, precos)

    if comando in ("/propostas", "/proposta"):
        propostas = carregar_propostas()
        if not propostas:
            return "Nenhuma proposta pendente. O robô propõe quando um ativo dá ENTRAR (score ≥ 8)."
        linhas = ["📌 <b>Propostas de entrada em aberto:</b>"]
        for t, p in propostas.items():
            if p.get("estado_entrada") == "candidato" or p.get("plano_setup") is not None:
                from setups import _data
                plano = p.get("plano_setup")
                try:
                    idade = (date.today() - _data(plano.get("data_sinal"))).days
                except (AttributeError, ValueError, TypeError, OverflowError):
                    linhas.append(f"  {t}: INVALIDO, data de sinal indisponivel; gere novo relatorio.")
                    continue
                if idade > 4:
                    linhas.append(f"  {t}: EXPIRADO, sinal fora da validade de 4 dias corridos.")
                    continue
                if idade < 0:
                    linhas.append(f"  {t}: INVALIDO, data de sinal futura; gere novo relatorio.")
                    continue
                linhas.append(f"  {t}: CANDIDATO, aguardar gatilho {p['preco_entrada']}; consulte /gatilho.")
                continue
            linhas.append(
                f"  {t} ({p['direcao']}) entrada R$ {p['preco_entrada']} · "
                f"stop R$ {p['stop']} · alvo R$ {p['alvo']} — responda /registrar {t}"
            )
        return "\n".join(linhas)

    if comando in ("/sinais", "/desempenho", "/performance"):
        return formatar_resumo_desempenho()

    if comando in ("/trava", "/verificar"):
        # /trava compra 10.86 0.22 11.56 0.09
        # /trava venda 9.86 0.24 9.06 0.15
        if len(args) < 5:
            return (
                "Uso: /trava DIRECAO STRIKE_COMPRA PREMIO_COMPRA STRIKE_VENDA PREMIO_VENDA\n"
                "Você informa os PREÇOS ATUAIS que está vendo no home broker:\n"
                "  /trava compra 10.86 0.22 11.56 0.09\n"
                "  /trava venda 9.86 0.24 9.06 0.15\n"
                "O robô calcula se a trava ainda compensa com esses preços."
            )
        try:
            direcao = args[0].lower()
            strike_comp = float(args[1])
            premio_comp = float(args[2])
            strike_vend = float(args[3])
            premio_vend = float(args[4])
            trava = calcular_trava_manual(
                direcao, strike_comp, premio_comp, strike_vend, premio_vend,
            )
            return ("🔒 <b>Calculo manual de trava</b>\n"
                    "Vencimento nao informado: calculo aritmetico, nao valida prazo nem autoriza operar.\n"
                    + formatar_trava_manual(trava))
        except ValueError as e:
            return f"⚠️ {e}\nExemplo: /trava compra 10.86 0.22 11.56 0.09"
        except Exception as e:
            logging.warning("Erro ao calcular trava manual: %s", e)
            return f"⚠️ Erro ao calcular: {str(e)[:200]}"

    if comando in ("/analisar_posicoes", "/analisar_posições", "/analisar", "/gestao_ia"):
        return _analisar_posicoes_ia()

    if comando in ("/relatorio", "/report", "/diario"):
        return _acionar_relatorio_github()

    if comando in ("/trava_registrar", "/registrar_trava", "/tr"):
        # /trava_registrar TICKER compra STRIKE_C PREMIO_C STRIKE_V PREMIO_V STOP ALVO [VENC]
        if len(args) < 8:
            return (
                "Uso: /trava_registrar TICKER DIRECAO STRIKE_COMPRA PREMIO_COMPRA "
                "STRIKE_VENDA PREMIO_VENDA STOP_PREMIO ALVO_PREMIO [VENCIMENTO]\n"
                "Exemplo: /trava_registrar CMIG4 compra 10.86 0.22 11.56 0.09 0.065 0.45 2026-10-16\n"
                "Os valores STOP e ALVO são no PRÊMIO da trava (R$ por contrato)."
            )
        try:
            ticker = args[0].upper()
            tipo = args[1].lower()

            if len(args) not in (8, 9):
                return "Uso: /trava_registrar TICKER DIRECAO SC PC SV PV STOP ALVO [VENCIMENTO]"
            try:
                numeros = [float(arg) for arg in args[2:8]]
            except ValueError:
                return "⚠️ Valor inválido: use números separados por espaço."
            if not all(numero_finito(n) for n in numeros):
                return "⚠️ Valor inválido: use números finitos."
            vencimento = args[8] if len(args) == 9 else ""

            strike_comp, premio_comp, strike_vend, premio_vend = numeros[0], numeros[1], numeros[2], numeros[3]
            stop_premio = numeros[4]
            alvo_premio = numeros[5]
            trava = adicionar_trava(
                ticker, tipo, strike_comp, premio_comp, strike_vend, premio_vend,
                stop_premio, alvo_premio, vencimento=vencimento,
            )
            return (
                f"🔒 <b>{ticker}</b> — TRAVA registrada!\n"
                f"  Comprar {trava['strike_comprado']:.2f} @ R$ {trava['premio_comprado']:.2f}\n"
                f"  Vender {trava['strike_vendido']:.2f} @ R$ {trava['premio_vendido']:.2f}\n"
                f"  💰 Débito: R$ {trava['preco_entrada']:.2f} · Stop: R$ {trava['stop']:.2f} · Alvo: R$ {trava['alvo']:.2f}\n"
                f"  Agora acompanho essa trava todo dia."
            )
        except ValueError as e:
            return f"⚠️ {e}"
        except Exception as e:
            logging.warning("Erro ao registrar trava: %s", e)
            return f"⚠️ Erro ao registrar trava: {str(e)[:200]}"

    if comando in ("/help", "/ajuda", "/start", "/comandos"):
        return (
            "🤖 <b>Comandos do robô:</b>\n"
            "  /carteira — risco agregado e limites para novas exposicoes\n"
            "  /gatilho TICKER PRECO ATR DATA — conferencia manual de candidato, sem ordens\n"
            "  /relatorio — dispara o relatório diário completo (gráficos + IA + travas)\n"
            "  /analisar_posicoes — IA analisa suas posições abertas (manter/ajustar/sair)\n"
            "  /registrar TICKER — registra a posição que o robô propôs\n"
            "  /registrar TICKER DIRECAO PRECO STOP ALVO — registra QUALQUER\n"
            "    operação sua (ex: /registrar PETR4 compra 43.11 40.50 48.22)\n"
            "  /remover TICKER — remove a posição (fechou a operação)\n"
            "  /posicoes — mostra todas as posições + o que fazer hoje\n"
            "  /status TICKER — gestão de uma posição com preço atual\n"
            "  /propostas — propostas de entrada em aberto\n"
            "  /sinais — taxa de acerto dos sinais que o robô já emitiu\n"
            "  /trava DIRECAO STRIKE1 PREMIO1 STRIKE2 PREMIO2 — verifica se a\n"
            "    trava compensa com os PREÇOS ATUAIS do home broker\n"
            "    (ex: /trava compra 10.86 0.22 11.56 0.09)\n"
            "  /trava_registrar TICKER DIRECAO SC PC SV PV STOP ALVO [VENC] — registra\n"
            "    a trava que você montou (para acompanhar todo dia)\n"
            "    (ex: /trava_registrar CMIG4 compra 10.86 0.22 11.56 0.09 0.065 0.45)"
        )

    return None


def _acionar_relatorio_github() -> str:
    """
    Dispara o workflow do relatório diário no GitHub Actions via API.
    O relatório roda lá (grátis, robusto) e envia o resultado pro Telegram.
    """
    import requests

    token = getattr(config, "GITHUB_TOKEN", "")
    if not token:
        return "❌ GITHUB_TOKEN não configurado. Crie um token no GitHub (Settings → Developer settings → Personal access tokens → Fine-grained tokens) com permissão 'Actions: Write' e adicione como secret no Render."

    repo = "carlosdaniel3421www-max/B3-bot"
    url = f"https://api.github.com/repos/{repo}/actions/workflows/relatorio.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {"ref": "main"}

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code == 204:
            return (
                "🚀 <b>Relatório acionado!</b>\n"
                "O relatório está sendo gerado no GitHub Actions e chegará aqui em ~2 minutos.\n"
                "Acompanhe em: https://github.com/carlosdaniel3421www-max/B3-bot/actions"
            )
        elif r.status_code == 401:
            return "❌ Token inválido ou sem permissão. Verifique o GITHUB_TOKEN no Render."
        elif r.status_code == 404:
            return "❌ Workflow não encontrado. Verifique se o repositório e o nome do workflow estão corretos."
        else:
            return f"⚠️ Erro ao disparar relatório (código {r.status_code}): {r.text[:200]}"
    except requests.RequestException as e:
        return f"⚠️ Erro de rede ao acionar o relatório: {e}"


def _montar_analisador_ia() -> AIAnalyzer | None:
    """Cria o AIAnalyzer (Gemini + Nemotron) se as chaves estiverem configuradas."""
    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key and not getattr(config, "CARLOS", ""):
        return None
    return AIAnalyzer(
        api_key=api_key,
        model=getattr(config, "GEMINI_MODEL", None),
        timeout_seconds=getattr(config, "GEMINI_TIMEOUT_SECONDS", 45),
        max_retries=getattr(config, "GEMINI_MAX_RETRIES", 3),
        CARLOS=getattr(config, "CARLOS", ""),
        CARLOS_model=getattr(config, "CARLOS_model", "nemotron-3-ultra-free"),
        CARLOS_base_url=getattr(config, "CARLOS_base_url", "https://opencode.ai/zen/v1"),
    )


def _analisar_posicoes_ia() -> str:
    """Gestão determinística primeiro; IA apenas complementa posições elegíveis."""
    import html as _html

    posicoes = carregar_posicoes()
    if not posicoes:
        return "📋 Nenhuma posição aberta para analisar."

    precos = _precos_posicoes(posicoes)

    blocos = []
    resumo = []
    elegiveis = set()
    saida_obrigatoria = False
    for ticker, posicao in posicoes.items():
        if posicao.get("tipo_operacao") == "trava":
            premio = _buscar_premio_trava(ticker, posicao)
            gestao = gerar_gestao_trava(posicao, premio)
            bloco = formatar_gestao_trava(posicao, premio)
            blocos.append(bloco)
            if gestao["acao"] == "INDISPONÍVEL":
                continue
            saida_obrigatoria |= gestao["acao"] in ("STOP", "ALVO", "VERIFICAR VENCIMENTO")
        else:
            try:
                gestao = gerar_gestao_posicao(posicao, precos.get(ticker))
            except ValueError:
                blocos.append(f"{ticker}: cotação/registro indisponível para gestão. Sem recomendação de manter/sair.")
                continue
            bloco = formatar_gestao(gestao)
            blocos.append(bloco)
            saida_obrigatoria |= gestao["acao"] in ("SAIR AGORA", "FECHAR", "FECHAR POR TEMPO")
        elegiveis.add(ticker)
        resumo.append(bloco + f"\nData de entrada: {posicao.get('data_entrada', 'não registrada')}")

    base = "📋 <b>Gestão determinística das posições</b>\nData atual: " + date.today().isoformat() + "\n\n" + "\n\n".join(blocos)
    if not elegiveis:
        return base + "\n\nSem cotações válidas para análise; IA não consultada."
    # Bloqueio por construção: não publica texto livre da IA quando existe saída
    # determinística, mesmo que a IA rotule 'sair' e contradiga isso na explicação.
    if saida_obrigatoria:
        return base + "\n\nIA não consultada: prevalece a saída/verificação determinística."

    prompt = (
        f"Data atual: {date.today().isoformat()}. Você é um gestor de risco na B3. "
        "Complemente a gestão determinística abaixo, sem contrariar stop/alvo. "
        "Os preços são de fechamento, não tempo real e não garantem execução. "
        "Sem cotação válida não recomende manter/sair; não analise tickers ausentes. "
        "Risco limitado não é risco baixo: uma trava pode perder todo o débito. "
        "O tempo não é necessariamente favorável; considere vencimento, theta, liquidez, exercício e custos. "
        "Limites teóricos pressupõem ambas as pernas intactas e excluem custos. "
        "Não aumente o risco nem afrouxe stops registrados.\n\n"
        + "\n\n".join(resumo)
        + "\n\nPara cada posição, avalie: manter, ajustar stop/alvo, ou sair. "
        "Responda APENAS com JSON no formato:\n"
        '{"analises": [{"ticker": "...", "acao": "manter|ajustar|sair", '
        '"explicacao": "...", "risco": "..."}]}'
    )

    analisador = _montar_analisador_ia()
    if analisador is None:
        return base + "\n\n❌ IA não configurada. Adicione GEMINI_API_KEY."

    try:
        resposta, provedor = analisador.analisar_prompt(prompt)
    except Exception as e:
        logging.warning("Falha na IA ao analisar posições: %s", e)
        return base + "\n\n⚠️ Erro ao consultar IA; gestão determinística preservada."

    if not resposta:
        return base + "\n\n⚠️ A IA não conseguiu analisar as posições agora."

    # Formata a resposta
    analises = resposta.get("analises", []) if isinstance(resposta, dict) else []
    if not isinstance(analises, list) or not analises:
        return base + "\n\nResposta da IA inválida; gestão determinística preservada."

    linhas = [base, "\n🧠 <b>Análise das posições (" + _html.escape(str(provedor)) + "):</b>"]
    emoji_acao = {"manter": "✅", "ajustar": "⚙️", "sair": "🚪"}
    for a in analises:
        if not isinstance(a, dict):
            continue
        ticker = a.get("ticker", "?")
        acao = a.get("acao", "?")
        if not isinstance(ticker, str) or ticker not in elegiveis or not isinstance(acao, str):
            continue
        if acao.lower() not in emoji_acao:
            continue
        emoji = emoji_acao[acao.lower()]
        explicacao = _html.escape(str(a.get("explicacao", "")), quote=False)
        risco = _html.escape(str(a.get("risco", "")), quote=False)
        linhas.append(f"\n{emoji} <b>{_html.escape(ticker)}</b> — {acao.upper()}")
        if explicacao:
            linhas.append(f"  💡 {explicacao}")
        if risco:
            linhas.append(f"  ⚠️ {risco}")

    return "\n".join(linhas)


def main():
    token = getattr(config, "TELEGRAM_TOKEN", "")
    chat_id = str(getattr(config, "TELEGRAM_CHAT_ID", ""))
    if not token or not chat_id:
        logging.warning("TELEGRAM_TOKEN/TELEGRAM_CHAT_ID não configurados.")
        return

    offset = _ler_offset()
    updates = buscar_updates(token, offset)
    ultimo_id = offset

    for upd in updates:
        update_id = upd.get("update_id", 0)
        ultimo_id = max(ultimo_id, update_id)

        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            continue

        msg_chat = str(msg.get("chat", {}).get("id", ""))
        if msg_chat != chat_id:
            continue  # ignora mensagens de outros chats

        texto = msg.get("text") or ""
        if not texto:
            continue

        resposta = processar_comando(token, msg_chat, texto)
        if resposta:
            responder(token, msg_chat, resposta)
            logging.info("Comando %s processado para chat %s", texto, msg_chat)

    if ultimo_id != offset:
        _salvar_offset(ultimo_id)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
