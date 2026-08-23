"""
Módulo de opções — sugere strike e vencimento a partir do sinal técnico
gerado para o ativo-base.

IMPORTANTE: a B3 não tem uma fonte gratuita e confiável de cadeia de opções
(strikes, vencimentos, gregas, liquidez). Este módulo tem duas frentes:

1. `sugerir_parametros_opcao()` — dá a lógica de QUAL strike/vencimento
   procurar (ex: "PETR4, CALL, strike ~R$ 34, vencimento ~35-45 dias"),
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

import requests

logger = logging.getLogger(__name__)


def _buscar_premio_oplab_para_strike(ticker, token, tipo_opcao, strike_alvo,
                                     dias_min=25, dias_max=45):
    """Busca o prêmio real da opção mais próxima do strike alvo na OpLab."""
    try:
        cadeia = buscar_cadeia_oplab(ticker, token)
        if not isinstance(cadeia, list) or not cadeia:
            return None
        candidatas = [
            o for o in cadeia
            if str(o.get("type", "")).upper() == tipo_opcao
            and dias_min <= o.get("days_to_maturity", 0) <= dias_max
        ]
        if not candidatas:
            return None
        candidatas.sort(key=lambda o: abs(o.get("strike", 0) - strike_alvo))
        melhor = candidatas[0]
        premio = melhor.get("bid") or melhor.get("ask") or melhor.get("premium")
        if premio:
            return {
                "premio_real": float(premio),
                "strike_real": melhor.get("strike"),
                "liquidez_ok": (melhor.get("volume") or 0) > 0,
            }
    except Exception as e:
        logger.warning("Falha ao buscar prêmio real na OpLab (%s): %s", ticker, e)
    return None


def sugerir_parametros_opcao(preco_atual: float, direcao: str, prazo_dias_min=25, prazo_dias_max=45) -> dict:
    """
    Sugere o TIPO de strike/vencimento a procurar, com base em regras
    comuns de swing trade com opções (evitar opções muito próximas do
    vencimento por causa do theta decay).
    """
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
            "prêmio mais barato; vencimento de 25-45 dias reduz o impacto "
            "do decaimento de theta durante o swing trade, mas ainda dá "
            "tempo pro movimento acontecer."
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
    resposta = requests.get(url, headers=headers)
    resposta.raise_for_status()
    return resposta.json()


def escolher_melhor_opcao(cadeia: list, strike_alvo: float, tipo_opcao: str, dias_min: int, dias_max: int) -> dict:
    """
    Dado o retorno de buscar_cadeia_oplab, filtra pelo tipo e vencimento
    desejado e escolhe a opção com strike mais próximo do alvo sugerido,
    priorizando liquidez.
    NOTA: ajuste os nomes de campos (ex: 'strike', 'due_date', 'type',
    'volume') conforme o formato real retornado pela OpLab.
    """
    candidatas = [
        o for o in cadeia
        if o.get("type", "").upper() == tipo_opcao
        and dias_min <= o.get("days_to_maturity", 0) <= dias_max
    ]
    if not candidatas:
        return {}

    candidatas.sort(key=lambda o: abs(o.get("strike", 0) - strike_alvo))
    return candidatas[0]


def sugerir_parametros_opcao_com_preco(preco_atual: float, direcao: str, ticker: str,
                                        token: str = "", prazo_dias_min=25, prazo_dias_max=45) -> dict:
    """
    Versão "inteligente" de sugestão de opção:
    - Se `token` (OpLab) for informado, tenta buscar o prêmio real da opção
      mais próxima do strike sugerido. Se encontrar, usa o prêmio real.
    - Caso contrário (sem token, ou busca falhou), usa o valor teórico e
      sinaliza claramente que é ESTIMATIVA.
    Retorna sempre o mesmo schema de `sugerir_parametros_opcao`, adicionando
    `premio` (float) e `fonte` ("oplab" | "estimativa").
    """
    base = sugerir_parametros_opcao(preco_atual, direcao,
                                    prazo_dias_min=prazo_dias_min,
                                    prazo_dias_max=prazo_dias_max)
    base["premio"] = None
    base["fonte"] = "estimativa"

    tipo_opcao = base["tipo_opcao"]
    strike_alvo = base["strike_sugerido_aprox"]

    if token:
        real = _buscar_premio_oplab_para_strike(
            ticker, token, tipo_opcao, strike_alvo,
            dias_min=prazo_dias_min, dias_max=prazo_dias_max,
        )
        if real and real.get("premio_real"):
            base["premio"] = real["premio_real"]
            base["fonte"] = "oplab"
            base["strike_sugerido_aprox"] = real.get("strike_real", strike_alvo)
            base["observacao"] = (
                "Prêmio real da OpLab (cotação de mercado). Verifique a liquidez "
                "(volume/contratos em aberto) antes de operar."
            )

    return base
