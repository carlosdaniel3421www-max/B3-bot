"""
Screener — varre uma lista de ativos, calcula o nível (0-10) de cada um e
retorna todos ranqueados do sinal mais forte para o mais fraco.
"""

import time
from b3_swing_analyzer import (
    baixar_dados, calcular_indicadores, avaliar_ativo,
    calcular_indicadores_curto_prazo, avaliar_ativo_curto_prazo,
    projetar_volume_dia_atual, avaliar_timeframe_horario,
)

# Lista base: principais ativos do Ibovespa com opções líquidas na B3.
# Prefira editar WATCHLIST em config.py — é mais fácil de achar.
WATCHLIST_PADRAO = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "ABEV3",
    "WEGE3", "RENT3", "SUZB3", "PRIO3", "RADL3", "EQTL3", "GGBR4",
    "LREN3", "RAIL3", "HAPV3", "CSNA3", "ELET3", "ITSA4",
]


def rodar_screener(watchlist=None, periodo="6mo", pausa=0.3,
                    usar_curto_prazo: bool = False, projetar_volume: bool = False,
                    confirmar_intradiario: bool = False) -> list:
    """
    Roda a avaliação (placar 0-10) para cada ativo da watchlist.
    `pausa` evita sobrecarregar a fonte de dados com requisições muito rápidas.
    usar_curto_prazo: usa o motor de indicadores mais rápidos (SMA5/10/20,
        RSI7, MACD 5/13/5, Estocástico7) em vez do padrão — pensado pra
        relatórios de prazo mais curto (ex: relatório da tarde).
    projetar_volume: projeta o volume do candle de hoje pro dia inteiro,
        caso o pregão ainda esteja em andamento (evita falso negativo na
        comparação de volume por causa de candle parcial).
    confirmar_intradiario: busca o gráfico de 1 HORA e usa ele pra confirmar
        (+1 ponto, até o máximo de 10) ou contestar (-2 pontos) o sinal do
        gráfico diário. Só faz sentido junto com usar_curto_prazo=True.
    Retorna lista de dicts ordenada do nível mais alto para o mais baixo.
    """
    watchlist = watchlist or WATCHLIST_PADRAO
    resultados = []

    for ticker in watchlist:
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

            resultados.append({
                "ticker": ticker,
                "score": score,
                "direcao": direcao,
                "preco": avaliacao["preco_atual"],
                "motivos": motivos,
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
        emoji = "🟢" if r["direcao"] == "compra" else ("🔴" if r["direcao"] == "venda" else "⚪")
        print(f"{emoji} {r['ticker']}: {r['score']}/10 ({r['direcao']}) | R$ {r['preco']:.2f}")
