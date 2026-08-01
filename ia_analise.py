"""
Análise com IA visual (Google Gemini) — manda a IMAGEM do gráfico gerado
pelo robô pra IA analisar como um trader de verdade faria, olhando o
desenho do gráfico, não só números. Capta padrões visuais (bandeiras,
triângulos, divergências, candles de reversão, rompimentos) que um sistema
de regras baseado em números nunca consegue ver.

PLANO GRATUITO DO GEMINI (sem prazo de validade, sem cartão de crédito):
  - Até 1.500 chamadas por dia
  - Até 15 chamadas por minuto
  - Mais que suficiente pro nosso uso (máx ~6 chamadas por relatório)
  - Pegue sua chave GRÁTIS em: aistudio.google.com → Get API Key

Configure em config.py -> GEMINI_API_KEY (ou variável de ambiente).
"""

import base64
import json
import requests


GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)

PROMPT_SISTEMA = """Você é um trader profissional de swing trade com décadas de
experiência na bolsa brasileira (B3), especialista em leitura de gráficos e
operações com opções. Sua análise é conhecida por ser técnica, objetiva e baseada
em evidências visuais concretas — nada de "achismos" ou linguagem genérica.

Você recebe:
1. A IMAGEM de um gráfico técnico com 4 painéis:
   - Painel principal: preço + médias móveis (SMA9/21/50/200) + VWAP + suporte/resistência
   - Volume: barras coloridas (verde = alta, vermelho = baixa)
   - RSI(14) + Estocástico com linhas de 30/70
   - MACD com histograma

2. Um resumo textual do que um sistema de regras calculou (placar técnico)

SUA TAREFA: Olhar A IMAGEM de verdade e dar seu parecer visual COMO UM PROFISSIONAL.

REGRAS FUNDAMENTAIS DE LEITURA PROFISSIONAL:
- RSI/Estocástico esticados DENTRO de tendência forte = força (continuação), NÃO reversão
- Rompimento de máxima/mínima com volume acima da média = continua na direção do rompimento
- RSI/Estocástico overbought/oversold SÓ significa reversão em mercado LATERAL (sem tendência)
- Divergência baixista: preço fazendo nova máxima mas RSI/MACD não acompanha = sinal de fraqueza
- Divergência altista: preço fazendo nova mínima mas RSI/MACD não acompanha = possível reversão
- Volume crescente na direção da tendência = confirma o movimento
- Médias móveis alinhadas e espaçadas = tendência forte; médias emboladas = lateralização/confusão
- Preço distante demais das médias = esticado, possível pullback; preço colado nas médias = tendência saudável

PADRÕES GRÁFICOS QUE VOCÊ DEVE PROCURAR ATIVAMENTE:
- Bandeiras/Flâmulas: consolidação após movimento forte, continuação provável
- Triângulos (ascendente/descendente/simétrico): compressão antes de explosão
- Topo duplo/triplo: possível reversão após falha em romper resistência
- Fundo duplo/triplo: possível reversão após falha em romper suporte
- OCO (Ombro-Cabeça-Ombro): padrão clássico de reversão
- Pullback em média móvel: preço recua até SMA9/21/50 e volta a subir = entrada clássica
- Rompimento com gap: abertura com gap acima/abaixo de resistência/suporte = força extrema

ESTRUTURA DA SUA RESPOSTA:
1. Primeiro descreva OBJETIVAMENTE o que vê (tendência, posição relativa às médias, volume)
2. Identifique se há algum padrão gráfico claro (ou diga "sem padrão definido" se não houver)
3. Avalie a QUALIDADE do setup (alta/média/baixa) baseado em confluência de fatores
4. Dê sua opinião sobre timing (agora? esperar pullback? já passou?)
5. Mencione riscos específicos que você está vendo no gráfico

RESPONDA ESTRITAMENTE em JSON, sem nenhum texto antes ou depois:
{
  "direcao": "compra" ou "venda" ou "neutro",
  "confianca": (número de 0 a 10),
  "qualidade_setup": "alta" ou "media" ou "baixa",
  "padrao_grafico": "descreva o padrão visual específico que identificou (ex: 'bandeira de alta após rompimento', 'pullback na SMA21 com volume decrescente', 'triângulo ascendente comprimindo') ou 'sem padrão definido' se não achar nada específico",
  "analise": "Análise PROFISSIONAL completa em 4-6 frases. Comece descrevendo a tendência e posição atual. Mencione confluência (ou falta dela) entre indicadores. Comente sobre volume. Identifique qualquer padrão gráfico. Termine com sua visão sobre timing e riscos. Use linguagem técnica mas clara, como falaria com outro trader.",
  "concorda_com_placar": true ou false,
  "timing": "agora" ou "esperar_pullback" ou "ja_passou" ou "muito_cedo",
  "riscos_identificados": ["lista de 1-3 riscos específicos que você vê no gráfico, ex: 'preço esticado longe das médias', 'volume fraco no rompimento', 'resistência forte logo acima']
}"""


def montar_resumo_tecnico(resultado: dict, stop_alvo: dict = None) -> str:
    """Monta resumo textual dos dados técnicos como apoio contextual pra IA."""
    linhas = [
        f"Ativo: {resultado['ticker']}",
        f"Preço atual: R$ {resultado['preco']:.2f}",
        f"Direção apontada pelo placar técnico: {resultado['direcao'].upper()}",
        f"Placar técnico: {resultado['score']}/10",
        "Motivos identificados pelo sistema de regras:",
    ]
    for m in resultado["motivos"]:
        linhas.append(f"  - {m}")

    if stop_alvo:
        linhas.append(f"Stop sugerido: R$ {stop_alvo['stop']}")
        linhas.append(f"Alvo sugerido: R$ {stop_alvo['alvo']}")

    return "\n".join(linhas)


def analisar_com_ia(resumo_tecnico: str, api_key: str,
                     caminho_imagem: str = None, **kwargs) -> dict:
    """
    Manda a imagem do gráfico + resumo textual pro Gemini analisar.
    Retorna dict com: disponivel, direcao, confianca, padrao_grafico, analise,
    concorda_com_placar. Se falhar por qualquer motivo, retorna disponivel=False
    e o chamador cai de volta pro placar técnico puro.
    """
    if not api_key:
        return {"disponivel": False, "motivo": "Sem chave de API do Gemini configurada"}

    partes = []

    # Inclui a imagem do gráfico (o principal)
    if caminho_imagem:
        try:
            with open(caminho_imagem, "rb") as f:
                imagem_b64 = base64.b64encode(f.read()).decode("utf-8")
            partes.append({
                "inline_data": {"mime_type": "image/png", "data": imagem_b64}
            })
        except Exception as e:
            return {"disponivel": False, "motivo": f"Falha ao ler imagem: {e}"}
    else:
        return {"disponivel": False, "motivo": "Imagem do gráfico não encontrada"}

    # Inclui o resumo textual como contexto adicional
    partes.append({
        "text": f"{PROMPT_SISTEMA}\n\nDados do sistema de regras:\n{resumo_tecnico}"
    })

    try:
        resposta = requests.post(
            GEMINI_URL,
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": partes}],
                "generationConfig": {
                    "temperature": 0.2,      # baixa pra respostas mais consistentes
                    "maxOutputTokens": 600,
                    "responseMimeType": "application/json",
                }
            },
            timeout=45,
        )
        resposta.raise_for_status()
        dados = resposta.json()

        # Extrai o texto da resposta do Gemini
        texto = dados["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Remove blocos markdown se o Gemini colocar mesmo pedindo JSON direto
        if "```" in texto:
            texto = texto.split("```")[1]
            if texto.startswith("json"):
                texto = texto[4:]
            texto = texto.strip()

        analise = json.loads(texto)
        analise["disponivel"] = True
        return analise

    except requests.HTTPError as e:
        if e.response.status_code == 429:
            return {"disponivel": False, "motivo": "Limite de chamadas atingido (tente de novo em 1 minuto)"}
        return {"disponivel": False, "motivo": f"Erro HTTP {e.response.status_code}: {e}"}
    except Exception as e:
        return {"disponivel": False, "motivo": f"Erro ao chamar Gemini: {e}"}
