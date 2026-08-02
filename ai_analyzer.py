"""Camada complementar de interpretação de cenário com Google Gemini."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)


class AIAnalyzer:
    """Interpreta um sinal técnico já calculado, sem alterar o motor do robô."""

    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: str, model: Optional[str] = None,
                 timeout_seconds: int = 30, max_retries: int = 2) -> None:
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._resolved_model: Optional[str] = None

    def analyze_asset(
        self,
        ticker: str,
        current_price: float,
        ema21: float,
        ema200: float,
        rsi: float,
        macd: float,
        volume: float,
        atr: float,
        support: float,
        resistance: float,
        score: int | float,
        direction: str,
        reasons: Sequence[str],
        news: Optional[Sequence[Mapping[str, Any]]] = None,
        chart_path: Optional[str | Path] = None,
    ) -> Optional[dict[str, Any]]:
        """Consulta o Gemini e devolve somente uma análise validada, ou ``None``.

        Falhas de rede, autenticação, biblioteca ausente ou respostas inválidas nunca
        propagam exceções para o robô.
        """
        if not self.api_key:
            logger.debug("Gemini não configurado; análise complementar ignorada.")
            return None

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            logger.warning("Pacote google-genai não instalado; IA complementar indisponível.")
            return None

        try:
            http_options = types.HttpOptions(timeout=self.timeout_seconds * 1000)
            client = genai.Client(api_key=self.api_key, http_options=http_options)
            model = self._get_model(client)
            contents: list[Any] = [self._build_prompt(
                ticker, current_price, ema21, ema200, rsi, macd, volume, atr,
                support, resistance, score, direction, reasons, news,
            )]
            if chart_path:
                image = Path(chart_path)
                if image.is_file():
                    contents.append(types.Part.from_bytes(
                        data=image.read_bytes(), mime_type="image/png"
                    ))
                else:
                    logger.warning("Gráfico de %s não encontrado: %s", ticker, image)

            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            temperature=0.2,
                            max_output_tokens=700,
                            response_mime_type="application/json",
                        ),
                    )
                    return self._validate_response(json.loads(response.text or "{}"), direction)
                except Exception as exc:  # SDK encapsula HTTP e timeouts em tipos próprios.
                    if attempt == self.max_retries:
                        logger.warning("Gemini indisponível para %s: %s", ticker, exc)
                        return None
                    logger.info("Tentativa %s/%s do Gemini falhou para %s.", attempt, self.max_retries, ticker)
                    time.sleep(attempt)
        except Exception as exc:
            logger.warning("Não foi possível preparar a análise Gemini de %s: %s", ticker, exc)
        return None

    def _get_model(self, client: Any) -> str:
        """Usa o Flash estável mais novo que a biblioteca/API disponibilizar."""
        if self._resolved_model:
            return self._resolved_model
        try:
            candidates = []
            for item in client.models.list():
                name = getattr(item, "name", "").removeprefix("models/")
                match = re.fullmatch(r"gemini-(\d+)(?:\.(\d+))?-flash", name)
                if match:
                    candidates.append(((int(match.group(1)), int(match.group(2) or 0)), name))
            if candidates:
                self._resolved_model = max(candidates)[1]
                return self._resolved_model
        except Exception as exc:
            logger.info("Não foi possível listar modelos Gemini; usando padrão: %s", exc)
        self._resolved_model = self.model
        return self._resolved_model

    @staticmethod
    def _build_prompt(
        ticker: str, current_price: float, ema21: float, ema200: float, rsi: float,
        macd: float, volume: float, atr: float, support: float, resistance: float,
        score: int | float, direction: str, reasons: Sequence[str],
        news: Optional[Sequence[Mapping[str, Any]]],
    ) -> str:
        operation = "CALL" if direction.lower() in {"compra", "call"} else "PUT"
        news_lines = [str(item.get("titulo", item)) for item in (news or [])]
        payload = {
            "ticker": ticker, "preco_atual": current_price, "ema21": ema21,
            "ema200": ema200, "rsi": rsi, "macd": macd, "volume": volume,
            "atr": atr, "suporte": support, "resistencia": resistance,
            "score_do_robo": score, "direcao_do_robo": operation,
            "motivos_do_robo": list(reasons), "noticias": news_lines,
        }
        return """Você é um trader profissional especializado em swing trade na B3.
Você NÃO deve calcular indicadores: eles já foram calculados pelo robô.
Interprete tendência, momentum, volume, suportes, resistências, contexto, gráfico e notícias.
A IA é apenas complementar e não altera o score do robô.
Responda SOMENTE em JSON no formato:
{"concorda":true,"operacao":"CALL","confianca":90,"entrada":"35.20","strike":"35.00","stop":"34.60","alvo":"36.50","risco":"Médio","explicacao":"texto curto","pontos_fortes":[],"pontos_fracos":[]}

Dados calculados:\n""" + json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _validate_response(data: Mapping[str, Any], direction: str) -> Optional[dict[str, Any]]:
        if not isinstance(data, Mapping):
            return None
        operation = str(data.get("operacao", "")).upper()
        default_operation = "CALL" if direction.lower() in {"compra", "call"} else "PUT"
        if operation not in {"CALL", "PUT"}:
            operation = default_operation
        try:
            confidence = max(0, min(100, int(float(data.get("confianca", 0)))))
        except (TypeError, ValueError):
            confidence = 0
        return {
            "concorda": bool(data.get("concorda", False)), "operacao": operation,
            "confianca": confidence, "entrada": str(data.get("entrada", "")),
            "strike": str(data.get("strike", "")), "stop": str(data.get("stop", "")),
            "alvo": str(data.get("alvo", "")), "risco": str(data.get("risco", "")),
            "explicacao": str(data.get("explicacao", "")),
            "pontos_fortes": [str(x) for x in data.get("pontos_fortes", []) if x],
            "pontos_fracos": [str(x) for x in data.get("pontos_fracos", []) if x],
        }
