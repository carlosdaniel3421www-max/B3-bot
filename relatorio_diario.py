import telebot
import config
from b3_swing_analyzer import analisar_ativo
from ia_analise import analisar_com_ia

def enviar_mensagem(texto):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("Configuração do Telegram incompleta. Mensagem não enviada.")
        print(texto)
        return
    try:
        bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
        bot.send_message(config.TELEGRAM_CHAT_ID, texto, parse_mode="Markdown")
        print("Mensagem enviada com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar telegram: {e}")

def gerar_relatorio():
    if not config.validar_config():
        return

    msg_final = "📊 *Relatório Diário B3*\n\n"
    
    for ativo in config.WATCHLIST:
        resultado = analisar_ativo(ativo)
        if not resultado:
            continue
            
        dados = resultado['dados']
        score = resultado['score']
        
        # Chama a IA apenas se o score for relevante (>4)
        analise_ia = None
        if score >= 4:
            analise_ia = analisar_com_ia(resultado)
        
        # Monta mensagem do ativo
        msg_ativo = f"🇧🇷 *{ativo}* (Score: {score:.1f})\n"
        msg_ativo += f"💰 Preço: R$ {dados['preco']} | Tendência: {dados['tendencia']}\n"
        msg_ativo += f"📉 RSI: {dados['rsi']} | MACD: {'Positivo' if dados['macd'] > dados['macd_signal'] else 'Negativo'}\n"
        
        if analise_ia:
            msg_ativo += f"\n🤖 *IA Analysis:*\n"
            msg_ativo += f"🎯 Direção: *{analise_ia.get('direcao', 'NEUTRO')}* ({analise_ia.get('confianca', 0)}/10)\n"
            msg_ativo += f"📝 Padrão: {analise_ia.get('padrao', 'N/A')}\n"
            msg_ativo += f"💡 Visão: {analise_ia.get('analise', '')}\n"
            msg_ativo += f"⚠️ Risco: {analise_ia.get('risco', '')}\n"
        else:
            msg_ativo += "\n⚪ *IA:* Sem sinal claro ou análise skipped.\n"
            
        msg_final += msg_ativo + "\n" + "-"*20 + "\n"

    enviar_mensagem(msg_final)

if __name__ == "__main__":
    gerar_relatorio()
