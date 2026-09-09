"""
Módulo de opções — sugere strike e vencimento a partir do sinal técnico
gerado para o ativo-base.

IMPORTANTE: a B3 não tem uma fonte gratuita e confiável de cadeia de opções
(strikes, vencimentos, gregas, liquidez). Este módulo tem duas frentes:

1. `sugerir_parametros_opcao()` — dá a lógica de QUAL strike/vencimento
   procurar (ex: "PETR4, CALL, strike ~R$ 34, vencimento 14-30 dias corridos"),
   mesmo sem cadeia real. Você usa isso para buscar manualmente no home
   broker ou na OpLab.

2. `buscar_cadeia_oplab()` — integração pronta com a API da OpLab
   (oplab.com.br), que tem dados reais de opções da B3. Requer uma chave
   de API paga. Preencha OPLAB_TOKEN em config.py para usar.

3. `sugerir_parametros_opcao_com_preco()` — versão "inteligente": se a
   OpLab estiver configurada, tenta buscar o prêmio real; senão (ou se a
   busca falhar), cai pro valor teórico e sinaliza que é estimativa.
"""

import logging
import math
from datetime import date

import requests

from fonte_opcoes import _faixa_dias_corridos

logger = logging.getLogger(__name__)


def _buscar_premio_oplab_para_strike(ticker, token, tipo_opcao, strike_alvo,
                                     dias_min=None, dias_max=None):
    """Busca o prêmio real da opção mais próxima do strike alvo na OpLab."""
    try:
        cadeia = buscar_cadeia_oplab(ticker, token)
        if not isinstance(cadeia, list) or not cadeia:
            return None
        melhor = escolher_melhor_opcao(
            cadeia, strike_alvo, tipo_opcao,
            dias_corridos_min=dias_min, dias_corridos_max=dias_max)
        if not melhor:
            return None
        # A sugestao e de COMPRA de call/put: custo de entrada e o ask, nao bid.
        premio = melhor.get("ask")
        if premio:
            return {
                "premio_real": float(premio),
                "strike_real": melhor.get("strike"),
                "liquidez_ok": (melhor.get("volume") or 0) > 0,
                "vencimento": melhor.get("due_date"),
                "dias_corridos": (date.fromisoformat(str(melhor["due_date"])[:10]) - date.today()).days,
            }
    except Exception as e:
        logger.warning("Falha ao buscar prêmio real na OpLab (%s): %s", ticker, e)
    return None


def sugerir_parametros_opcao(preco_atual: float, direcao: str, prazo_dias_min=None, prazo_dias_max=None) -> dict:
    """
    Sugere o TIPO de strike/vencimento a procurar, com base em regras
    comuns de swing trade com opções (evitar opções muito próximas do
    vencimento por causa do theta decay). Prazos em dias corridos, por
    padrao da politica (14..30); personalizacao apenas estreita a janela.
    """
    prazo_dias_min, prazo_dias_max = _faixa_dias_corridos(prazo_dias_min, prazo_dias_max)
    if (direcao not in ("compra", "venda")
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                       and math.isfinite(v) and v > 0
                       for v in (preco_atual, prazo_dias_min, prazo_dias_max))
            or prazo_dias_min > prazo_dias_max):
        raise ValueError("Preco, direcao ou faixa de vencimento invalidos")
    tipo_opcao = "CALL" if direcao == "compra" else "PUT"

    # Regra simples: strike levemente OTM (fora do dinheiro) para dar
    # mais alavancagem, mas não tão longe que fique ilíquido.
    if tipo_opcao == "CALL":
        strike_sugerido = round(preco_atual * 1.03, 2)  # ~3% OTM
    else:
        strike_sugerido = round(preco_atual * 0.97, 2)  # ~3% OTM

    return {
        "tipo_opcao": tipo_opcao,
        "strike_sugerido_aprox": strike_sugerido,
        "faixa_strike": (round(preco_atual * 0.98, 2), round(preco_atual * 1.06, 2))
                        if tipo_opcao == "CALL" else
                        (round(preco_atual * 0.94, 2), round(preco_atual * 1.02, 2)),
        "vencimento_sugerido": f"entre {prazo_dias_min} e {prazo_dias_max} dias corridos",
        "motivo": (
            "Strike levemente fora do dinheiro busca mais alavancagem com "
            f"premio mais barato; vencimento de {prazo_dias_min}-{prazo_dias_max} "
            "dias corridos respeita o limite de 30 dias e evita novas entradas "
            "nas duas semanas finais. Theta ainda pode causar perdas."
        ),
        "observacao": (
            "Confirme liquidez (volume/contratos em aberto) da opção antes "
            "de operar — opção sem liquidez tem spread ruim entre compra e venda."
        ),
    }


def buscar_cadeia_oplab(ticker: str, token: str) -> list:
    """
    Busca a cadeia de opções real via API da OpLab.
    Retorna lista de opções com strike, vencimento, tipo, bid/ask, gregas.
    Consulte a documentação atual em https://oplab.com.br/ para o endpoint
    exato, pois a API pode mudar; esta função é um esqueleto pronto para
    ajustar as chaves do JSON de resposta conforme a doc vigente.
    """
    url = f"https://api.oplab.com.br/v3/market/options/{ticker.upper()}"
    headers = {"Access-Token": token}
    resposta = requests.get(url, headers=headers, timeout=20)
    resposta.raise_for_status()
    return resposta.json()


def escolher_melhor_opcao(cadeia: list, strike_alvo: float, tipo_opcao: str,
                          dias_min: int = 1, dias_max: int = 60, *,
                          dias_corridos_min=None, dias_corridos_max=None) -> dict:
    """
    Dado o retorno de buscar_cadeia_oplab, filtra pelo tipo e vencimento
    desejado e escolhe a opção com strike mais próximo do alvo sugerido,
    priorizando liquidez. Exige due_date; days_to_maturity nao comprova prazo.
    Nesta API OpLab dias_min/dias_max continuam sendo dias corridos adicionais,
    nao DU. Limites opcionais so estreitam a politica (14..30 por padrao).
    NOTA: ajuste os nomes de campos (ex: 'strike', 'due_date', 'type',
    'volume') conforme o formato real retornado pela OpLab.
    """
    try:
        minimo, maximo = _faixa_dias_corridos(dias_corridos_min, dias_corridos_max)
    except ValueError:
        return {}
    candidatas = []
    hoje = date.today()
    for o in cadeia:
        if not isinstance(o, dict) or str(o.get("type", "")).upper() != tipo_opcao.upper():
            continue
        valores = [o.get(c) for c in ("strike", "ask", "volume")]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   and math.isfinite(v) and v > 0 for v in valores):
            continue
        try:
            dias = (date.fromisoformat(str(o.get("due_date"))[:10]) - hoje).days
        except ValueError:
            continue
        if not minimo <= dias <= maximo or not dias_min <= dias <= dias_max:
            continue
        bid = o.get("bid")
        if bid is not None and (not isinstance(bid, (int, float)) or isinstance(bid, bool)
                                or not math.isfinite(bid) or bid < 0 or bid > o["ask"]):
            continue
        candidatas.append(o)
    if not candidatas:
        return {}

    candidatas.sort(key=lambda o: abs(o.get("strike", 0) - strike_alvo))
    return candidatas[0]


def sugerir_parametros_opcao_com_preco(preco_atual: float, direcao: str, ticker: str,
                                        token: str = "", prazo_dias_min=None, prazo_dias_max=None) -> dict:
    """
    Versão "inteligente" de sugestão de opção:
    - Se `token` (OpLab) for informado, tenta buscar o prêmio real da opção
      mais próxima do strike sugerido. Se encontrar, usa o prêmio real.
    - Caso contrário (sem token, ou busca falhou), usa o valor teórico e
      sinaliza claramente que é ESTIMATIVA.
    Retorna sempre o mesmo schema de `sugerir_parametros_opcao`, adicionando
    `premio` (float) e `fonte` ("oplab" | "estimativa").
    """
    prazo_dias_min, prazo_dias_max = _faixa_dias_corridos(prazo_dias_min, prazo_dias_max)
    base = sugerir_parametros_opcao(preco_atual, direcao,
                                    prazo_dias_min=prazo_dias_min,
                                    prazo_dias_max=prazo_dias_max)
    base["premio"] = None
    base["fonte"] = "estimativa"

    tipo_opcao = base["tipo_opcao"]
    strike_alvo = base["strike_sugerido_aprox"]
    from trava import _premio_bs_europeu
    dias_corridos = (prazo_dias_min + prazo_dias_max) / 2
    base["premio"] = round(_premio_bs_europeu(
        preco_atual, strike_alvo, dias_corridos / 365.0, 0.105, 0.30, tipo_opcao.lower()), 2)
    base["observacao"] = (
        "Estimativa Black-Scholes, volatilidade 30% a.a., juros 10.5% a.a., "
        "sem dividendos; nao e cotacao nem preco executavel. Confirme liquidez."
    )

    if token:
        real = _buscar_premio_oplab_para_strike(
            ticker, token, tipo_opcao, strike_alvo,
            dias_min=prazo_dias_min, dias_max=prazo_dias_max,
        )
        if real and real.get("premio_real"):
            base["premio"] = real["premio_real"]
            base["fonte"] = "oplab"
            base["strike_sugerido_aprox"] = real.get("strike_real", strike_alvo)
            base["vencimento_sugerido"] = real.get("vencimento") or f"{real['dias_corridos']} dias corridos"
            base["liquidez_ok"] = real["liquidez_ok"]
            base["observacao"] = (
                "Ask informado pela OpLab para compra; atualidade e execucao nao garantidas. Verifique a liquidez "
                "(volume/contratos em aberto) antes de operar."
            )

    return base
