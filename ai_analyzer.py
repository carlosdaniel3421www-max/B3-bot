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
        
    def _build_payload(
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
        extra_context: Optional[dict] = None,

    ) -> dict[str, Any]:
        """
        Monta todas as informações que serão entregues para a IA.
        """


        distancia_suporte = None
        distancia_resistencia = None

        try:

            distancia_suporte = (
                (current_price - support)
                /
                current_price
            ) * 100


            distancia_resistencia = (
                (resistance - current_price)
                /
                current_price
            ) * 100


        except Exception:

            pass



        contexto = {

            "ticker": ticker,

            "preco_atual": round(
                current_price,
                2
            ),


            "direcao_robo": direction,


            "score_robo": score,


            "indicadores": {

                "ema21": round(
                    ema21,
                    2
                ),

                "ema200": round(
                    ema200,
                    2
                ),

                "rsi": round(
                    rsi,
                    2
                ),

                "macd": round(
                    macd,
                    4
                ),

                "volume": volume,

                "atr": round(
                    atr,
                    2
                )

            },


            "niveis": {

                "suporte": round(
                    support,
                    2
                ),

                "resistencia": round(
                    resistance,
                    2
                ),

                "distancia_suporte_percentual":
                    round(
                        distancia_suporte,
                        2
                    )
                    if distancia_suporte
                    else None,


                "distancia_resistencia_percentual":
                    round(
                        distancia_resistencia,
                        2
                    )
                    if distancia_resistencia
                    else None

            },


            "motivos_detectados_pelo_robo":
                list(reasons),


            "noticias":

                [
                    str(
                        n.get(
                            "titulo",
                            n
                        )
                    )

                    for n in (news or [])
                ]

        }



        if extra_context:

            contexto["contexto_extra"] = extra_context



        return contexto





    def _build_prompt(
        self,
        payload: dict[str, Any]
    ) -> str:

        """
        Prompt principal da IA.

        Aqui ensinamos o comportamento do analista.
        """


        return f"""

Você é um analista profissional de Swing Trade da bolsa brasileira B3.

Você trabalha como um segundo analista de um robô quantitativo.

IMPORTANTE:

O robô já calculou os indicadores.

Você NÃO deve recalcular indicadores.

Você NÃO deve alterar o score.

Você NÃO deve ignorar os dados fornecidos.

Sua função é interpretar o cenário.

Você deve analisar:

- tendência principal;
- força do movimento;
- qualidade do volume;
- proximidade de suporte e resistência;
- estrutura do preço;
- possíveis padrões gráficos;
- risco da operação;
- melhor estratégia de entrada.



REGRAS DE ANÁLISE:


1) TENDÊNCIA

EMA21 acima da EMA200 normalmente indica tendência positiva.

EMA21 abaixo da EMA200 normalmente indica tendência negativa.

Não compre apenas porque RSI está baixo.

Não venda apenas porque RSI está alto.


2) RSI

RSI extremo em tendência forte pode representar força.

Não trate automaticamente RSI acima de 70 como venda.

Não trate automaticamente RSI abaixo de 30 como compra.


3) VOLUME

Rompimentos sem volume possuem maior chance de falha.

Movimento acompanhado por aumento de volume possui maior qualidade.


4) SUPORTE E RESISTÊNCIA

Entradas próximas de suporte possuem melhor relação risco/retorno.

Comprar exatamente em resistência possui maior risco.


5) GRÁFICO

Observe:

- rompimentos;
- pullbacks;
- bandeiras;
- triângulos;
- topo duplo;
- fundo duplo;
- candles de reversão;
- perda de força;
- divergências.



6) OPÇÕES

Ao sugerir operação:

Pense em:

- direção;
- distância do strike;
- tempo até vencimento;
- risco da operação.



RESPONDA SOMENTE JSON.

NÃO escreva texto antes ou depois.



Formato obrigatório:


{{
    "concorda_com_robo": true,

    "vale_operar": true,

    "operacao": "CALL",

    "setup": "Pullback EMA21",

    "confianca": 0,

    "entrada_agora": false,

    "esperar_confirmacao": true,

    "preco_ideal_entrada": "",

    "strike_sugerido": "",

    "stop": "",

    "alvo": "",

    "tempo_estimado": "",

    "risco": "",

    "explicacao": "",

    "pontos_fortes": [],

    "pontos_fracos": []

}}



Dados do robô:


{json.dumps(payload, indent=4, ensure_ascii=False)}

"""

    def _call_gemini(
        self,
        client: Any,
        prompt: str,
        chart_path: Optional[str | Path] = None,

    ) -> Optional[dict[str, Any]]:

        """
        Faz a chamada para o Gemini.

        Envia:
        - prompt textual
        - imagem do gráfico

        Retorna:
        JSON da IA.
        """


        try:

            from google.genai import types


            partes = []


            # ==========================
            # TEXTO
            # ==========================

            partes.append(
                types.Part.from_text(
                    text=prompt
                )
            )



            # ==========================
            # IMAGEM DO GRÁFICO
            # ==========================

            if chart_path:

                caminho = Path(
                    chart_path
                )


                if caminho.exists():

                    imagem = caminho.read_bytes()


                    partes.append(

                        types.Part.from_bytes(

                            data=imagem,

                            mime_type="image/png"

                        )

                    )


                else:

                    logger.warning(
                        "Imagem não encontrada: %s",
                        chart_path
                    )



            # ==========================
            # CHAMADA GEMINI
            # ==========================


            resposta = client.models.generate_content(

                model=self.model,

                contents=[

                    types.Content(

                        role="user",

                        parts=partes

                    )

                ],


                config=types.GenerateContentConfig(

                    temperature=0.15,

                    max_output_tokens=1200,

                    response_mime_type="application/json"

                )

            )



            if not resposta:

                return None



            texto = resposta.text



            if not texto:

                return None



            return self._extract_json(
                texto
            )



        except Exception as e:

            logger.error(

                "Erro chamada Gemini: %s",

                e

            )

            raise





    def _extract_json(
        self,
        texto: str

    ) -> Optional[dict[str, Any]]:

        """
        Limpa resposta do Gemini.

        Às vezes ele manda:

        ```json
        {...}
        ```

        mesmo pedindo JSON puro.
        """


        texto = texto.strip()



        if "```" in texto:

            partes = texto.split(
                "```"
            )


            if len(partes) >= 2:

                texto = partes[1]


                if texto.startswith(
                    "json"
                ):

                    texto = texto[4:]



        texto = texto.strip()



        try:

            return json.loads(
                texto
            )


        except json.JSONDecodeError:


            logger.warning(

                "Gemini retornou JSON inválido: %s",

                texto[:300]

            )


            return None

    def _validate_response(
        self,
        data: dict[str, Any],
        original_direction: str

    ) -> dict[str, Any]:

        """
        Valida e padroniza resposta do Gemini.

        A IA pode errar.
        Essa função garante que o robô receba
        sempre um formato previsível.
        """


        if not isinstance(data, dict):

            return None



        operacao = str(
            data.get(
                "operacao",
                ""
            )
        ).upper()



        # Corrige respostas diferentes

        if operacao in (
            "COMPRA",
            "COMPRAR",
            "BUY"
        ):

            operacao = "CALL"



        elif operacao in (
            "VENDA",
            "VENDER",
            "SELL"
        ):

            operacao = "PUT"



        if operacao not in (
            "CALL",
            "PUT"
        ):

            if str(original_direction).lower() in (
                "compra",
                "call"
            ):

                operacao = "CALL"

            else:

                operacao = "PUT"




        # Confiança

        try:

            confianca = int(
                float(
                    data.get(
                        "confianca",
                        0
                    )
                )
            )


        except Exception:

            confianca = 0



        confianca = max(
            0,
            min(
                confianca,
                100
            )
        )



        def texto(campo):

            valor = data.get(
                campo,
                ""
            )

            if valor is None:

                return ""

            return str(
                valor
            )



        def lista(campo):

            valor = data.get(
                campo,
                []
            )


            if not isinstance(
                valor,
                list
            ):

                return []


            return [

                str(x)

                for x in valor

                if x

            ]



        resultado = {


            "concorda_com_robo":

                bool(
                    data.get(
                        "concorda_com_robo",
                        False
                    )
                ),



            "vale_operar":

                bool(
                    data.get(
                        "vale_operar",
                        False
                    )
                ),



            "operacao":

                operacao,



            "setup":

                texto(
                    "setup"
                ),



            "confianca":

                confianca,



            "entrada_agora":

                bool(
                    data.get(
                        "entrada_agora",
                        False
                    )
                ),



            "esperar_confirmacao":

                bool(
                    data.get(
                        "esperar_confirmacao",
                        False
                    )
                ),



            "preco_ideal_entrada":

                texto(
                    "preco_ideal_entrada"
                ),



            "strike_sugerido":

                texto(
                    "strike_sugerido"
                ),



            "stop":

                texto(
                    "stop"
                ),



            "alvo":

                texto(
                    "alvo"
                ),



            "tempo_estimado":

                texto(
                    "tempo_estimado"
                ),



            "risco":

                texto(
                    "risco"
                ),



            "explicacao":

                texto(
                    "explicacao"
                ),



            "pontos_fortes":

                lista(
                    "pontos_fortes"
                ),



            "pontos_fracos":

                lista(
                    "pontos_fracos"
                )

        }


        return resultado

    def format_telegram_message(
        self,
        result: dict[str, Any]

    ) -> str:

        """
        Formata a análise da IA para envio no Telegram.
        """


        if not result:

            return (
                "🤖 <b>ANÁLISE DA IA</b>\n"
                "IA indisponível."
            )



        operacao = result.get(
            "operacao",
            "N/A"
        )


        emoji = (
            "🟢"
            if operacao == "CALL"
            else "🔴"
        )



        linhas = [

            "🤖 <b>ANÁLISE DA IA</b>",

            "",

            f"{emoji} Operação: <b>{operacao}</b>",

            f"📊 Setup: {result.get('setup','')}",

            f"🎯 Confiança: {result.get('confianca',0)}%",

            f"💰 Entrada ideal: {result.get('preco_ideal_entrada','')}",

            f"📈 Strike: {result.get('strike_sugerido','')}",

            f"🛑 Stop: {result.get('stop','')}",

            f"🎯 Alvo: {result.get('alvo','')}",

            f"⏳ Tempo estimado: {result.get('tempo_estimado','')}",

            f"⚠️ Risco: {result.get('risco','')}",

            "",

            "<b>Resumo:</b>",

            result.get(
                "explicacao",
                ""
            )

        ]



        fortes = result.get(
            "pontos_fortes",
            []
        )


        if fortes:

            linhas.append(
                ""
            )

            linhas.append(
                "<b>Pontos fortes:</b>"
            )

            for item in fortes:

                linhas.append(
                    f"✅ {item}"
                )



        fracos = result.get(
            "pontos_fracos",
            []
        )


        if fracos:

            linhas.append(
                ""
            )

            linhas.append(
                "<b>Pontos fracos:</b>"
            )

            for item in fracos:

                linhas.append(
                    f"⚠️ {item}"
                )



        return "\n".join(
            linhas
        )




    def is_available(self) -> bool:

        """
        Verifica se a IA está configurada.
        """

        return bool(
            self.api_key
        )




def criar_analisador_gemini(
    api_key: str,
    model: str = None

) -> AIAnalyzer:

    """
    Factory simples para criação do analisador.
    """

    return AIAnalyzer(
        api_key=api_key,
        model=model
    )
