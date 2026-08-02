import os
import json
from google import genai
import config

def analisar_com_ia(dados_ativo):
    if not config.GEMINI_API_KEY:
        return None
        
    try:
        # Inicializa o cliente correto
        client = genai.Client(api_key=config.GEMINI_API_KEY)
    except Exception as e:
        print(f"Erro ao iniciar cliente IA: {e}")
        return None

    simb = dados_ativo['simbolo']
    d = dados_ativo['dados']
    
    prompt = f"""
    Atue como trader profissional. Analise {simb}:
    Preço: {d['preco']} | Tendência: {d['tendencia']} | RSI: {d['rsi']} | Score: {dados_ativo['score']}
    
    Retorne APENAS um JSON válido sem markdown:
    {{
        "direcao": "COMPRA" ou "VENDA" ou "NEUTRO",
        "confianca": 0 a 10,
        "padrao": "nome do padrão técnico",
        "analise": "frase curta",
        "risco": "frase curta sobre risco"
    }}
    """
    
    try:
        # Chama a API com o modelo correto
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        
        texto = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(texto)
        
    except Exception as e:
        print(f"Falha na IA para {simb}: {e}")
        return None
