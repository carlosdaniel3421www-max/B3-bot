"""
Análise com IA visual (Google Gemini) — manda os gráficos dos melhores
ativos do dia pro Gemini analisar visualmente, como um trader profissional
faria. Retorna uma mensagem consolidada com "por que entrar" e "por que
não entrar" pra cada ativo analisado.

PLANO GRATUITO DO GEMINI (sem prazo de validade, sem cartão de crédito):
  - Até 1.500 chamadas por dia (15 por minuto)
  - Pegue sua chave GRÁTIS em: aistudio.google.com → Get API Key
"""

import base64
import json
import requests
import time

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)


def _codificar_imagem(caminho: str) -> str:
    with open(caminho, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def analisar_ativo_visualmente(ticker: str, score: int, direcao: str,
                                motivos: list, preco: float,
                                caminho_imagem: str, api_key: str) -> dict:
    """
    Analisa UM ativo visualmente (imagem do gráfico) e retorna:
    - razoes_entrar: lista de motivos pra fazer a entrada
    - razoes_nao_entrar: lista de motivos pra NÃO fazer a entrada
    - veredicto: "ENTRAR", "AGUARDAR" ou "EVITAR"
    - confianca: 0-10
    """
    if not api_key:
        return {"disponivel": False, "motivo": "Sem chave GEMINI_API_KEY configurada"}

    try:
        imagem_b64 = _codificar_imagem(caminho_imagem)
    except Exception as e:
        return {"disponivel": False, "motivo": f"Erro ao ler imagem: {e}"}

    motivos_txt = "\n".join(f"- {m}" for m in motivos)

    prompt = f"""Você é um trader profissional de swing trade na B3 com 20 anos de experiência.

Analise o gráfico do ativo {ticker} (preço R$ {preco:.2f}) e os dados técnicos abaixo.

DADOS DO SISTEMA DE REGRAS:
- Direção apontada: {direcao.upper()}
- Placar técnico: {score}/10
- Motivos identificados:
{motivos_txt}

O gráfico tem 4 painéis: preço com médias (SMA9/21/50/200) + suporte/resistência, volume, RSI/Estocástico e MACD.

REGRAS PARA DECISÃO DE ENTRAR:

1) SE score >= 8: A IA DEVE CONCORDAR com a entrada do robô. Veredicto esperado: "ENTRAR". 
   A menos que haja sinais visuais claros de exaustão (preço no topo, sombra longa, reversão de candle).
   
2) SE score entre 6 e 7: IA pode concordar ou discordar. Se indicadores conflitantes (RSI extremo + volume baixo), pencione para "AGUARDAR".
   
3) SE score abaixo de 6: IA deve concordar que NÃO há setup suficiente. Veredicto: "AGUARDAR" ou "EVITAR".

REGRAS PARA "RAZÕES_NAO_ENTRAR":
- Apenas liste motivos se veredicto for "EVITAR" ou "AGUARDAR"
- Exemplos válidos: "RSI > 80 + volume abaixo da média = sobrecompra sem força"
- NÃO liste opiniões gericas sobre o robô

REGRAS PARA CONFIANÇA (0-100):
- 80-100: Sinais totalmente alinhados, gráfico confirma dados técnicos
- 50-79: Sinais mistos, precisa de confirmação extra
- 0-49: Não vale operar com base nesses sinais sozinhos

Responda APENAS em JSON válido, sem markdown, sem texto fora do JSON.
Formato obrigatório:

{{
  "razoes_entrar": ["motivo técnico específico", "outro motivo técnico"],
  "razoes_nao_entrar": ["motivo específico se não operar, ex: 'RSI muito alto sem volume'"],
  "veredicto": "ENTRAR",
  "confianca": 85,
  "resumo": "Frase direta de no máximo 20 palavras resumindo a leitura"
}}"""

    try:
        resposta = requests.post(
            GEMINI_URL,
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{
                    "parts": [
                        {"inline_data": {"mime_type": "image/png", "data": imagem_b64}},
                        {"text": prompt}
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 500,
                }
            },
            timeout=45,
        )
        resposta.raise_for_status()
        dados = resposta.json()
        texto = dados["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Remove markdown se vier
        if "```" in texto:
            partes = texto.split("```")
            for parte in partes:
                parte = parte.strip()
                if parte.startswith("json"):
                    parte = parte[4:].strip()
                try:
                    resultado = json.loads(parte)
                    resultado["disponivel"] = True
                    return resultado
                except:
                    continue

        resultado = json.loads(texto)
        resultado["disponivel"] = True
        return resultado

    except requests.HTTPError as e:
        codigo = e.response.status_code if e.response else "?"
        if codigo == 429:
            return {"disponivel": False, "motivo": "Limite de chamadas atingido (aguarde 1 min)"}
        return {"disponivel": False, "motivo": f"Erro HTTP {codigo}"}
    except json.JSONDecodeError:
        return {"disponivel": False, "motivo": "IA retornou formato inesperado"}
    except Exception as e:
        return {"disponivel": False, "motivo": f"Erro: {e}"}


def formatar_analise_ia(ticker: str, preco: float, analise: dict) -> str:
    """Formata a análise da IA em texto pronto pra enviar no Telegram."""
    if not analise.get("disponivel"):
        return f"⚠️ <b>{ticker}</b> — IA indisponível: {analise.get('motivo', 'erro desconhecido')}"

    veredicto = analise.get("veredicto", "AGUARDAR")
    emoji = {"ENTRAR": "🟢", "AGUARDAR": "🟡", "EVITAR": "🔴"}.get(veredicto, "⚪")
    confianca = analise.get("confianca", 0)

    linhas = [
        f"{emoji} <b>{ticker}</b> — R$ {preco:.2f} | Veredicto: <b>{veredicto}</b> ({confianca}/10)",
        f"<i>{analise.get('resumo', '')}</i>",
    ]

    razoes_entrar = analise.get("razoes_entrar", [])
    if razoes_entrar:
        linhas.append("\n✅ <b>Por que entrar:</b>")
        for r in razoes_entrar:
            linhas.append(f"  • {r}")

    razoes_nao_entrar = analise.get("razoes_nao_entrar", [])
    if razoes_nao_entrar:
        linhas.append("\n❌ <b>Por que NÃO entrar:</b>")
        for r in razoes_nao_entrar:
            linhas.append(f"  • {r}")

    return "\n".join(linhas)


def montar_resumo_tecnico(resultado: dict, stop_alvo: dict = None) -> str:
    """Mantido por compatibilidade com chamadas existentes."""
    linhas = [
        f"Ativo: {resultado['ticker']}",
        f"Preço atual: R$ {resultado['preco']:.2f}",
        f"Direção: {resultado['direcao'].upper()} | Score: {resultado['score']}/10",
        "Motivos:",
    ]
    for m in resultado["motivos"]:
        linhas.append(f"  - {m}")
    if stop_alvo:
        linhas.append(f"Stop: R$ {stop_alvo['stop']} | Alvo: R$ {stop_alvo['alvo']}")
    return "\n".join(linhas)


def analisar_com_ia(resumo_tecnico: str, api_key: str,
                     caminho_imagem: str = None, **kwargs) -> dict:
    """Mantido por compatibilidade — redireciona pra nova função."""
    return {"disponivel": False, "motivo": "Use analisar_ativo_visualmente diretamente"}
