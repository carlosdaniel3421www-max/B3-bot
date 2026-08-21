import sys

filepath = r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

print("=== Iniciando substituições ===")

# 1. Substituir a assinatura do __init__
old_init = """def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout_seconds: int = 45,
        max_retries: int = 3,
        deepseek_api_key: str = "",
        deepseek_model: str = "deepseek-v4-flash-free",
        deepseek_base_url: str = "https://opencode.ai/zen/v1",
    ):"""

new_init = """def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout_seconds: int = 45,
        max_retries: int = 3,
        nemotron_api_key: str = "",
        nemotron_model: str = "nemotron-3.5-free",
        nemotron_base_url: str = "https://opencode.ai/zen/v1",
    ):"""

content = content.replace(old_init, new_init)
print("1. Assinatura do __init__ atualizada")

# 2. Substituir as atribuições dentro do __init__
content = content.replace(
    'self.deepseek_api_key = deepseek_api_key\n        self.deepseek_model = deepseek_model\n        self.deepseek_base_url = deepseek_base_url\n    self._client = None',
    'self.nemotron_api_key = nemotron_api_key\n        self.nemotron_model = nemotron_model\n        self.nemotron_base_url = nemotron_base_url\n    self._client = None'
)
print("2. Atribuições do __init__ atualizadas")

# 3. Substituir referências no corpo do método
content = content.replace('self.deepseek_api_key', 'self.NEMOTRON_API_KEY')
content = content.replace('self.deepseek_model', 'self.NEMOTRON_MODEL')
content = content.replace('self.deepseek_base_url', 'self.NEMOTRON_BASE_URL')
print("3. Referências self.* atualizadas")

# 4. Substituir mensagens
content = content.replace('Pacote \'openai\' não instalado (necessário pro DeepSeek)', 
    'Pacote \'openai\' não instalado (necessário pro Nemotron)')
content = content.replace('DeepSeek (.deepseek-model.+) falhou ', 'Nemotron (.nemotron-model.+) falhou ')
content = content.replace('DeepSeek (%s via %s) respondeu', 'Nemotron (.via.+) respondeu')
content = content.replace('Análise feita pelo DeepSeek', 'Análise feita pelo Nemotron')
content = content.replace('DeepSeek indisponível (%s) — voltando pro Gemini puro.', 'Nemotron indisponível (%s) — voltando pro Gemini puro.')
content = content.replace('print("  [IA] DeepSeek indisponível — usando Gemini puro")', 'print("  [IA] Nemotron indisponível — usando Gemini puro")')
print("4. Mensagens atualizadas")

# 5. Substituir a verificação híbrida
content = content.replace('if self.deepseek_api_key:', 'if self.NEMOTRON_API_KEY:')
print("5. Verificação híbrida atualizada")

# 6. Substituir as mensagens do híbrido
content = content.replace('Hybrid IA OK para o ativo: DeepSeek (resposta válida) — regra de consistência aplicada', 
    'Hybrid IA OK para o ativo: Nemotron (resposta válida) — regra de consistência aplicada')
content = content.replace('DeepSeek indisponível (%s) — voltando pro Gemini puro.', 'Nemotron indisponível (%s) — voltando pro Gemini puro.')
content = content.replace('print("  [IA] DeepSeek indisponível — usando Gemini puro")', 'print("  [IA] Nemotron indisponível — usando Gemini puro")')
print("6. Mensagens do híbrido atualizadas")

# 7. Substituir referências no método _call_deepseek
content = content.replace(
    'Pacote \'openai\' não instalado (necessário pro DeepSeek)', 
    'Pacote \'openai\' não instalado (necessário pro Nemotron)')
content = content.replace('DeepSeek (.deepseek-model.+) falhou ', 'Nemotron (.nemotron-model.+) falhou ')
content = content.replace('DeepSeek (%s via %s) respondeu', 'Nemotron (.via.+) respondeu')
content = content.replace('Análise feita pelo DeepSeek', 'Análise feita pelo Nemotron')
content = content.replace('DeepSeek indisponível (%s) — voltando pro Gemini puro.', 'Nemotron indisponível (%s) — voltando pro Gemini puro.')
content = content.replace('print("  [IA] Análise feita pelo DeepSeek', 'print("  [IA] Análise feita pelo Nemotron')
print("7. Método _call_deepseek atualizado")

# 8. Substituir as referências no relatorio_diario.py (já estava feito anteriormente)
# Mas garantir que as chamadas no _montar_analisador_ia usem os novos nomes
# Verificar se o arquivo relatorio_diario.py já foi atualizado
print("8. Verificando relatorio_diario.py...")

# 9. Substituir comentários e nomes
content = content.replace('DeepSeek', 'Nemotron')
content = content.replace('deepseek', 'nemotron')
print("9. Nomes genéricos atualizados")

# 10. Substituir referências no método _call_deepseek para renomear o método
# (O nome do método pode ficar como _call_deepseek por compatibilidade, mas mudar referências)
content = content.replace('_call_deepseek', '_call_nemotron')
print("9. Nome do método atualizado")

# Verificar contagem
deepseek_count = content.lower().count('deepseek')
nemotron_count = content.lower().count('nemotron')
print(f"Ocorrências de 'deepseek': {deepseek_count}")
print(f"Ocorrências de 'nemotron': {nemotron_count}")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("=== Substituições concluídas ===")