with open(r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

idx = content.find('Nemotron indispon\u00edvel')
if idx >= 0:
    end_idx = content.find('\n\n        for attempt', idx)
    if end_idx == -1:
        end_idx = content.find('\n\n        for attempt in', idx)
    
    old_text = content[idx:end_idx]
    print(f'Found old text (len={len(old_text)})')
    print(repr(old_text))
    
    new_text = old_text.replace(
        'print("  [IA] Nemotron indispon\u00edvel \u2014 usando Gemini puro")',
        'print(f"[DEBUG] Nemotron failed: {self.ultimo_erro}")\n            print("  [IA] Nemotron indispon\u00edvel \u2014 usando Gemini puro")'
    )
    
    content = content[:idx] + new_text + content[end_idx:]
    
    with open(r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Updated successfully')
else:
    print('Not found')