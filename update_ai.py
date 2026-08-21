import sys

filepath = r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Substituir a assinatura do __init__
old_init = """def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout_seconds: int = 45,
        max_retries: int = 3,
        deepseek_api_key: str = \"\",
        deepseek_model: str = \"deepseek-v4-flash-free\",
        deepseek_base_url: str = \"https://opencode.ai/zen/v1\",
    ):"""

new_init = """def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        timeout_seconds: int = 45,
        max_retries: int = 3,
        nemotron_api_key: str = \"\",
        nemotron_model: str = \"nemotron-3.5-free\",
        nemotron_base_url: str = \"https://opencode.ai/zen/v1\",
    ):"""

content = content.replace(old_init, new_init)

# 2. Substituir as atribuições dentro do __init__
content = content.replace(
    'self.deepseek_api_key = deepseek_api_key\n        self.deepseek_model = deepseek_model\n        self.deepseek_base_url = deepseek_base_url\n    self._client = None',
    'self.nemotron_api_key = nemotron_api_key\n        self.nemotron_model = nemotron_model\n        self.nemotron_base_url = nemotron_base_url\n    self._client = None'
)

# 3. Substituir referências no corpo do método
content = content.replace('self.deepseek_api_key', 'self.NEMOTRON_API_KEY')
content = content.replace('self.deepseek_model', 'self.NEMOTRON_MODEL')
content = content.replace('self.deepseek_base_url', 'self.NEMOTRON_BASE_URL')

# 4. Substituir mensagens
content = content.replace('Pacote \'openai\' não instalado (necessária pro DeepSeek)', 
    'Pacote \'openai\' não instalado (necessário pro Nemotron)')
content = content.replace('DeepSeek (.deepseek-model.+) falhou ', 'Nemotron (.nemotron-model.+) falhou ')
content = content.replace('DeepSeek (%s via %s) respondeu', 'Nemotron (.via.+) respondeu')
content = content.replace('Análise feita pelo DeepSeek', 'Análise feita pelo Nemotron')
content = content.replace('DeepSeek indisponível (%s) — voltando pro Gemini puro.', 'Nemotron indisponível (%s) — voltando pro Gemini puro.')
content = content.replace('print("  [IA] DeepSeek indisponível — usando Gemini puro")', 'print("  [IA] Nemotron indisponível — usando Gemini puro")')

# 5. Substituir na leitura de config no relatorio_diario.py
content = content.replace(
    'deepseek_api_key=getattr(config, "DEEPSEEK_API_KEY", "")',
    'nemotron_api_key=getattr(config, "NEMOTRON_API_KEY", "")'
)
content = content.replace(
    'deepseek_model=getattr(config, "DEEPSEEK_MODEL", "nemotron-3.5-free")',
    'nemotron_model=getattr(config, "NEMOTRON_MODEL", "nemotron-3.5-free")'
)
content = content.replace(
    'deepseek_base_url=getattr(config, "DEEPSEEK_BASE_URL", "https://opencode.ai/zen/v1")',
    'nemotron_base_url=getattr(config, "NEMOTRON_BASE_URL", "https://opencode.ai/zen/v1")'
)

# 6. Substituir a verificação híbrida
content = content.replace('if self.deepseek_api_key:', 'if self.NEMOTRON_API_KEY:')

# 7. Substituir as mensagens do híbrido
content = content.replace('Hybrid IA OK para o ativo: DeepSeek (resposta válida) — regra de consistência aplicada', 
    'Hybrid IA OK para o ativo: Nemotron (resposta válida) — regra de consistência aplicada')
content = content.replace('DeepSeek indisponível (%s) — voltando pro Gemini puro.', 'Nemotron indisponível (%s) — voltando pro Gemini puro.')
content = content.replace('print("  [IA] DeepSeek indisponível — usando Gemini puro")', 'print("  [IA] Nemotron indisponível — usando Gemini puro")')

# 8. Substituir as referências no relatorio_diario.py (já estava feito)
# Verificar se ainda precisa

# 8. Substituir referências no método _call_deepseek
# Contar ocorências
deepseek_count = content.count('deepseek_api_key')
nemotron_count = content.count('NEMOTRON_API_KEY')
print(f'Ocorrências de deepseek_api_key: {deepseek_count}')
print(f'Ocorrências de NEMOTRON_API_KEY: {nemotron_count}')

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print('Substituições concluídas')
"