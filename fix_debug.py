with open(r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = 'Nemotron indispon\u00edvel (%s) \u2014 voltando pro Gemini puro.",\n                self.ultimo_erro,\n            )\n            print("  [IA] Nemotron indispon\u00edvel \u2014 usando Gemini puro")'

new = 'Nemotron indispon\u00edvel (%s) \u2014 voltando pro Gemini puro.",\n                self.ultimo_erro,\n            )\n            print(f"[DEBUG] Nemotron failed: {self.ultimo_erro}")\n            print("  [IA] Nemotron indispon\u00edvel \u2014 usando Gemini puro")'

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