with open(r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''if self.NEMOTRON_API_KEY:
            resposta_nemotron = self._call_nemotron(prompt, chart_path)
            if resposta_nemotron:
                self.ultimo_provedor = "nemotron"
                logger.info(
                    "Hybrid IA OK para o ativo: Nemotron (resposta v\u00e1lida) \u2014 regra de consist\u00eancia aplicada"
                )
                return self._validate_response('''

new = '''if self.NEMOTRON_API_KEY:
            print(f"[DEBUG] Calling Nemotron with model: {self.NEMOTRON_MODEL}")
            resposta_nemotron = self._call_nemotron(prompt, chart_path)
            if resposta_nemotron:
                self.ultimo_provedor = "nemotron"
                logger.info(
                    "Hybrid IA OK para o ativo: Nemotron (resposta v\u00e1lida) \u2014 regra de consist\u00eancia aplicada"
                )
                print("[DEBUG] Nemotron responded successfully")
                return self._validate_response('''

if old in content:
    content = content.replace(old, new)
    with open(r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Updated success call')
else:
    print('Old text not found')