import google.generativeai as genai
import config
import json

def analisar_com_ia(dados_ativo):
    if not config.GEMINI_API_KEY:
        return None
        
    try:
        genai.configure(api_key=config.GEMINI_API_KEY)
        model = genai.GenerativeModel(config.GEMINI_MODEL)
    except Exception as e:
        print(f"Erro ao iniciar IA: {e}")
        return None

    simb = dados_ativo['simbolo']
    d = dados_ativo['dados']
    
    prompt = f"""
    Atue como trader profissional. Analise {simb}:
    Preço: {d['preco']} | Tendência: {d['tendencia']} | RSI: {d['rsi']} | MACD: {d['macd']} | Score: {dados_ativo['score']}
    
    Retorne APENAS um JSON válido sem markdown:
    {{
        "direcao": "COMPRA" ou "VENDA" ou "NEUTRO",
        "confianca": 0 a 10,
        "padrao": "nome do padrão técnico em 3 palavras",
        "analise": "frase curta e direta",
        "risco": "frase curta sobre o risco principal"
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        texto = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(texto)
    except Exception as e:
        print(f"Falha na IA para {simb}: {e}")
        return None
