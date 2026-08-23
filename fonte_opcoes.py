"""
Fonte de dados real de opções da B3 — opcoes.net.br (API pública gratuita).

Dados de "último pregão" (fechamento do dia útil anterior), sem token/login:
    GET https://opcoes.net.br/api/v1?z=<ts>&r0t=LastQuotesInfo&r1t=OptionsChain
        &r1p.underlying_asset_id=TICKER&r1p.skip=0&r1p.load=8&r1p.underlying_quotes=true

Retorna JSON com a cadeia completa: strikes, vencimentos, calls/puts com
preços, bid/ask, volume, delta, gama, theta, vega e volatilidade implícita.

IMPORTANTE:
- É dado de FECHAMENTO do último pregão, NÃO tempo real. Suficiente para
  decisões de swing trade (dias/semanas).
- Se a API falhar ou o ativo não tiver opções, retorna None e o sistema cai
  para a estimativa Black-Scholes (trava.py).
- Formato de cada série é posicional: [suffix, fm, modelo, strike, aio, dist,
  preço_último, variação, data_hora, n_negócios, volume, vol_impl, delta, ...]
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://opcoes.net.br/api/v1"
TIMEOUT = 20


def buscar_cadeia_opcoesnet(ticker: str) -> dict | None:
    """
    Busca a cadeia de opções do ticker na API do opcoes.net.br.
    Retorna dict com underlying, strikes, expirations, calls/puts.
    None se falhar ou não houver dados.
    """
    ticker = ticker.upper()
    try:
        z = int(time.time() / 10000)
        params = {
            "z": z,
            "r0t": "LastQuotesInfo",
            "r1t": "OptionsChain",
            "r1p.columns_info": "true",
            "r1p.load": "8",
            "r1p.skip": "0",
            "r1p.underlying_asset_id": ticker,
            "r1p.underlying_quotes": "true",
        }
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        resp = requests.get(BASE_URL, params=params, headers=headers, timeout=TIMEOUT)
        if resp.status_code != 200:
            logger.warning("opcoes.net.br %s -> status %s", ticker, resp.status_code)
            return None
        data = resp.json()
        if not data.get("success"):
            logger.warning("opcoes.net.br %s -> success=false", ticker)
            return None

        # Acha o resultado do tipo OptionsChain
        for req in data.get("requests", []):
            if req.get("type") == "OptionsChain":
                results = req.get("results", {})
                if not results:
                    return None
                # Preço do ativo-base (chave 'p' dentro de underlying_asset)
                ua = results.get("underlying_asset") or {}
                preco_base = ua.get("p")
                # Vencimentos
                expirations_raw = results.get("expirations") or []
                expirations = []
                for e in expirations_raw:
                    expirations.append({
                        "dt": e.get("dt"),
                        "du": e.get("du"),
                        "mensal": bool(e.get("m")),
                        "calls": e.get("calls") or [],
                        "puts": e.get("puts") or [],
                    })
                return {
                    "ticker": ticker,
                    "preco_base": preco_base,
                    "strikes": (results.get("strikes") or {}).get("list") or [],
                    "expirations": expirations,
                }
        logger.warning("opcoes.net.br %s -> sem OptionsChain no payload", ticker)
        return None
    except requests.RequestException as e:
        logger.warning("opcoes.net.br %s -> erro de rede: %s", ticker, e)
        return None
    except Exception as e:
        logger.warning("opcoes.net.br %s -> erro inesperado: %s", ticker, e)
        return None


def _serie_para_opcao(serie: list, columns: list) -> dict:
    """
    Converte um array posicional de série para dict com as chaves das colunas.
    columns: lista de dicts {id, ...} retornados pelo endpoint (columns_info).
    """
    resultado = {}
    for idx, col in enumerate(columns):
        if idx < len(serie):
            resultado[col.get("id", str(idx))] = serie[idx]
    return resultado


def buscar_cadeia_estruturada(ticker: str) -> dict | None:
    """
    Busca a cadeia e devolve já estruturada para consumo fácil:
    {
        'preco_base': float,
        'expirations': [ { 'dt': ..., 'du': ..., 'calls': {strike: {'p':..., 'b':..., 'a':..., 'n':...}}, 'puts': {...} } ]
    }
    """
    raw = buscar_cadeia_opcoesnet(ticker)
    if not raw:
        return None

    # Precisamos das colunas para mapear os arrays. A chamada com
    # columns_info=true não expõe as colunas no mesmo nível; usamos a
    # ordem conhecida do site (ver fonte_opcoes.ler_ordem_colunas).
    # Ordem posicional documentada:
    # 0 suffix | 1 fm | 2 modelo | 3 strike | 4 aio | 5 dist |
    # 6 preço_último | 7 variação | 8 data_hora | 9 n_negócios |
    # 10 volume | 11 vol_impl | 12 delta | ...
    col_strike = 3
    col_preco = 6
    col_negocios = 9
    col_volume = 10

    def _mapa(series: list) -> dict:
        m = {}
        for s in series:
            if len(s) <= col_strike:
                continue
            try:
                strike = float(s[col_strike])
            except (TypeError, ValueError):
                continue
            m[strike] = {
                "strike": strike,
                "preco": _to_float(s[col_preco]),
                "negocios": _to_float(s[col_negocios]),
                "volume": _to_float(s[col_volume]),
                "sufixo": s[0] if s and s[0] else "",
                "modelo": s[2] if len(s) > 2 else "",
            }
        return m

    expirations = []
    for e in raw.get("expirations", []):
        expirations.append({
            "dt": e["dt"],
            "du": e["du"],
            "mensal": e["mensal"],
            "calls": _mapa(e.get("calls", [])),
            "puts": _mapa(e.get("puts", [])),
        })

    return {
        "ticker": ticker,
        "preco_base": raw.get("preco_base"),
        "expirations": expirations,
    }


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def buscar_melhor_vencimento(cadeia: dict, dias_min: int = 15, dias_max: int = 60,
                             preferir_mensal: bool = True) -> dict | None:
    """
    Escolhe o melhor vencimento da cadeia: o mensal (se preferir_mensal)
    com 'du' (dias úteis) dentro da faixa, ou o que tiver mais negócios.
    Retorna o dict do vencimento ou None.
    """
    if not cadeia or not cadeia.get("expirations"):
        return None

    candidatos = [e for e in cadeia["expirations"] if dias_min <= e["du"] <= dias_max]
    if not candidatos:
        candidatos = list(cadeia["expirations"])

    if preferir_mensal:
        mensais = [e for e in candidatos if e["mensal"]]
        if mensais:
            candidatos = mensais

    # Ordena por 'du' mais próximo do meio da faixa (30-45 dias)
    candidatos.sort(key=lambda e: abs(e["du"] - 35))
    return candidatos[0]


def buscar_premio_real(ticker: str, strike_alvo: float, tipo: str,
                       dias_min: int = 15, dias_max: int = 60) -> dict | None:
    """
    Busca o prêmio real da opção mais próxima do strike_alvo, no melhor
    vencimento disponível.
    Retorna dict com premio, strike_real, vencimento, negocios ou None.
    """
    cadeia = buscar_cadeia_estruturada(ticker)
    if not cadeia:
        return None

    venc = buscar_melhor_vencimento(cadeia, dias_min, dias_max)
    if not venc:
        return None

    lado = venc.get("calls" if tipo.lower() == "call" else "puts", {})
    if not lado:
        return None

    # Acha o strike mais próximo do alvo
    melhor = None
    melhor_dist = float("inf")
    for strike, info in lado.items():
        dist = abs(strike - strike_alvo)
        if dist < melhor_dist:
            melhor_dist = dist
            melhor = info

    if melhor is None:
        return None

    premio = melhor.get("preco")
    if premio is None:
        # Tenta fallback: usa estimativa? Não — retorna None (fallback BS)
        return None

    return {
        "premio": premio,
        "strike_real": melhor["strike"],
        "vencimento": venc["dt"],
        "dias_uteis": venc["du"],
        "negocios": melhor.get("negocios"),
        "volume": melhor.get("volume"),
        "sufixo": melhor.get("sufixo"),
    }
