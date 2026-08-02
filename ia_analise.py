import json
from google import genai
import config

def analisar_com_ia(dados_ativo):
    """Envia dados para o Gemini e retorna análise estruturada."""
    if not config.GEMINI_API_KEY:
        return None
        
    try:
        client = genai.Client(api_key=config.GEMINI_API_KEY)
    except Exception as e:
        print(f"Erro ao iniciar cliente IA: {e}")
        return None

    simb = dados_ativo['simbolo']
    d = dados_ativo['dados']
    
    prompt = f"""
    Atue como um trader profissional de opções da B3. Analise friamente os dados:
    Ativo: {simb}
    Preço: R$ {d['preco']}
    Tendência: {d['tendencia']}
    RSI: {d['rsi']}
    MACD: {d['macd']} (Linha de Sinal: {d['macd_signal']})
    Score Técnico: {dados_ativo['score']}/10

    Tarefa:
    1. Defina direção (COMPRA, VENDA ou NEUTRO).
    2. Nível de confiança (0 a 10).
    3. Identifique o padrão gráfico provável (ex: Pullback, Rompimento).
    4. Resuma a tese em uma frase curta.
    5. Aponte o maior risco atual.

    Retorne APENAS um JSON válido, sem markdown, sem crases, sem texto extra:
    {{
        "direcao": "COMPRA",
        "confianca": 8,
        "padrao": "Pullback na MM9",
        "analise": "Preço respeitando suporte dinâmico com volume crescente.",
        "risco": "Romper a mínima de ontem invalida o setup."
    }}
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        
        if not response.text:
            return None
            
        # Limpeza de segurança caso a IA envie markdown
        texto_limpo = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(texto_limpo)
        
    except Exception as e:
        print(f"Falha na análise de IA para {simb}: {e}")
        return None
