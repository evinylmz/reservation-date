import os
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- TOKENLAR ---
# ⚠️ Güvenlik uyarısı: Gerçek projede bu değerleri doğrudan yazma!
# Test için buraya geçici olarak ekledik.
TELEGRAM_TOKEN = "8362034436:AAF8_nuPVDKKs9XXC9WFe5zHcf88qLO9U1c"
OPENROUTER_API_KEY = "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"

if not TELEGRAM_TOKEN:
    raise ValueError("Lütfen TELEGRAM_TOKEN ortam değişkenini ayarlayın.")
if not OPENROUTER_API_KEY:
    raise ValueError("Lütfen OPENROUTER_API_KEY ortam değişkenini ayarlayın.")

# --- LLM İstemcisini (Client) Kurma ---
client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=OPENROUTER_API_KEY,
)

# --- LLM'e Soru Soran Fonksiyon ---
def get_llm_response(user_message_content):
    try:
        completion = client.chat.completions.create(
            model="deepcogito/cogito-v2-preview-llama-405b",
            messages=[{"role": "user", "content": user_message_content}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"LLM'den cevap alınırken hata oluştu: {e}")
        return "Üzgünüm, şu anda bir sorunla karşılaştım. Lütfen daha sonra tekrar deneyin."

# --- Telegram Mesajlarını İşleyen Fonksiyon ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    print(f"Kullanıcıdan gelen mesaj: {user_text}")
    llm_answer = get_llm_response(user_text)
    await update.message.reply_text(llm_answer)

# --- Bot'u Başlatan Ana Fonksiyon ---
def main():
    print("Bot başlatılıyor...")
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    application.add_handler(message_handler)
    print("Bot çalışıyor. Mesaj bekleniyor...")
    application.run_polling()

if __name__ == '__main__':
    main()
