"""
Screener — varre uma lista de ativos, calcula o nível (0-10) de cada um e
retorna todos ranqueados do sinal mais forte para o mais fraco.
"""

import time
from b3_swing_analyzer import baixar_dados, calcular_indicadores, avaliar_ativo

# Lista base: principais ativos do Ibovespa com opções líquidas na B3.
# Prefira editar WATCHLIST em config.py — é mais fácil de achar.
WATCHLIST_PADRAO = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "ABEV3",
    "WEGE3", "RENT3", "SUZB3", "PRIO3", "RADL3", "EQTL3", "GGBR4",
    "LREN3", "RAIL3", "HAPV3", "CSNA3", "ELET3", "ITSA4",
]


def rodar_screener(watchlist=None, periodo="6mo", pausa=0.3) -> list:
    """
    Roda a avaliação (placar 0-10) para cada ativo da watchlist.
    `pausa` evita sobrecarregar a fonte de dados com requisições muito rápidas.
    Retorna lista de dicts ordenada do nível mais alto para o mais baixo.
    """
    watchlist = watchlist or WATCHLIST_PADRAO
    resultados = []

    for ticker in watchlist:
        try:
            df = baixar_dados(ticker, periodo=periodo)
            df = calcular_indicadores(df)
            avaliacao = avaliar_ativo(df)
            resultados.append({
                "ticker": ticker,
                "score": avaliacao["score"],
                "direcao": avaliacao["direcao"],
                "preco": avaliacao["preco_atual"],
                "motivos": avaliacao["motivos"],
                "df": df,  # mantém o dataframe para uso posterior (gráfico, stop/alvo)
            })
        except Exception as e:
            print(f"[aviso] Falha ao processar {ticker}: {e}")
        time.sleep(pausa)

    resultados.sort(key=lambda r: r["score"], reverse=True)
    return resultados


if __name__ == "__main__":
    resultados = rodar_screener()
    print("=== RANKING DE ATIVOS (0-10) ===")
    for r in resultados:
        emoji = "🟢" if r["direcao"] == "compra" else "🔴"
        print(f"{emoji} {r['ticker']}: {r['score']}/10 ({r['direcao']}) | R$ {r['preco']:.2f}")
