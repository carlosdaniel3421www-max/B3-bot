with open(r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''            logger.warning(
                "Nemotron indisponível (%s) — voltando pro Gemini puro.",
                self.ultimo_erro,
            )
            print("  [IA] Nemotron indisponível — usando Gemini puro")'''

new = '''            logger.warning(
                "Nemotron indisponível (%s) — voltando pro Gemini puro.",
                self.ultimo_erro,
            )
            print(f"[DEBUG] Nemotron failed: {self.ultimo_erro}")
            print("  [IA] Nemotron indisponível — usando Gemini puro")'''

if old in content:
    content = content.replace(old, new)
    with open(r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Updated')
else:
    print('Old text not found exactly')
    idx = content.find('Nemotron failed')
    if idx >= 0:
        print('Already has debug')
    else:
        print('No debug found')