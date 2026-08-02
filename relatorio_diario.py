import telebot
import config
from b3_swing_analyzer import analisar_ativo
from ia_analise import analisar_com_ia

def enviar_mensagem_telegram(texto):
    """Envia mensagem formatada para o Telegram."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("⚠️ Configuração do Telegram incompleta. Imprimindo no console:")
        print(texto)
        return

    try:
        bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
        # parse_mode="Markdown" permite negrito e itálico
        bot.send_message(config.TELEGRAM_CHAT_ID, texto, parse_mode="Markdown")
        print("✅ Mensagem enviada com sucesso para o Telegram!")
    except Exception as e:
        print(f"❌ Erro ao enviar mensagem: {e}")

def gerar_relatorio():
    """Função principal executada pelo GitHub Actions."""
    print("🚀 Iniciando Robô B3 Swing Analyzer...")
    
    if not config.validar_config():
        print("⛔ Execução cancelada devido a erros de configuração.")
        return

    msg_final = "📊 *Relatório Diário B3*\n"
    msg_final += f"🕒 Gerado em: {__import__('datetime').datetime.now().strftime('%d/%m %H:%M')}\n\n"
    
    ativos_analisados = 0
    
    for ativo in config.WATCHLIST:
        resultado = analisar_ativo(ativo)
        
        if not resultado:
            continue
            
        dados = resultado['dados']
        score = resultado['score']
        ativos_analisados += 1
        
        # Só chama a IA se o score for relevante (evita gasto de API com lixo)
        analise_ia = None
        if score >= 4.5: 
            analise_ia = analisar_com_ia(resultado)
        
        # Monta mensagem do ativo
        emoji_tendencia = "🟢" if dados['tendencia'] == "ALTA" else "🔴" if dados['tendencia'] == "BAIXA" else "⚪"
        
        msg_ativo = f"{emoji_tendencia} *{ativo}* (Score: {score:.1f})\n"
        msg_ativo += f"💰 Preço: R$ {dados['preco']} | Tendência: {dados['tendencia']}\n"
        msg_ativo += f"📉 RSI: {dados['rsi']} | MACD: {'Positivo 📈' if dados['macd'] > dados['macd_signal'] else 'Negativo 📉'}\n"
        
        if analise_ia:
            msg_ativo += f"\n🤖 *IA Insight:*\n"
            msg_ativo += f"🎯 Direção: *{analise_ia.get('direcao', 'NEUTRO')}* ({analise_ia.get('confianca', 0)}/10)\n"
            msg_ativo += f"📝 Padrão: {analise_ia.get('padrao', 'N/A')}\n"
            msg_ativo += f"💡 Visão: _{analise_ia.get('analise', '')}_\n"
            msg_ativo += f"⚠️ Risco: {analise_ia.get('risco', '')}\n"
        else:
            if score < 4.5:
                msg_ativo += "\n⚪ *IA:* Setup fraco, análise ignorada.\n"
            else:
                msg_ativo += "\n⚠️ *IA:* Falha na comunicação.\n"
            
        msg_final += msg_ativo + "\n" + "-"*30 + "\n"

    if ativos_analisados == 0:
        msg_final = "⚠️ Nenhum ativo pôde ser analisado hoje (Erro de dados ou Internet)."

    enviar_mensagem_telegram(msg_final)

if __name__ == "__main__":
    gerar_relatorio()
