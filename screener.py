"""
Screener — varre uma lista de ativos, calcula o nível (0-10) de cada um e
retorna todos ranqueados do sinal mais forte para o mais fraco.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from b3_swing_analyzer import (
    baixar_dados, calcular_indicadores, avaliar_ativo,
    calcular_indicadores_curto_prazo, avaliar_ativo_curto_prazo,
    projetar_volume_dia_atual, avaliar_timeframe_horario,
    avaliar_regime_ibov,
)

# Lista base: principais ativos do Ibovespa com opções líquidas na B3.
# Prefira editar WATCHLIST em config.py — é mais fácil de achar.
WATCHLIST_PADRAO = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "ABEV3",
    "WEGE3", "RENT3", "SUZB3", "PRIO3", "RADL3", "EQTL3", "GGBR4",
    "LREN3", "RAIL3", "HAPV3", "CSNA3", "ELET3", "ITSA4",
]


def _processar_ativo(ticker, periodo, usar_curto_prazo, projetar_volume,
                     confirmar_intradiario, regime_ibov=None) -> dict | None:
    """Processa um ativo individualmente (para paralelismo)."""
    try:
        df = baixar_dados(ticker, periodo=periodo)
        df = calcular_indicadores(df)  # sempre calcula o padrão (usado no gráfico)

        if projetar_volume:
            df = projetar_volume_dia_atual(df)

        if usar_curto_prazo:
            df = calcular_indicadores_curto_prazo(df)
            avaliacao = avaliar_ativo_curto_prazo(df)
        else:
            avaliacao = avaliar_ativo(df)

        motivos = list(avaliacao["motivos"])
        score = avaliacao["score"]
        direcao = avaliacao["direcao"]

        if confirmar_intradiario and direcao != "neutro":
            horario = avaliar_timeframe_horario(ticker)
            if horario["direcao"] == direcao:
                score = min(10, score + 1)
                motivos.append(f"✅ Gráfico de 1h confirma a mesma direção (RSI horário {horario['rsi_h']:.0f})")
            elif horario["direcao"] not in ("neutro", "indisponivel"):
                score = max(0, score - 2)
                motivos.append(
                    f"⚠️ Gráfico de 1h está na direção OPOSTA (RSI horário {horario['rsi_h']:.0f}) "
                    f"— cautela redobrada, sinal pode estar perdendo força intradiária"
                )

        # Filtro de regime de mercado (Ibovespa): limita o score pela direção.
        # Ex: mercado LATERAL limita compra E venda a 7/10 (nunca ENTRAR).
        if regime_ibov and direcao != "neutro":
            tetos = regime_ibov.get("tetos") or {}
            teto = tetos.get(direcao)
            if teto is not None and score > teto:
                score = teto
                aviso = regime_ibov.get("texto_aviso", "")
                if aviso:
                    motivos.append(f"⚠️ Ibovespa: {aviso}")

        return {
            "ticker": ticker,
            "score": score,
            "direcao": direcao,
            "preco": avaliacao["preco_atual"],
            "motivos": motivos,
            "df": df,  # mantém o dataframe para uso posterior (gráfico, stop/alvo)
        }
    except Exception as e:
        logging.warning("Falha ao processar %s: %s", ticker, e)
        return None


def rodar_screener(watchlist=None, periodo="2y", pausa=0.3,
                    usar_curto_prazo: bool = False, projetar_volume: bool = False,
                    confirmar_intradiario: bool = False, paralelo: bool = True,
                    regime_ibov: dict = None) -> list:
    """
    Roda a avaliação (placar 0-10) para cada ativo da watchlist.
    regime_ibov: dict com tetos de score por direção (output de avaliar_regime_ibov).
                 Se None, calcula automaticamente.
    Retorna lista de dicts ordenada do nível mais alto para o mais baixo.
    """
    if regime_ibov is None:
        regime_ibov = avaliar_regime_ibov()
    watchlist = watchlist or WATCHLIST_PADRAO
    resultados = []

    if paralelo and len(watchlist) > 2:
        with ThreadPoolExecutor(max_workers=min(6, len(watchlist))) as executor:
            futuros = {
                executor.submit(
                    _processar_ativo, t, periodo, usar_curto_prazo,
                    projetar_volume, confirmar_intradiario, regime_ibov,
                ): t
                for t in watchlist
            }
            for futuro in as_completed(futuros):
                r = futuro.result()
                if r:
                    resultados.append(r)
    else:
        for ticker in watchlist:
            r = _processar_ativo(
                ticker, periodo, usar_curto_prazo, projetar_volume,
                confirmar_intradiario, regime_ibov,
            )
            if r:
                resultados.append(r)
            time.sleep(pausa)

    resultados.sort(key=lambda r: r["score"], reverse=True)
    return resultados


if __name__ == "__main__":
    resultados = rodar_screener()
    print("=== RANKING DE ATIVOS (0-10) ===")
    for r in resultados:
        emoji = "🟢" if r["direcao"] == "compra" else ("🔴" if r["direcao"] == "venda" else "⚪")
        print(f"{emoji} {r['ticker']}: {r['score']}/10 ({r['direcao']}) | R$ {r['preco']:.2f}")
