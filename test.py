import os
import logging
import json
import re
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# Kütüphaneler
from google import genai
from google.genai import types as genai_types
from google.genai.errors import APIError as GeminiAPIError

# --- GEREKLİ AYARLAR VE LOGLAMA ---

# Token ve Anahtarlarınız (Değerleriniz Koda Yerleştirilmiştir)
TELEGRAM_BOT_TOKEN = "your token"
LLM_API_KEY = "your key" 
RESTORAN_ADI = "Hafta3 Restoranı"

# Loglama ayarı
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Her kullanıcı için konuşma geçmişini (hafızayı) tutacak yapı
user_conversations = {}

# ⚠️ GEMINI İSTEMCİSİ: Anahtar ile başlatılıyor
try:
    gemini_client = genai.Client(api_key=LLM_API_KEY)
except Exception as e:
    logger.error(f"Gemini istemcisi başlatılırken hata oluştu: {e}")
    gemini_client = None

GEMINI_MODEL = "gemini-2.5-flash" 

# --- I. LLM SİSTEM PROMPT'U ---

def get_system_prompt():
    """LLM'in rolünü, kurallarını ve formatını belirleyen prompt'u döndürür."""
    today_date = datetime.now().strftime('%Y-%m-%d')
    
    prompt = f"""
    Sen, "{RESTORAN_ADI}" için bir rezervasyon asistanısın.
    Görevin, kullanıcıdan rezervasyon için 3 temel bilgiyi toplamaktır: TARİH, SAAT ve KİŞİ SAYISI.
    Kullanıcıyla doğal bir dille sohbet et.

    KURALLAR:
    1. Tüm bu 3 bilgi (tarih, saat, kişi sayısı) netleştiğinde, başka HİÇBİR ŞEY YAZMADAN, sadece ve sadece şu formatta bir JSON objesi döndür:
       {{"intent": "check_availability", "date": "YYYY-MM-DD", "time": "HH:MM", "party_size": N}}
    2. Eğer bilgiler eksikse (örn: "yarın 3 kişi" dedi ama saat vermedi), JSON DÖNDÜRME. Eksik olan bilgiyi kibarca iste (örn: "Harika, yarın 3 kişi için. Saat kaçta gelmeyi düşünüyorsunuz?").
    3. Tarihleri her zaman YYYY-MM-DD formatına, saatleri HH:MM (24 saat formatı) formatına çevir. Bugünün tarihi: {today_date}
    4. Kullanıcı sohbet ederse ("merhaba", "nasılsın"), kibarca cevap ver ve rezervasyon için yardımcı olabileceğini belirt.
    """
    return prompt.strip()


# --- II. REZERVASYON İŞLEMLERİ (ÖNEMLİ: Gerçek API bağlantısı buraya gelmeli) ---

async def process_reservation_check(details: dict, update: Update):
    """
    LLM'den gelen JSON'u işler, müsaitlik kontrolünü yapar ve sonucu LLM'e geri gönderir.
    Bu kısım sadece simülasyondur.
    """
    try:
        date = details.get("date")
        time = details.get("time")
        party_size = details.get("party_size")
        
        # ⚠️ SİMÜLASYON BAŞLANGICI ⚠️
        if party_size > 6:
            response_to_llm = f"Rezervasyon yapılamadı: {party_size} kişi için müsait masa bulunamadı. Lütfen daha küçük bir grup veya başka bir tarih deneyin."
        else:
            reservation_id = "RZ" + str(hash(date + time + str(party_size)) % 10000)
            masa_adı = "Masa 5 (Pencere Kenarı)" 
            customer_name = update.effective_user.first_name or "Misafir"
            final_message = f"""
Harika, **{customer_name}**!
Rezervasyonunuz (No: **{reservation_id}**) başarıyla oluşturuldu.

Detaylar:
📅 Tarih: {date}
⏰ Saat: {time}
👥 Kişi Sayısı: {party_size}
📍 Masa: {masa_adı}

Sizi ağırlamak için sabırsızlanıyoruz!
            """
            
            await update.message.reply_html(final_message)
            user_id = update.effective_user.id
            if user_id in user_conversations:
                del user_conversations[user_id]
            
            return # Rezervasyon başarılı, LLM'i tekrar çağırmıyoruz

        return response_to_llm # Başarısızlık durumunda LLM'e geri bildirim
        
    except Exception as e:
        logger.error(f"Rezervasyon kontrol hatası: {e}")
        return "Üzgünüm, rezervasyon sistemimizde bir hata oluştu. Lütfen tekrar deneyin."


# --- III. TELEGRAM İŞLEYİCİ FONKSİYONLARI ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start komutuna yanıt verir ve hafızayı temizler."""
    user_id = update.effective_user.id
    if user_id in user_conversations:
        del user_conversations[user_id]
    
    await update.message.reply_text(
        f'Hoş geldiniz! Ben **{RESTORAN_ADI}** için rezervasyon asistanınız. '
        f'Size yardımcı olmaktan mutluluk duyarım. Rezervasyon yapmak istediğiniz tarih, saat ve kişi sayısını belirtir misiniz?'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcının her mesajını işler."""
    if not gemini_client:
        await update.message.reply_text("Üzgünüm, Gemini API istemcisi doğru şekilde başlatılamadı.")
        return
        
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Konuşma geçmişini al veya oluştur
    if user_id not in user_conversations:
        # 🟢 DÜZELTME UYGULANDI: Sistem prompt'u doğru Gemini formatıyla ilk mesaj olarak ekleniyor.
        initial_system_prompt_content = genai_types.Content(
            role="user", 
            parts=[genai_types.Part(text=get_system_prompt())]
        )
        user_conversations[user_id] = [initial_system_prompt_content] 
        
    # Kullanıcı mesajını geçmişe ekle
    user_conversations[user_id].append(genai_types.Content(role="user", parts=[genai_types.Part(text=user_message)]))
    
    await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)
    
    # 2. LLM Çağrısı (Gemini'ye özgü)
    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_conversations[user_id],
            config=genai_types.GenerateContentConfig(
                temperature=0.0
            )
        )
        llm_response_text = response.text.strip()
        
    except GeminiAPIError as e:
        logger.error(f"Gemini API Çağrısı Hatası: {e}")
        await update.message.reply_text("Üzgünüm, Gemini API'ye ulaşılamıyor (Belki günlük limit aşıldı). Lütfen tekrar deneyin.")
        return
    except Exception as e:
        logger.error(f"Beklenmedik LLM Hatası: {e}")
        await update.message.reply_text("Üzgünüm, bir hata oluştu.")
        return

    # 3. LLM Cevabını İşleme
    
    # import re

    # Kod bloğu şeklindeki JSON'u yakala (örnek: ```json { ... } ```)
    json_match = re.search(r'\{.*\}', llm_response_text, re.DOTALL)
    if json_match:
        json_text = json_match.group(0)
    else:
        json_text = llm_response_text

    if json_text.startswith('{') and json_text.endswith('}'):
        await update.message.reply_html("Rezervasyon detaylarınızı kontrol ediyorum, lütfen bekleyin... 🍽️")
        try:
            reservation_details = json.loads(json_text)
            logger.info(f"LLM JSON Çıktısı Aldı: {reservation_details}")
            
            llm_feedback = await process_reservation_check(reservation_details, update)
            
            if llm_feedback:
                 # Hata/Başarısızlık geri bildirimi geldiyse, LLM'e doğal dilde yanıt üretmesini iste.
                
                # Önceki JSON cevabını kaydet (role 'model')
                user_conversations[user_id].append(genai_types.Content(role="model", parts=[genai_types.Part(text=json_text)]))
                
                # Sistemden gelen geri bildirimi 'user' olarak sun
                system_feedback_message = f"Sistemden gelen bilgi: {llm_feedback}. Bu duruma uygun şekilde müşteriye bilgi ver ve yeni seçenek iste."
                user_conversations[user_id].append(genai_types.Content(role="user", parts=[genai_types.Part(text=system_feedback_message)]))
                
                # LLM'i tekrar çağır
                await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)
                final_response_obj = gemini_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=user_conversations[user_id],
                    config=genai_types.GenerateContentConfig(temperature=0.0)
                )
                final_response_text = final_response_obj.text.strip()
                await update.message.reply_html(final_response_text)
                user_conversations[user_id].append(genai_types.Content(role="model", parts=[genai_types.Part(text=final_response_text)]))

        except json.JSONDecodeError:
            # Geçersiz JSON ise, LLM'in cevabını normal metin olarak gönder
            await update.message.reply_html(llm_response_text)
            user_conversations[user_id].append(genai_types.Content(role="model", parts=[genai_types.Part(text=llm_response_text)]))
        
    else:
        # LLM eksik bilgi istedi veya sohbet etti
        await update.message.reply_html(llm_response_text)
        user_conversations[user_id].append(genai_types.Content(role="model", parts=[genai_types.Part(text=llm_response_text)]))


def main():
    """Botu çalıştırır."""
    if not gemini_client:
        print("Gemini istemcisi başlatılamadı. Lütfen LLM_API_KEY değerinizi kontrol edin.")
        return

    # Telegram Uygulamasını Oluşturma
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Komut ve Mesaj İşleyicileri
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Botu başlat
    print(f"🤖 {RESTORAN_ADI} Botu (Gemini) çalışıyor...")
    application.run_polling(poll_interval=3)

if __name__ == '__main__':
    main()
