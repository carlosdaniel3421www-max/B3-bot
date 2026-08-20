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
import re
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


    DEFAULT_MODEL = "gemini-3.5-flash-lite"

    # Modelos alternativos, tentados em ordem se o modelo principal
    # devolver 404 (NOT_FOUND — comum quando a Google descontinua/restringe
    # um modelo). Mantém o robô funcionando mesmo se o nome do modelo
    # configurado parar de existir de um dia pro outro.
    MODELOS_FALLBACK = (
        "gemini-3.5-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-2.0-flash-lite",
    )


    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout_seconds: int = 45,
        max_retries: int = 3,
        deepseek_api_key: str = "",
        deepseek_model: str = "deepseek/deepseek-v4-flash:free",
        deepseek_base_url: str = "https://openrouter.ai/api/v1",
    ):

        self.api_key = api_key

        self.model = model or self.DEFAULT_MODEL

        self.timeout_seconds = timeout_seconds

        self.max_retries = max_retries

        self.deepseek_api_key = deepseek_api_key

        self.deepseek_model = deepseek_model

        self.deepseek_base_url = deepseek_base_url

        self._client = None

        # Guarda o motivo real da última falha (status HTTP, tipo de exceção,
        # mensagem). None enquanto tudo estiver funcionando. Quem chama
        # analyze_asset() pode ler isso depois de um retorno None para saber
        # exatamente por que a IA ficou indisponível, em vez de um
        # "erro genérico" sem causa.
        self.ultimo_erro: Optional[str] = None

        # Provedor de IA que respondeu na última análise bem-sucedida:
        # "deepseek" (híbrido: Gemini descreveu o gráfico, DeepSeek analisou)
        # ou "gemini" (Gemini puro — DeepSeek sem chave/indisponível).
        self.ultimo_provedor: str = "gemini"



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

            self.ultimo_erro = f"Falha ao criar cliente Gemini ({type(e).__name__}): {e}"

            logger.error(
                "Erro criando cliente Gemini: %s",
                e,
                exc_info=True,
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


        self.ultimo_erro = None

        if not self.api_key:

            self.ultimo_erro = "Sem GEMINI_API_KEY configurada (verifique o secret no GitHub Actions)"

            logger.warning(
                "Gemini sem API KEY"
            )

            return None



        client = self._get_client()


        if not client:

            if not self.ultimo_erro:
                self.ultimo_erro = "Não foi possível criar o cliente Gemini (verifique se o pacote google-genai está instalado)"

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


        modelos_para_tentar = list(dict.fromkeys([self.model, *self.MODELOS_FALLBACK]))
        indice_modelo = 0

        # --- HÍBRIDO: tenta DeepSeek (raciocínio forte) primeiro ---
        # O Gemini só descreve o gráfico; o DeepSeek faz a análise final.
        if self.deepseek_api_key:
            resposta_deepseek = self._call_deepseek(prompt, chart_path)
            if resposta_deepseek:
                self.ultimo_provedor = "deepseek"
                logger.info(
                    "Hybrid IA OK para o ativo: DeepSeek (resposta válida) — regra de consistência aplicada"
                )
                return self._validate_response(
                    resposta_deepseek,
                    direction,
                    score
                )
            logger.warning(
                "DeepSeek indisponível (%s) — voltando pro Gemini puro.",
                self.ultimo_erro,
            )
            print("  [IA] DeepSeek indisponível — usando Gemini puro")

        for attempt in range(1, self.max_retries + 1):

            modelo_atual = modelos_para_tentar[min(indice_modelo, len(modelos_para_tentar) - 1)]

            try:

                response = self._call_gemini(
                    client,
                    prompt,
                    chart_path,
                    modelo=modelo_atual,
                )


                if response:

                    self.ultimo_provedor = "gemini"

                    return self._validate_response(
                        response,
                        direction,
                        score
                    )

                self.ultimo_erro = (
                    f"Tentativa {attempt}/{self.max_retries} ({modelo_atual}): Gemini respondeu, "
                    f"mas sem JSON válido (ver logs para o texto bruto)"
                )


            except Exception as e:

                codigo_http = (
                    getattr(e, "code", None)
                    or getattr(e, "status_code", None)
                    or getattr(e, "status", None)
                )

                self.ultimo_erro = (
                    f"Tentativa {attempt}/{self.max_retries} ({modelo_atual}) falhou "
                    f"(status={codigo_http}, tipo={type(e).__name__}): {e}"
                )

                logger.warning(
                    "Tentativa %s/%s (%s) de chamada ao Gemini falhou "
                    "(status=%s, tipo=%s): %s",
                    attempt,
                    self.max_retries,
                    modelo_atual,
                    codigo_http,
                    type(e).__name__,
                    e,
                    exc_info=True,
                )

                eh_modelo_indisponivel = str(codigo_http) == "404" or "NOT_FOUND" in str(e)

                if eh_modelo_indisponivel and indice_modelo < len(modelos_para_tentar) - 1:
                    indice_modelo += 1
                    logger.warning(
                        "Modelo %s indisponível, tentando %s na próxima chamada",
                        modelo_atual,
                        modelos_para_tentar[indice_modelo],
                    )
                    continue  # tenta o próximo modelo imediatamente, sem esperar

                atraso = self._extrair_delay_retry(e)
                if atraso is None:
                    atraso = attempt * 2

                time.sleep(min(atraso, 65))



        if not self.ultimo_erro:
            self.ultimo_erro = "Gemini não retornou resposta utilizável após todas as tentativas"

        return None

    @staticmethod
    def _extrair_delay_retry(erro: Exception) -> Optional[float]:
        """
        Extrai o tempo de espera real sugerido pelo Google num erro 429
        (RESOURCE_EXHAUSTED), ex: "Please retry in 56.99s" ou
        retryDelay: "56s". Retorna None se não encontrar nada — nesse
        caso quem chama usa um backoff padrão.
        """
        texto = str(erro)

        match = re.search(r"retry in ([\d.]+)\s*s", texto, re.IGNORECASE)
        if match:
            return float(match.group(1))

        match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?([\d.]+)\s*s", texto, re.IGNORECASE)
        if match:
            return float(match.group(1))

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

IMPORTANTE SOBRE A ESCALA DE CONFIANÇA:

O campo "confianca" é um número INTEIRO de 0 a 100 (percentual),
representando o quanto VOCÊ está confiante nessa análise.

Essa escala é DIFERENTE da escala do "score_robo" que você recebe
(o score do robô é 0 a 10). NÃO copie o valor do score_robo para o
campo confianca. Avalie sua própria confiança de 0 a 100 com base
na qualidade e clareza dos sinais que você está vendo.

Exemplos: sinais fracos ou conflitantes = confiança baixa (10-40).
Sinais razoáveis mas com alguma dúvida = confiança média (40-70).
Sinais fortes e alinhados (tendência + volume + momentum concordando)
= confiança alta (70-95). Nunca use 100 (sempre há algum risco).



REGRAS DE ANÁLISE:

REGRA DE CONSISTÊNCIA COM O ROBÔ (OBRIGATÓRIA — NÃO PODE QUEBRAR):

O campo "score_robo" (0 a 10) já é o placar técnico calculado pelo robô.
A SUA RESPOSTA SERÁ FORÇADA A SEGUIR ESTA REGRA NO CÓDIGO. Portanto,
responda SEMPRE coerente com ela:

1) SE score_robo >= 8 (o robô deu ENTRAR):
   - "concorda_com_robo" = true
   - "vale_operar" = true
   - "entrada_agora" = true
   - "esperar_confirmacao" = false
   Você PODE e DEVE apontar riscos, mas a entrada é aprovada.

2) SE score_robo entre 6 e 7 (o robô deu AGUARDAR):
   - "vale_operar" = false
   - "entrada_agora" = false
   - "esperar_confirmacao" = true
   Ainda não é hora de entrar. Explique o que falta pra confirmar.

3) SE score_robo abaixo de 6 (o robô deu EVITAR):
   - "concorda_com_robo" = false
   - "vale_operar" = false
   - "entrada_agora" = false
   Não há setup suficiente. Diga o que está faltando.

4) NUNCA contradiga o robô. A IA é uma SEGUNDA OPINIÃO que explica e
   detalha a decisão do robô — nunca é ela quem decide entrar ou não.
   Seu papel: explicar POR QUE o placar do robô faz sentido (ou avisar
   dos riscos), não criar um veredito paralelo.

5) EXAUSTÃO DE TENDÊNCIA: Se o preço subiu consecutivamente por 3-5 dias
   sem pullback de no mínimo 2-3%, a tendência pode estar madura para
   correção. RSI > 75 + volume constante = risco alto de reversão imediata.
   Isso deve constar em "pontos_fracos" e "explicacao" como aviso de risco,
   mas NÃO muda "vale_operar" (que é definido pela regra acima).

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
        modelo: Optional[str] = None,

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

                model=modelo or self.model,

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

                e,

                exc_info=True,

            )

            raise





    def _descrever_grafico_gemini(
        self,
        chart_path: Optional[str | Path] = None
    ) -> str:
        """
        HÍBRIDO — passo 1: usa o Gemini (modelo gratuito) apenas para
        DESCREVER o gráfico em texto, já que o DeepSeek não enxerga imagens.

        Retorna a descrição textual (vazia se não houver imagem ou falhar).
        """
        if not chart_path:
            return ""

        caminho = Path(chart_path)
        if not caminho.exists():
            return ""

        client = self._get_client()
        if not client:
            return ""

        try:
            from google.genai import types

            imagem = caminho.read_bytes()

            resposta = client.models.generate_content(
                model="gemini-flash-lite-latest",
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text=(
                                    "Descreva ESTE gráfico de candlestick de forma técnica "
                                    "e objetiva em português (máximo 6 linhas): tendência, "
                                    "padrões de candle visíveis, toque em suporte/resistência, "
                                    "comportamento do volume, sinais de exaustão ou reversão. "
                                    "Sem opinião de compra/venda — só descrição factual do gráfico."
                                )
                            ),
                            types.Part.from_bytes(
                                data=imagem,
                                mime_type="image/png"
                            ),
                        ],
                    )
                ],
            )

            if resposta and resposta.text:
                return resposta.text.strip()

        except Exception as e:
            logger.warning(
                "Falha ao descrever gráfico com Gemini: %s",
                e,
                exc_info=True,
            )

        return ""

    def _call_deepseek(
        self,
        prompt: str,
        chart_path: Optional[str | Path] = None,
    ) -> Optional[dict[str, Any]]:
        """
        HÍBRIDO — passo 2: chama o DeepSeek (raciocínio forte) com os dados
        técnicos + a descrição do gráfico feita pelo Gemini.

        Retorna o JSON da análise. None se falhar (aí o fluxo volta pro
        Gemini puro, que enxerga a imagem).
        """
        if not self.deepseek_api_key:
            return None

        try:
            from openai import OpenAI
        except ImportError:
            self.ultimo_erro = "Pacote 'openai' não instalado (necessário pro DeepSeek)"
            return None

        try:
            descricao_grafico = self._descrever_grafico_gemini(chart_path)

            prompt_final = prompt
            if descricao_grafico:
                prompt_final += (
                    "\n\n===== DESCRIÇÃO DO GRÁFICO (feita por um modelo de visão) =====\n"
                    f"{descricao_grafico}\n"
                    "Use essa descrição como apoio visual. Lembre-se: a regra de "
                    "consistência com o score_robo continua valendo."
                )

            client = OpenAI(
                api_key=self.deepseek_api_key,
                base_url=self.deepseek_base_url,
                timeout=self.timeout_seconds,
                default_headers={"HTTP-Referer": "https://github.com/", "X-Title": "B3-bot"},
            )

            resposta = client.chat.completions.create(
                model=self.deepseek_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Você é um analista técnico de ações experiente. "
                            "Responda APENAS com JSON válido, sem texto antes ou depois."
                        ),
                    },
                    {"role": "user", "content": prompt_final},
                ],
                temperature=0.15,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )

            texto = resposta.choices[0].message.content if resposta.choices else None
            if not texto:
                return None

            logger.info(
                "DeepSeek (%s via %s) respondeu — análise feita pelo DeepSeek V4 Flash Free",
                self.deepseek_model,
                self.deepseek_base_url,
            )
            print(f"  [IA] Análise feita pelo DeepSeek ({self.deepseek_model})")

            return self._extract_json(texto)

        except Exception as e:
            codigo_http = (
                getattr(e, "status_code", None)
                or getattr(e, "code", None)
                or getattr(e, "status", None)
            )
            self.ultimo_erro = (
                f"DeepSeek ({self.deepseek_model}) falhou "
                f"(status={codigo_http}, tipo={type(e).__name__}): {e}"
            )
            logger.warning(
                "Erro chamada DeepSeek: %s",
                e,
                exc_info=True,
            )
            return None


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
        original_direction: str,
        score_robo: float = 0

    ) -> dict[str, Any]:

        """
        Valida e padroniza resposta do Gemini.

        A IA pode errar.
        Essa função garante que o robô receba
        sempre um formato previsível.

        REGRA RÍGIDA (imposta aqui no código, não só no prompt):
        A IA SÓ pode aprovar entrada ("vale_operar") quando o robô deu
        o sinal verde ENTRAR (score >= 8). Abaixo disso ela é FORÇADA a
        NÃO operar, não importa o que o Gemini tenha escrito.
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

        # ------------------------------------------------------------------
        # REGRA RÍGIDA DE CONSISTÊNCIA COM O ROBÔ (imposta no código):
        # A IA SÓ aprova entrada quando o robô deu ENTRAR (score >= 8).
        # Senão, força a resposta da IA a NÃO operar, ignorando o que o
        # Gemini escreveu (ele pode errar ou "viajar").
        # ------------------------------------------------------------------
        if score_robo >= 8:
            resultado["concorda_com_robo"] = True
            resultado["vale_operar"] = True
            resultado["entrada_agora"] = True
            resultado["esperar_confirmacao"] = False
        else:
            resultado["concorda_com_robo"] = False
            resultado["vale_operar"] = False
            resultado["entrada_agora"] = False
            resultado["esperar_confirmacao"] = True

        return resultado

    def format_telegram_message(
        self,
        result: dict[str, Any]

    ) -> str:

        """
        Formata a análise da IA para envio no Telegram, em bullets diretos
        (concordância, entrada ideal, strike, stop, alvo, motivo) — o mesmo
        JSON de sempre, só a apresentação é mais enxuta.
        """

        if not result:

            return "IA indisponível."

        operacao = result.get("operacao", "N/A")

        concorda = result.get("concorda_com_robo", False)
        vale_operar = result.get("vale_operar", False)

        linhas = []

        # --- concordância com o robô ---
        if concorda:
            linhas.append("✅ Concordo com o sinal do robô.")
        else:
            linhas.append("❌ Discordo do sinal do robô.")

        if not vale_operar:
            linhas.append("⚠️ Na minha leitura, não vale operar agora.")

        # --- plano de entrada ---
        setup = result.get("setup", "")
        entrada = result.get("preco_ideal_entrada", "")
        if entrada:
            sufixo_setup = f" ({setup})" if setup else ""
            linhas.append(f"💰 Entrada ideal: R$ {entrada}{sufixo_setup}")

        strike = result.get("strike_sugerido", "")
        if strike:
            tempo = result.get("tempo_estimado", "")
            sufixo_tempo = f" ({tempo})" if tempo else ""
            linhas.append(f"📈 Strike sugerido: {operacao} {strike}{sufixo_tempo}")

        stop = result.get("stop", "")
        if stop:
            linhas.append(f"🛑 Stop: R$ {stop}")

        alvo = result.get("alvo", "")
        if alvo:
            linhas.append(f"🎯 Alvo: R$ {alvo}")

        risco = result.get("risco", "")
        confianca = result.get("confianca", 0)
        if risco:
            linhas.append(f"⚠️ Risco: {risco} (confiança da IA: {confianca}%)")

        # --- motivo (o "porquê" — o mais importante pra decisão) ---
        explicacao = result.get("explicacao", "")
        if explicacao:
            linhas.append(f"🧠 {explicacao}")

        for item in result.get("pontos_fortes", []):
            linhas.append(f"  + {item}")

        for item in result.get("pontos_fracos", []):
            linhas.append(f"  – {item}")

        return "\n".join(
            l if l.startswith("  ") else f"• {l}"
            for l in linhas
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
