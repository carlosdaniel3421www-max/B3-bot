import os
import json
import config

def analisar_com_ia(dados_ativo):
    if not config.GEMINI_API_KEY:
        return None
        
    simb = dados_ativo['simbolo']
    d = dados_ativo['dados']
    
    prompt = f"""
    Atue como trader profissional de opções na B3. Analise friamente:
    Ativo: {simb}
    Preço: R$ {d['preco']}
    Tendência: {d['tendencia']}
    RSI: {d['rsi']}
    MACD: {d['macd']} (Signal: {d['macd_signal']})
    Score Técnico: {dados_ativo['score']}/10

    Retorne APENAS um JSON válido, sem markdown, sem crases:
    {{
        "direcao": "COMPRA",
        "confianca": 8,
        "padrao": "Pullback na MM9",
        "analise": "Preço respeitando suporte dinâmico.",
        "risco": "Romper a mínima de ontem."
    }}
    """

    # Tentativa 1: Usando a biblioteca nova (google.genai)
    try:
        from google import genai
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        texto = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(texto)
    except Exception as e1:
        # Se falhar, tenta a biblioteca antiga (google.generativeai) como fallback
        try:
            import google.generativeai as genai_old
            genai_old.configure(api_key=config.GEMINI_API_KEY)
            model = genai_old.GenerativeModel('gemini-pro') # gemini-pro é mais estático na API antiga
            response = model.generate_content(prompt)
            texto = response.text.replace('```json', '').replace('```', '').strip()
            return json.loads(texto)
        except Exception as e2:
            print(f"Falha na IA para {simb}. Erro novo: {e1}. Erro old: {e2}")
            return None
