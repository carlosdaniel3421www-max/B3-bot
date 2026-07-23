"""
Calendário de resultados — checa se tem divulgação de resultado
trimestral (balanço) próxima, pra evitar sugerir entrada véspera de
evento que costuma causar volatilidade forte e imprevisível
(especialmente ruim pra quem está comprado em opção por causa do
"crush" de volatilidade implícita depois do resultado).

Fonte: yfinance (dados de calendário de earnings, quando disponíveis
para o ativo — cobertura pra B3 pode ser incompleta; por isso este
módulo é "best effort": se não achar dado, simplesmente não bloqueia).
"""

from datetime import date, datetime


def checar_resultado_proximo(ticker: str, dias_minimos: int = 5) -> dict:
    """
    Retorna dict com 'tem_resultado_proximo' (bool) e 'data_resultado'
    (ou None se não encontrado / não disponível).
    """
    try:
        import yfinance as yf

        ticker_yf = ticker.upper() if ticker.upper().endswith(".SA") else ticker.upper() + ".SA"
        acao = yf.Ticker(ticker_yf)
        datas = acao.get_earnings_dates(limit=4)

        if datas is None or datas.empty:
            return {"tem_resultado_proximo": False, "data_resultado": None, "info_disponivel": False}

        hoje = date.today()
        # Filtra só datas futuras
        datas_futuras = [d.date() for d in datas.index if d.date() >= hoje]
        if not datas_futuras:
            return {"tem_resultado_proximo": False, "data_resultado": None, "info_disponivel": True}

        proxima = min(datas_futuras)
        dias_ate_resultado = (proxima - hoje).days

        return {
            "tem_resultado_proximo": dias_ate_resultado <= dias_minimos,
            "data_resultado": proxima.isoformat(),
            "dias_ate_resultado": dias_ate_resultado,
            "info_disponivel": True,
        }
    except Exception:
        # Cobertura de earnings da Yahoo pra B3 é inconsistente — falha
        # silenciosa é o comportamento certo aqui (não bloqueia por falta de dado)
        return {"tem_resultado_proximo": False, "data_resultado": None, "info_disponivel": False}
