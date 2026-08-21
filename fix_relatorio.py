with open(r'C:\Users\carlo\Desktop\B3-bot\relatorio_diario.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''nemotron_base_url=getattr(config, "NEMOTRON_BASE_URL", "https://opencode.ai/zen/v1")"),
>>>>>>> bb04106 (Troca DeepSeek por Nemotron 3.5 do opencode zen)
    )'''

new = '''nemotron_base_url=getattr(config, "NEMOTRON_BASE_URL", "https://opencode.ai/zen/v1"),
    )'''

if '>>>>>>> bb04106' in content:
    content = content.replace(old, new)
    with open(r'C:\Users\carlo\Desktop\B3-bot\relatorio_diario.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Fixed relatorio_diario.py')
else:
    print('No conflicts found')