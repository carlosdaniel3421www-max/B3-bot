# -*- coding: utf-8 -*-
import os

base = r'C:\Users\carlo\Desktop\B3-bot'

print('=== Checagem de residuos ===')
for f in ['ia_analise.py', 'fix_conflicts.py', 'relatorio.yml', 'bot_servidor.py', 'relatorio_tarde.py']:
    status = 'EXISTE' if os.path.exists(os.path.join(base, f)) else 'removido'
    print(f'{f}: {status}')

print()
print('=== Workflows ===')
for f in os.listdir(os.path.join(base, '.github', 'workflows')):
    print(' -', f)

print()
print('=== Referencias a CARLOS ===')
termos = ['CARLOS', 'carlos']
for f in sorted(os.listdir(base)):
    if f.endswith('.py') or f.endswith('.yml') or f.endswith('.yaml'):
        p = os.path.join(base, f)
        if os.path.isfile(p):
            try:
                with open(p, 'r', encoding='utf-8', errors='replace') as fh:
                    lines = fh.readlines()
            except Exception:
                continue
            for i, line in enumerate(lines, 1):
                if any(t in line for t in termos):
                    print(f'{f}:{i}: {line.rstrip()}')
