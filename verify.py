import py_compile
files = [
    r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py',
    r'C:\Users\carlo\Desktop\B3-bot\config.py',
    r'C:\Users\carlo\Desktop\B3-bot\relatorio_diario.py'
]
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f'{f}: OK')
    except py_compile.PyCompileError as e:
        print(f'{f}: ERROR - {e}')