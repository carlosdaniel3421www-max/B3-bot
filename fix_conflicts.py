with open(r'C:\Users\carlo\Desktop\B3-bot\relatorio_diario.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '<<<<<<< HEAD\n        deepseek_api_key=getattr(config, "DEEPSEEK_API_KEY", ""),\n        deepseek_model=getattr(config, "DEEPSEEK_MODEL", "deepseek-v4-flash-free"),\n        deepseek_base_url=getattr(config, "DEEPSEEK_BASE_URL", "https://opencode.ai/zen/v1"),\n=======\n        nemotron_api_key=getattr(config, "NEMOTRON_API_KEY", ""),\n        nemotron_model=getattr(config, "NEMOTRON_MODEL", "nemotron-3.5-free"),\n        nemotron_base_url=getattr(config, "NEMOTRON_BASE_URL", "https://opencode.ai/zen/v1'

new = '''        nemotron_api_key=getattr(config, "NEMOTRON_API_KEY", ""),
        nemotron_model=getattr(config, "NEMOTRON_MODEL", "nemotron-3.5-free"),
        nemotron_base_url=getattr(config, "NEMOTRON_BASE_URL", "https://opencode.ai/zen/v1")'''

if "<<<<<<< HEAD" in content:
    content = content.replace(
        "<<<<<<< HEAD\n        deepseek_api_key=getattr(config, \"DEEPSEEK_API_KEY\", \"\"),\n        deepseek_model=getattr(config, \"DEEPSEEK_MODEL\", \"deepseek-v4-flash-free\"),\n        deepseek_base_url=getattr(config, \"DEEPSEEK_BASE_URL\", \"https://opencode.ai/zen/v1\"),\n=======\n        nemotron_api_key=getattr(config, \"NEMOTRON_API_KEY\", \"\"),\n        nemotron_model=getattr(config, \"NEMOTRON_MODEL\", \"nemotron-3.5-free\"),\n        nemotron_base_url=getattr(config, \"NEMOTRON_BASE_URL\", \"https://opencode.ai/zen/v1",
        "        nemotron_api_key=getattr(config, \"NEMOTRON_API_KEY\", \"\"),\n        nemotron_model=getattr(config, \"NEMOTRON_MODEL\", \"nemotron-3.5-free\"),\n        nemotron_base_url=getattr(config, \"NEMOTRON_BASE_URL\", \"https://opencode.ai/zen/v1\")"
    )
    with open(r'C:\Users\carlo\Desktop\B3-bot\relatorio_diario.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('relatorio_diario.py resolved')
else:
    print('No conflicts found')