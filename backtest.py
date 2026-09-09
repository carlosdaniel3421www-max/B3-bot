"""
Backtest — simula como a estratégia (placar de confluência 0-10 + stop/alvo
por ATR) teria se saído no passado, pra você ver se faz sentido confiar
nela antes de operar dinheiro de verdade.

USO:
    python backtest.py PETR4 --periodo 2y --nivel-minimo 8

Como funciona a simulação:
- Percorre o histórico dia a dia
- Sempre que o placar do dia bate o nível mínimo E não há posição aberta,
  "entra" na abertura do pregão seguinte, com stop/alvo definidos no sinal
- Cancela a entrada se a abertura já estiver fora do intervalo stop/alvo
- Verifica saídas inclusive no pregão de entrada; gaps contra o stop saem
  na abertura, alvos são executados no limite (sem melhoria por gap)
- Se stop e alvo forem tocados na mesma barra, assume stop primeiro,
  exceto quando a abertura já tiver acionado a saída
- Sai quando o preço bate o stop, bate o alvo, ou depois de um número
  máximo de dias (holding period) — o que vier primeiro
- Não entra em nova operação enquanto uma já está aberta (sem pirâmide)
- Holding conta sessoes desde a entrada (entrada = 0); zero sai na entrada.
- Slippage opcional piora entrada e saida, inclusive a referencia do alvo.
  A condicao de entrada e os gatilhos continuam usando OHLC sem ajuste.
- Retorno bruto usa precos executados (ja com slippage); liquido desconta
  custos fixos por lado em bps do valor de entrada: 2 * custos_bps / 100 pp.
  retorno_pct e as estatisticas usam o liquido; padroes zero preservam o modelo.

IMPORTANTE — limitações honestas deste backtest:
- Custos/slippage sao hipoteses constantes, nao tarifas reais; sem imposto
  de renda, aluguel de acoes ou financiamento da venda.
- OHLC diário não revela a sequência intradiária nem garante liquidez;
  posições ainda abertas ao fim do histórico não entram nas estatísticas
- Não simula opções de verdade (prêmio, gregas, spread) — simula a AÇÃO
  e nao permite inferir nem mesmo o sinal do PnL de uma opcao
- Default 8 alinha apenas o corte ENTRAR, nao replica o relatorio: sem
  suavizacao, noticias, IA, regime IBOV, confirmacao horaria ou gestao de carteira.
- Soma de retornos e drawdown dessa soma sao pontos percentuais descritivos,
  nao retorno/drawdown de capital. Saidas na mesma data sao agrupadas; nao ha
  marcacao a mercado, alocacao, composicao nem restricao a trades simultaneos.
- Desempenho passado não garante desempenho futuro
- Poucos trades (comum em swing trade) tornam as estatísticas menos
  confiáveis estatisticamente — trate como indicativo, não prova
"""

import argparse
import math
from numbers import Real
import pandas as pd
from b3_swing_analyzer import baixar_dados, calcular_indicadores, avaliar_ativo, sugerir_stop_alvo


def _validar_limites(nivel_minimo, max_dias_holding, custos_bps_por_lado=0,
                     slippage_bps_por_lado=0):
    if isinstance(nivel_minimo, bool) or not isinstance(nivel_minimo, int) or not 0 <= nivel_minimo <= 10:
        raise ValueError("nivel_minimo deve ser inteiro de 0 a 10")
    if isinstance(max_dias_holding, bool) or not isinstance(max_dias_holding, int) or max_dias_holding < 0:
        raise ValueError("max_dias_holding deve ser inteiro >= 0 (entrada = sessao zero)")
    for nome, valor in (("custos_bps_por_lado", custos_bps_por_lado),
                        ("slippage_bps_por_lado", slippage_bps_por_lado)):
        if (isinstance(valor, bool) or not isinstance(valor, Real)
                or not 0 <= valor < 10000 or not math.isfinite(valor)):
            raise ValueError(f"{nome} deve ser numero finito >= 0 e < 10000 bps")


def _configuracao(periodo, nivel_minimo, max_dias_holding, custos_bps_por_lado,
                  slippage_bps_por_lado):
    return {
        "periodo": periodo,
        "nivel_minimo": nivel_minimo,
        "max_dias_holding": max_dias_holding,
        "custos_bps_por_lado": custos_bps_por_lado,
        "slippage_bps_por_lado": slippage_bps_por_lado,
        "modelo_custos": "2 * custos_bps_por_lado / 100 pp; base fixa no valor de entrada",
        "modelo_slippage": "Adverso na entrada e em toda saida; gatilhos OHLC sem ajuste",
        "retornos": "Bruto apos slippage, antes de custos; retorno_pct = retorno_liquido_pct",
    }


def rodar_backtest(ticker: str, periodo: str = "2y", nivel_minimo: int = 8,
                   max_dias_holding: int = 20, custos_bps_por_lado: float = 0,
                   slippage_bps_por_lado: float = 0) -> dict:
    """Simula trades de acao; custos e slippage em [0, 10000) bps por lado."""
    _validar_limites(nivel_minimo, max_dias_holding, custos_bps_por_lado, slippage_bps_por_lado)
    slippage = slippage_bps_por_lado / 10000
    custos_pct = 2 * (custos_bps_por_lado / 100)
    df = baixar_dados(ticker, periodo=periodo)
    df = calcular_indicadores(df)

    # precisa de histórico suficiente pra SMA200 e afins existirem
    inicio = 210
    if len(df) <= inicio + 1:
        raise ValueError("Histórico insuficiente para rodar o backtest (precisa de mais de ~210 dias úteis).")

    trades = []
    posicao_aberta = None

    for i in range(inicio, len(df) - 1):
        df_ate_aqui = df.iloc[: i + 1]

        if posicao_aberta is None:
            avaliacao = avaliar_ativo(df_ate_aqui)
            score = avaliacao["score"]
            if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 10:
                raise ValueError("Score do sinal deve ser inteiro de 0 a 10")
            if avaliacao["score"] >= nivel_minimo and avaliacao["direcao"] in ("compra", "venda"):
                stop_alvo = sugerir_stop_alvo(df_ate_aqui, avaliacao["direcao"])
                entrada_idx = i + 1  # entra no próximo pregão
                preco_entrada = df["open"].iloc[entrada_idx]
                if not all(isinstance(v, Real) and not isinstance(v, bool)
                           and math.isfinite(v) and v > 0
                           for v in (preco_entrada, stop_alvo["stop"], stop_alvo["alvo"])):
                    raise ValueError("Entrada, stop e alvo devem ser finitos e positivos")
                # Ordem condicionada a uma abertura dentro dos limites do sinal.
                if avaliacao["direcao"] == "compra":
                    entrada_valida = 0 < stop_alvo["stop"] < preco_entrada < stop_alvo["alvo"]
                else:
                    entrada_valida = 0 < stop_alvo["alvo"] < preco_entrada < stop_alvo["stop"]
                if not entrada_valida:
                    continue
                sentido = 1 if avaliacao["direcao"] == "compra" else -1
                preco_entrada *= 1 + sentido * slippage
                posicao_aberta = {
                    "direcao": avaliacao["direcao"],
                    "score_entrada": avaliacao["score"],
                    "data_entrada": df.index[entrada_idx],
                    "preco_entrada": preco_entrada,
                    "stop": stop_alvo["stop"],
                    "alvo": stop_alvo["alvo"],
                    "dias_no_trade": 0,
                    "idx_entrada": entrada_idx,
                }
        if posicao_aberta is not None:
            dia_atual = i + 1
            # Sessões decorridas desde a entrada (a sessão de entrada vale zero).
            posicao_aberta["dias_no_trade"] = dia_atual - posicao_aberta["idx_entrada"]

            preco_abertura = df["open"].iloc[dia_atual]
            preco_max = df["high"].iloc[dia_atual]
            preco_min = df["low"].iloc[dia_atual]
            preco_fechamento = df["close"].iloc[dia_atual]

            saiu = False
            motivo_saida = None
            preco_saida = None

            if posicao_aberta["direcao"] == "compra":
                if preco_abertura <= posicao_aberta["stop"]:
                    saiu, motivo_saida, preco_saida = True, "stop", preco_abertura
                elif preco_abertura >= posicao_aberta["alvo"]:
                    saiu, motivo_saida, preco_saida = True, "alvo", posicao_aberta["alvo"]
                elif preco_min <= posicao_aberta["stop"]:
                    saiu, motivo_saida, preco_saida = True, "stop", posicao_aberta["stop"]
                elif preco_max >= posicao_aberta["alvo"]:
                    saiu, motivo_saida, preco_saida = True, "alvo", posicao_aberta["alvo"]
            else:  # venda
                if preco_abertura >= posicao_aberta["stop"]:
                    saiu, motivo_saida, preco_saida = True, "stop", preco_abertura
                elif preco_abertura <= posicao_aberta["alvo"]:
                    saiu, motivo_saida, preco_saida = True, "alvo", posicao_aberta["alvo"]
                elif preco_max >= posicao_aberta["stop"]:
                    saiu, motivo_saida, preco_saida = True, "stop", posicao_aberta["stop"]
                elif preco_min <= posicao_aberta["alvo"]:
                    saiu, motivo_saida, preco_saida = True, "alvo", posicao_aberta["alvo"]

            if not saiu and posicao_aberta["dias_no_trade"] >= max_dias_holding:
                saiu, motivo_saida, preco_saida = True, "prazo_maximo", preco_fechamento

            if saiu:
                sentido = 1 if posicao_aberta["direcao"] == "compra" else -1
                preco_saida *= 1 - sentido * slippage
                if posicao_aberta["direcao"] == "compra":
                    retorno_bruto_pct = (preco_saida - posicao_aberta["preco_entrada"]) / posicao_aberta["preco_entrada"] * 100
                else:
                    retorno_bruto_pct = (posicao_aberta["preco_entrada"] - preco_saida) / posicao_aberta["preco_entrada"] * 100
                retorno_liquido_pct = retorno_bruto_pct - custos_pct

                # Arredondar aqui apagaria custos/retornos pequenos antes das estatisticas.
                trades.append({
                    "data_entrada": posicao_aberta["data_entrada"],
                    "data_saida": df.index[dia_atual],
                    "direcao": posicao_aberta["direcao"],
                    "score_entrada": posicao_aberta["score_entrada"],
                    "preco_entrada": posicao_aberta["preco_entrada"],
                    "preco_saida": preco_saida,
                    "motivo_saida": motivo_saida,
                    "retorno_bruto_pct": retorno_bruto_pct,
                    "custos_pct": custos_pct,
                    "retorno_liquido_pct": retorno_liquido_pct,
                    "retorno_pct": retorno_liquido_pct,
                    "dias_no_trade": posicao_aberta["dias_no_trade"],
                })
                posicao_aberta = None

    return {
        **montar_estatisticas(ticker, trades),
        "configuracao": _configuracao(periodo, nivel_minimo, max_dias_holding,
                                      custos_bps_por_lado, slippage_bps_por_lado),
    }


def montar_estatisticas(ticker: str, trades: list) -> dict:
    """Distribuicao de trades; soma/drawdown em pp, nunca curva de capital."""
    if not trades:
        return {"ticker": ticker, "total_trades": 0, "mensagem": "Nenhum trade gerado nesse período com esse nível mínimo."}

    por_data = {}
    for trade in trades:
        retorno = trade["retorno_pct"]
        if isinstance(retorno, bool) or not isinstance(retorno, Real) or not math.isfinite(retorno):
            raise ValueError("Retorno de trade deve ser finito")
        data_saida = pd.Timestamp(trade["data_saida"])
        if pd.isna(data_saida):
            raise ValueError("Data de saida invalida")
        if data_saida.tzinfo is not None:
            data_saida = data_saida.tz_convert("America/Sao_Paulo")
        por_data.setdefault(data_saida.date(), []).append(retorno)
    trades = sorted(trades, key=lambda t: (pd.Timestamp(t["data_saida"]).isoformat(),
                                          str(t.get("ticker", "")), str(t.get("data_entrada", ""))))
    ganhos = [t for t in trades if t["retorno_pct"] > 0]
    perdas = [t for t in trades if t["retorno_pct"] <= 0]

    retorno_total_pct = math.fsum(t["retorno_pct"] for t in trades)
    retorno_medio_pct = retorno_total_pct / len(trades)
    taxa_acerto = len(ganhos) / len(trades) * 100

    media_ganho = sum(t["retorno_pct"] for t in ganhos) / len(ganhos) if ganhos else 0
    media_perda = sum(t["retorno_pct"] for t in perdas) / len(perdas) if perdas else 0

    soma_ganhos = math.fsum(t["retorno_pct"] for t in ganhos)
    soma_perdas_abs = abs(math.fsum(t["retorno_pct"] for t in perdas))
    profit_factor = (soma_ganhos / soma_perdas_abs) if soma_perdas_abs > 0 else None

    acumulado = 0
    pico = 0
    max_drawdown = 0
    for data_saida in sorted(por_data):
        acumulado += math.fsum(por_data[data_saida])
        pico = max(pico, acumulado)
        max_drawdown = min(max_drawdown, acumulado - pico)

    return {
        "ticker": ticker,
        "total_trades": len(trades),
        "taxa_acerto_pct": round(taxa_acerto, 1),
        "soma_retornos_pp": round(retorno_total_pct, 2),
        "retorno_medio_por_trade_pct": round(retorno_medio_pct, 2),
        "media_ganho_pct": round(media_ganho, 2),
        "media_perda_pct": round(media_perda, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else (
            "inf (sem perdas)" if soma_ganhos > 0 else "indefinido (sem ganhos/perdas)"),
        "drawdown_soma_pp": round(max_drawdown, 2),
        "metrica": "Soma de retornos por data de saida; nao representa capital/carteira",
        "trades": trades,
    }


def _imprimir_configuracao(resultado):
    print("Acao, custos/slippage hipoteticos; nao replica filtros do relatorio nem carteira.")
    if "configuracao" in resultado:
        config = resultado["configuracao"]
        print(f"Custos por lado: {config['custos_bps_por_lado']} bps | "
              f"Slippage por lado: {config['slippage_bps_por_lado']} bps")
        print(f"Custos: {config['modelo_custos']}")
        print(f"Retornos: {config['retornos']}")


def imprimir_resultado(resultado: dict):
    print("=" * 60)
    print(f"BACKTEST — {resultado['ticker']}")
    print("=" * 60)
    _imprimir_configuracao(resultado)
    if resultado["total_trades"] == 0:
        print(resultado["mensagem"])
        return

    print(f"Total de trades:        {resultado['total_trades']}")
    print(f"Taxa de acerto:         {resultado['taxa_acerto_pct']}%")
    print(f"Soma retornos/trade:    {resultado['soma_retornos_pp']} pp (nao e retorno de capital)")
    print(f"Retorno médio/trade:    {resultado['retorno_medio_por_trade_pct']}%")
    print(f"Ganho médio (trades+):  {resultado['media_ganho_pct']}%")
    print(f"Perda média (trades-):  {resultado['media_perda_pct']}%")
    print(f"Profit factor:          {resultado['profit_factor']}")
    print(f"Drawdown da soma:       {resultado['drawdown_soma_pp']} pp (por data de saida, sem MTM)")
    print("-" * 60)
    print("Últimos trades:")
    for t in resultado["trades"][-10:]:
        emoji = "✅" if t["retorno_pct"] > 0 else "❌"
        print(f"  {emoji} {t['data_entrada'].date()} -> {t['data_saida'].date()} | "
              f"{t['direcao']:6s} | score {t['score_entrada']}/10 | "
              f"{t['retorno_pct']:+.2f}% | saída: {t['motivo_saida']}")
    print("=" * 60)
    print("\nAVISO: backtest simplificado (sem impostos/aluguel, sem simular opcao real).")
    print("Use como indicativo, não como garantia de resultado futuro.\n")


def rodar_backtest_multi(tickers: list, periodo: str = "2y", nivel_minimo: int = 8,
                         max_dias_holding: int = 20, custos_bps_por_lado: float = 0,
                         slippage_bps_por_lado: float = 0) -> dict:
    """
    Agrega trades independentes, nao simula carteira. Saidas simultaneas
    entram juntas na soma descritiva, sem ordem artificial entre tickers.
    """
    _validar_limites(nivel_minimo, max_dias_holding, custos_bps_por_lado, slippage_bps_por_lado)
    configuracao = _configuracao(periodo, nivel_minimo, max_dias_holding,
                                custos_bps_por_lado, slippage_bps_por_lado)
    if not isinstance(tickers, (list, tuple)) or not tickers or any(
        not isinstance(t, str) or not t.strip().upper().removesuffix(".SA") for t in tickers
    ):
        raise ValueError("Informe uma lista nao vazia de tickers")
    tickers = list(dict.fromkeys(t.strip().upper().removesuffix(".SA") for t in tickers))
    resultados = []
    falhas = []
    for ticker in tickers:
        try:
            resultados.append(rodar_backtest(ticker, periodo=periodo,
                                             nivel_minimo=nivel_minimo,
                                             max_dias_holding=max_dias_holding,
                                             custos_bps_por_lado=custos_bps_por_lado,
                                             slippage_bps_por_lado=slippage_bps_por_lado))
        except Exception as e:
            falhas.append(f"{ticker}: {e}")

    todos_trades = []
    for r in resultados:
        todos_trades.extend(dict(t, ticker=r["ticker"]) for t in r.get("trades", []))

    if not todos_trades:
        return {
            "tickers": tickers,
            "total_trades": 0,
            "mensagem": "Nenhum trade gerado nos ativos testados.",
            "por_ativo": resultados,
            "falhas": falhas,
            "configuracao": configuracao,
        }

    return {
        **montar_estatisticas("MULTI", todos_trades),
        "tickers": tickers,
        "por_ativo": resultados,
        "falhas": falhas,
        "configuracao": configuracao,
    }


def imprimir_resultado_multi(resultado: dict):
    print("=" * 60)
    print(f"BACKTEST MULTI-ATIVO — {', '.join(resultado['tickers'])}")
    print("=" * 60)
    _imprimir_configuracao(resultado)
    if resultado["total_trades"] == 0:
        print(resultado["mensagem"])
        for r in resultado["por_ativo"]:
            if r["total_trades"] == 0:
                print(f"  - {r['ticker']}: sem trades")
        if resultado["falhas"]:
            print("\nFalhas:")
            for f in resultado["falhas"]:
                print(f"  - {f}")
        return

    print(f"Total de trades (todos):{resultado['total_trades']}")
    print(f"Taxa de acerto:         {resultado['taxa_acerto_pct']}%")
    print(f"Soma retornos/trade:    {resultado['soma_retornos_pp']} pp (nao e retorno de capital)")
    print(f"Retorno médio/trade:    {resultado['retorno_medio_por_trade_pct']}%")
    print(f"Ganho médio (trades+):  {resultado['media_ganho_pct']}%")
    print(f"Perda média (trades-):  {resultado['media_perda_pct']}%")
    print(f"Profit factor:          {resultado['profit_factor']}")
    print(f"Drawdown da soma:       {resultado['drawdown_soma_pp']} pp (por data de saida, sem MTM)")
    print("-" * 60)
    print("Por ativo:")
    for r in resultado["por_ativo"]:
        if r["total_trades"] == 0:
            print(f"  {r['ticker']}: sem trades")
        else:
            print(f"  {r['ticker']}: {r['total_trades']} trades | "
                  f"acerto {r['taxa_acerto_pct']}% | soma {r['soma_retornos_pp']:+.2f} pp | "
                  f"PF {r['profit_factor']}")
    if resultado["falhas"]:
        print("\nFalhas:")
        for f in resultado["falhas"]:
            print(f"  - {f}")
    print("=" * 60)
    print("\nAVISO: backtest simplificado (sem impostos/aluguel, sem simular opcao real).")
    print("Trades independentes, sem alocacao de capital ou curva de carteira.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest da estratégia de confluência (1 ativo ou vários)")
    parser.add_argument("tickers", nargs="+", help="Código(s) do ativo, ex: PETR4 (ou PETR4 VALE3 ITUB4)")
    parser.add_argument("--periodo", default="2y", help="Período de histórico (ex: 1y, 2y, 5y)")
    parser.add_argument("--nivel-minimo", type=int, choices=range(11), default=8, help="Corte 0-10 (padrao 8); nao replica os filtros do relatorio")
    parser.add_argument("--max-dias", type=int, default=20, help="Sessoes desde entrada (entrada=0; zero sai no mesmo dia)")
    parser.add_argument("--custos-bps-por-lado", type=float, default=0,
                        help="Custos por lado em bps da entrada (0 <= valor < 10000; padrao 0)")
    parser.add_argument("--slippage-bps-por-lado", type=float, default=0,
                        help="Slippage adverso por lado em bps (0 <= valor < 10000; padrao 0)")
    args = parser.parse_args()
    try:
        _validar_limites(args.nivel_minimo, args.max_dias,
                        args.custos_bps_por_lado, args.slippage_bps_por_lado)
    except ValueError as exc:
        parser.error(str(exc))

    if len(args.tickers) == 1:
        resultado = rodar_backtest(args.tickers[0], periodo=args.periodo,
                                   nivel_minimo=args.nivel_minimo, max_dias_holding=args.max_dias,
                                   custos_bps_por_lado=args.custos_bps_por_lado,
                                   slippage_bps_por_lado=args.slippage_bps_por_lado)
        imprimir_resultado(resultado)
    else:
        resultado = rodar_backtest_multi(args.tickers, periodo=args.periodo,
                                         nivel_minimo=args.nivel_minimo, max_dias_holding=args.max_dias,
                                         custos_bps_por_lado=args.custos_bps_por_lado,
                                         slippage_bps_por_lado=args.slippage_bps_por_lado)
        imprimir_resultado_multi(resultado)
