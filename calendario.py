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

from datetime import datetime
import logging
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)


def checar_resultado_proximo(ticker: str, dias_minimos: int = 5) -> dict:
    """
    Retorna dict com 'tem_resultado_proximo' (bool) e 'data_resultado'
    (ou None se não encontrado / não disponível).
    """
    if type(dias_minimos) is not int or dias_minimos < 0:
        raise ValueError("dias_minimos deve ser inteiro não negativo")
    try:
        import yfinance as yf
        import pandas as pd

        ticker_yf = ticker.strip().upper()
        if not ticker_yf:
            raise ValueError("ticker vazio")
        if not ticker_yf.endswith(".SA"):
            ticker_yf += ".SA"
        acao = yf.Ticker(ticker_yf)
        datas = acao.get_earnings_dates(limit=4)

        if datas is None or datas.empty:
            return {"tem_resultado_proximo": False, "data_resultado": None, "info_disponivel": False}

        fuso = ZoneInfo("America/Sao_Paulo")
        hoje = datetime.now(fuso).date()
        datas_futuras = []
        for valor in datas.index:
            try:
                if isinstance(valor, (int, float)):
                    continue
                data = pd.Timestamp(valor)
                if pd.isna(data):
                    continue
                if data.tzinfo is not None:
                    data = data.tz_convert(fuso)
                if data.date() >= hoje:
                    datas_futuras.append(data.date())
            except (TypeError, ValueError, OverflowError):
                continue
        if not datas_futuras:
            return {"tem_resultado_proximo": False, "data_resultado": None, "info_disponivel": False}

        proxima = min(datas_futuras)
        dias_ate_resultado = (proxima - hoje).days

        return {
            "tem_resultado_proximo": dias_ate_resultado <= dias_minimos,
            "data_resultado": proxima.isoformat(),
            "dias_ate_resultado": dias_ate_resultado,
            "info_disponivel": True,
        }
    except Exception as e:
        # Cobertura de earnings da Yahoo pra B3 é inconsistente — falha
        # Mantém best effort, sem confundir indisponibilidade com ausência de evento.
        logger.warning("Calendário indisponível para %s: %s", ticker, e)
        return {"tem_resultado_proximo": False, "data_resultado": None, "info_disponivel": False}
