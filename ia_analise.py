"""
Camada de análise complementar usando Google Gemini.

Responsabilidade:
- Receber a análise técnica já feita pelo robô.
- Enviar dados + gráfico para a IA.
- Retornar uma opinião complementar.

IMPORTANTE:
A IA NÃO calcula indicadores.
A IA NÃO altera score.
A IA NÃO substitui o motor técnico.

Ela apenas atua como um segundo analista.
"""

from __future__ import annotations

import json
import logging
import time

from pathlib import Path
from typing import Any, Optional, Sequence, Mapping


logger = logging.getLogger(__name__)


class AIAnalyzer:
    """
    Analista complementar usando Google Gemini.

    O robô principal continua sendo responsável por:
    - indicadores
    - score
    - direção
    - gestão de risco

    O Gemini interpreta:
    - gráfico
    - contexto
    - qualidade do setup
    """


    DEFAULT_MODEL = "gemini-2.5-flash"


    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout_seconds: int = 45,
        max_retries: int = 3,
    ):

        self.api_key = api_key

        self.model = model or self.DEFAULT_MODEL

        self.timeout_seconds = timeout_seconds

        self.max_retries = max_retries

        self._client = None



    def _get_client(self):
        """
        Cria cliente Gemini somente quando necessário.
        """

        if self._client:
            return self._client


        try:
            from google import genai

            self._client = genai.Client(
                api_key=self.api_key
            )

            return self._client


        except Exception as e:

            logger.error(
                "Erro criando cliente Gemini: %s",
                e
            )

            return None



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
        score: float,
        direction: str,
        reasons: Sequence[str],
        news: Optional[Sequence[Mapping[str, Any]]] = None,
        chart_path: Optional[str | Path] = None,
        extra_context: Optional[dict] = None,

    ) -> Optional[dict[str, Any]]:

        """
        Executa análise completa da IA.

        Retorna:

        {
            operacao,
            confianca,
            entrada,
            strike,
            stop,
            alvo,
            explicacao
        }

        Caso falhe:
        retorna None.

        O robô nunca deve parar por causa da IA.
        """


        if not self.api_key:

            logger.warning(
                "Gemini sem API KEY"
            )

            return None



        client = self._get_client()


        if not client:

            return None



        payload = self._build_payload(
            ticker=ticker,
            current_price=current_price,
            ema21=ema21,
            ema200=ema200,
            rsi=rsi,
            macd=macd,
            volume=volume,
            atr=atr,
            support=support,
            resistance=resistance,
            score=score,
            direction=direction,
            reasons=reasons,
            news=news,
            extra_context=extra_context
        )


        prompt = self._build_prompt(
            payload
        )


        for attempt in range(1, self.max_retries + 1):

            try:

                response = self._call_gemini(
                    client,
                    prompt,
                    chart_path
                )


                if response:

                    return self._validate_response(
                        response,
                        direction
                    )


            except Exception as e:

                logger.warning(
                    "Tentativa %s Gemini falhou: %s",
                    attempt,
                    e
                )


                time.sleep(attempt)



        return None
