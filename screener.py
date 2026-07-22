"""
Screener — varre uma lista de ativos, calcula o placar de confluência de
cada um e retorna os melhores setups de compra e de venda.
"""

import time
from b3_swing_analyzer import baixar_dados, calcular_indicadores, gerar_placar

# Lista base: principais ativos do Ibovespa com opções líquidas na B3.
# Edite livremente para focar na sua carteira/watchlist.
WATCHLIST_PADRAO = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "ABEV3",
    "WEGE3", "RENT3", "SUZB3", "PRIO3", "RADL3", "EQTL3", "GGBR4",
    "LREN3", "RAIL3", "HAPV3", "CSNA3", "ELET3", "ITSA4",
]


def rodar_screener(watchlist=None, periodo="6mo", pausa=0.3) -> list:
    """
    Roda o placar de confluência para cada ativo da watchlist.
    `pausa` evita sobrecarregar a fonte de dados com requisições muito rápidas.
    Retorna lista de dicts ordenada do sinal mais forte de compra para o mais forte de venda.
    """
    watchlist = watchlist or WATCHLIST_PADRAO
    resultados = []

    for ticker in watchlist:
        try:
            df = baixar_dados(ticker, periodo=periodo)
            df = calcular_indicadores(df)
            placar = gerar_placar(df)
            resultados.append({
                "ticker": ticker,
                "pontos": placar["pontos"],
                "classificacao": placar["classificacao"],
                "preco": placar["preco_atual"],
                "motivos": placar["motivos"],
                "df": df,  # mantém o dataframe para uso posterior (gráfico, stop/alvo)
            })
        except Exception as e:
            print(f"[aviso] Falha ao processar {ticker}: {e}")
        time.sleep(pausa)

    resultados.sort(key=lambda r: r["pontos"], reverse=True)
    return resultados


def melhores_setups(resultados: list, top_n: int = 3) -> dict:
    """Separa os top N sinais de compra e de venda mais fortes."""
    compras = [r for r in resultados if r["pontos"] >= 2][:top_n]
    vendas = sorted([r for r in resultados if r["pontos"] <= -2], key=lambda r: r["pontos"])[:top_n]
    return {"compras": compras, "vendas": vendas}


if __name__ == "__main__":
    resultados = rodar_screener()
    melhores = melhores_setups(resultados)

    print("=== MELHORES SETUPS DE COMPRA ===")
    for r in melhores["compras"]:
        print(f"{r['ticker']}: {r['pontos']:+d} pontos | R$ {r['preco']:.2f} | {r['classificacao']}")

    print("\n=== MELHORES SETUPS DE VENDA ===")
    for r in melhores["vendas"]:
        print(f"{r['ticker']}: {r['pontos']:+d} pontos | R$ {r['preco']:.2f} | {r['classificacao']}")
