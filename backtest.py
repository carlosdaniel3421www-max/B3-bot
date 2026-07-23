"""
Backtest — simula como a estratégia (placar de confluência 0-10 + stop/alvo
por ATR) teria se saído no passado, pra você ver se faz sentido confiar
nela antes de operar dinheiro de verdade.

USO:
    python backtest.py PETR4 --anos 2 --nivel-minimo 6

Como funciona a simulação:
- Percorre o histórico dia a dia
- Sempre que o placar do dia bate o nível mínimo E não há posição aberta,
  "entra" no fechamento do dia seguinte
- Sai quando o preço bate o stop, bate o alvo, ou depois de um número
  máximo de dias (holding period) — o que vier primeiro
- Não entra em nova operação enquanto uma já está aberta (sem pirâmide)

IMPORTANTE — limitações honestas deste backtest:
- Não considera custos de corretagem, emolumentos, imposto de renda
- Não simula opções de verdade (prêmio, gregas, spread) — simula a AÇÃO
  como proxy, assumindo que a opção capturaria a mesma direção
- Desempenho passado não garante desempenho futuro
- Poucos trades (comum em swing trade) tornam as estatísticas menos
  confiáveis estatisticamente — trate como indicativo, não prova
"""

import argparse
from b3_swing_analyzer import baixar_dados, calcular_indicadores, avaliar_ativo, sugerir_stop_alvo


def rodar_backtest(ticker: str, periodo: str = "2y", nivel_minimo: int = 6, max_dias_holding: int = 20) -> dict:
    df = baixar_dados(ticker, periodo=periodo)
    df = calcular_indicadores(df)

    # precisa de histórico suficiente pra SMA200 e afins existirem
    inicio = 210
    if len(df) <= inicio:
        raise ValueError("Histórico insuficiente para rodar o backtest (precisa de mais de ~210 dias úteis).")

    trades = []
    posicao_aberta = None

    for i in range(inicio, len(df) - 1):
        df_ate_aqui = df.iloc[: i + 1]

        if posicao_aberta is None:
            avaliacao = avaliar_ativo(df_ate_aqui)
            if avaliacao["score"] >= nivel_minimo:
                stop_alvo = sugerir_stop_alvo(df_ate_aqui, avaliacao["direcao"])
                entrada_idx = i + 1  # entra no próximo pregão
                posicao_aberta = {
                    "direcao": avaliacao["direcao"],
                    "score_entrada": avaliacao["score"],
                    "data_entrada": df.index[entrada_idx],
                    "preco_entrada": df["open"].iloc[entrada_idx],
                    "stop": stop_alvo["stop"],
                    "alvo": stop_alvo["alvo"],
                    "dias_no_trade": 0,
                    "idx_entrada": entrada_idx,
                }
        else:
            dia_atual = i + 1
            if dia_atual >= len(df):
                continue
            posicao_aberta["dias_no_trade"] = dia_atual - posicao_aberta["idx_entrada"]

            preco_max = df["high"].iloc[dia_atual]
            preco_min = df["low"].iloc[dia_atual]
            preco_fechamento = df["close"].iloc[dia_atual]

            saiu = False
            motivo_saida = None
            preco_saida = None

            if posicao_aberta["direcao"] == "compra":
                if preco_min <= posicao_aberta["stop"]:
                    saiu, motivo_saida, preco_saida = True, "stop", posicao_aberta["stop"]
                elif preco_max >= posicao_aberta["alvo"]:
                    saiu, motivo_saida, preco_saida = True, "alvo", posicao_aberta["alvo"]
            else:  # venda
                if preco_max >= posicao_aberta["stop"]:
                    saiu, motivo_saida, preco_saida = True, "stop", posicao_aberta["stop"]
                elif preco_min <= posicao_aberta["alvo"]:
                    saiu, motivo_saida, preco_saida = True, "alvo", posicao_aberta["alvo"]

            if not saiu and posicao_aberta["dias_no_trade"] >= max_dias_holding:
                saiu, motivo_saida, preco_saida = True, "prazo_maximo", preco_fechamento

            if saiu:
                if posicao_aberta["direcao"] == "compra":
                    retorno_pct = (preco_saida - posicao_aberta["preco_entrada"]) / posicao_aberta["preco_entrada"] * 100
                else:
                    retorno_pct = (posicao_aberta["preco_entrada"] - preco_saida) / posicao_aberta["preco_entrada"] * 100

                trades.append({
                    "data_entrada": posicao_aberta["data_entrada"],
                    "data_saida": df.index[dia_atual],
                    "direcao": posicao_aberta["direcao"],
                    "score_entrada": posicao_aberta["score_entrada"],
                    "preco_entrada": round(posicao_aberta["preco_entrada"], 2),
                    "preco_saida": round(preco_saida, 2),
                    "motivo_saida": motivo_saida,
                    "retorno_pct": round(retorno_pct, 2),
                    "dias_no_trade": posicao_aberta["dias_no_trade"],
                })
                posicao_aberta = None

    return montar_estatisticas(ticker, trades)


def montar_estatisticas(ticker: str, trades: list) -> dict:
    if not trades:
        return {"ticker": ticker, "total_trades": 0, "mensagem": "Nenhum trade gerado nesse período com esse nível mínimo."}

    ganhos = [t for t in trades if t["retorno_pct"] > 0]
    perdas = [t for t in trades if t["retorno_pct"] <= 0]

    retorno_total_pct = sum(t["retorno_pct"] for t in trades)
    retorno_medio_pct = retorno_total_pct / len(trades)
    taxa_acerto = len(ganhos) / len(trades) * 100

    media_ganho = sum(t["retorno_pct"] for t in ganhos) / len(ganhos) if ganhos else 0
    media_perda = sum(t["retorno_pct"] for t in perdas) / len(perdas) if perdas else 0

    soma_ganhos = sum(t["retorno_pct"] for t in ganhos)
    soma_perdas_abs = abs(sum(t["retorno_pct"] for t in perdas))
    profit_factor = (soma_ganhos / soma_perdas_abs) if soma_perdas_abs > 0 else float("inf")

    acumulado = 0
    pico = 0
    max_drawdown = 0
    for t in trades:
        acumulado += t["retorno_pct"]
        pico = max(pico, acumulado)
        max_drawdown = min(max_drawdown, acumulado - pico)

    return {
        "ticker": ticker,
        "total_trades": len(trades),
        "taxa_acerto_pct": round(taxa_acerto, 1),
        "retorno_total_pct": round(retorno_total_pct, 2),
        "retorno_medio_por_trade_pct": round(retorno_medio_pct, 2),
        "media_ganho_pct": round(media_ganho, 2),
        "media_perda_pct": round(media_perda, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf (sem perdas)",
        "max_drawdown_pct": round(max_drawdown, 2),
        "trades": trades,
    }


def imprimir_resultado(resultado: dict):
    print("=" * 60)
    print(f"BACKTEST — {resultado['ticker']}")
    print("=" * 60)
    if resultado["total_trades"] == 0:
        print(resultado["mensagem"])
        return

    print(f"Total de trades:        {resultado['total_trades']}")
    print(f"Taxa de acerto:         {resultado['taxa_acerto_pct']}%")
    print(f"Retorno total (soma):   {resultado['retorno_total_pct']}%")
    print(f"Retorno médio/trade:    {resultado['retorno_medio_por_trade_pct']}%")
    print(f"Ganho médio (trades+):  {resultado['media_ganho_pct']}%")
    print(f"Perda média (trades-):  {resultado['media_perda_pct']}%")
    print(f"Profit factor:          {resultado['profit_factor']}")
    print(f"Máximo drawdown:        {resultado['max_drawdown_pct']}%")
    print("-" * 60)
    print("Últimos trades:")
    for t in resultado["trades"][-10:]:
        emoji = "✅" if t["retorno_pct"] > 0 else "❌"
        print(f"  {emoji} {t['data_entrada'].date()} -> {t['data_saida'].date()} | "
              f"{t['direcao']:6s} | score {t['score_entrada']}/10 | "
              f"{t['retorno_pct']:+.2f}% | saída: {t['motivo_saida']}")
    print("=" * 60)
    print("\nAVISO: backtest simplificado (sem custos, sem simular opção real).")
    print("Use como indicativo, não como garantia de resultado futuro.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest da estratégia de confluência em um ativo")
    parser.add_argument("ticker", help="Código do ativo, ex: PETR4")
    parser.add_argument("--periodo", default="2y", help="Período de histórico (ex: 1y, 2y, 5y)")
    parser.add_argument("--nivel-minimo", type=int, default=6, help="Nível mínimo (0-10) pra considerar entrada")
    parser.add_argument("--max-dias", type=int, default=20, help="Máximo de dias segurando o trade")
    args = parser.parse_args()

    resultado = rodar_backtest(args.ticker, periodo=args.periodo, nivel_minimo=args.nivel_minimo, max_dias_holding=args.max_dias)
    imprimir_resultado(resultado)
