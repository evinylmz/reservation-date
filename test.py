import os
import logging
import json
import re
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction
import random # Rezervasyon ID'si için
import uuid # Geçici kullanıcı ID'si için (Eğer auth olmasaydı)

# Kütüphaneler
from google import genai
from google.genai import types as genai_types
from google.genai.errors import APIError as GeminiAPIError

# --- GEREKLİ AYARLAR VE LOGLAMA ---

# Token ve Anahtarlarınız (Değerleriniz Koda Yerleştirilmiştir)
TELEGRAM_BOT_TOKEN = "your token"
LLM_API_KEY = "your api key" 
RESTORAN_ADI = "Hafta3 Restoranı"

# Loglama ayarı
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Her kullanıcı için konuşma geçmişini (hafızayı) tutacak yapı
user_conversations = {}

# 💾 REZERVASYON VERİ TABANI SİMÜLASYONU (Hafıza)
# Gerçek uygulamada burası Firestore, PostgreSQL vb. bir veritabanı olmalıdır.
# { 'RZ1234': {'date': '2025-01-01', 'time': '19:00', 'party_size': 4, 'customer_name': 'Ahmet Yılmaz', 'telegram_user_id': 123456}, ... }
RESERVATIONS_DB = {}

# ⚠️ GEMINI İSTEMCİSİ: Anahtar ile başlatılıyor
try:
    gemini_client = genai.Client(api_key=LLM_API_KEY)
except Exception as e:
    logger.error(f"Gemini istemcisi başlatılırken hata oluştu: {e}")
    gemini_client = None

GEMINI_MODEL = "gemini-2.5-flash" 

# --- I. LLM SİSTEM PROMPT'U (GÜNCELLENDİ) ---

def get_system_prompt():
    """LLM'in rolünü, kurallarını ve formatını belirleyen prompt'u döndürür."""
    today_date = datetime.now().strftime('%Y-%m-%d')
    
    prompt = f"""
    Sen, "{RESTORAN_ADI}" için akıllı bir asistan ve rezervasyon yöneticisisin.
    Görevin, iki temel işlemi yönetmek: YENİ REZERVASYON ALMAK veya VAR OLAN REZERVASYONU SORGULAMAK.

    YENİ REZERVASYON İÇİN 4 temel bilgiyi toplamalısın: TARİH, SAAT, KİŞİ SAYISI ve MÜŞTERİ ADI/SOYADI.
    VAR OLAN REZERVASYONU SORGULAMAK İÇİN ise 2 bilgi toplamalısın: REZERVASYON NUMARASI (RZ ile başlar) ve MÜŞTERİ ADI/SOYADI.

    KURALLAR:
    1. YENİ REZERVASYON: Tüm 4 bilgi (tarih, saat, kişi sayısı, ad/soyad) netleştiğinde, HİÇBİR ŞEY YAZMADAN, sadece bu formatta bir JSON döndür:
       {{"intent": "check_availability", "date": "YYYY-MM-DD", "time": "HH:MM", "party_size": N, "customer_name": "Ad Soyad"}}
    2. REZERVASYON SORGULAMA: Kullanıcı "rezervasyonumu öğrenmek istiyorum", "ne zaman rezervasyonum var" gibi bir talepte bulunursa, Rezervasyon No'yu ve Ad/Soyad bilgisini iste. İki bilgi de netleştiğinde, HİÇBİR ŞEY YAZMADAN, sadece bu formatta bir JSON döndür:
       {{"intent": "retrieve_reservation", "reservation_id": "RZxxxx", "customer_name": "Ad Soyad"}}
    3. Bilgiler eksikse, JSON DÖNDÜRME. Eksik olan bilgiyi kibarca iste.
    4. Tarihleri her zaman YYYY-MM-DD formatına, saatleri HH:MM (24 saat formatı) formatına çevir. Bugünün tarihi: {today_date}
    5. Müşteri Adı/Soyadı her zaman *İlk Harfleri Büyük* olacak şekilde temizlenmiş olarak verilmelidir.
    6. Kullanıcı sohbet ederse, kibarca cevap ver ve rezervasyon için yardımcı olabileceğini belirt.
    """
    return prompt.strip()


# --- II. REZERVASYON İŞLEMLERİ (YENİ VE GÜNCELLENMİŞ) ---

async def handle_check_availability(details: dict, update: Update):
    """LLM'den gelen yeni rezervasyon JSON'unu işler ve kaydeder."""
    date = details.get("date")
    time = details.get("time")
    party_size = details.get("party_size")
    customer_name = details.get("customer_name")
    user_id = update.effective_user.id
    
    # Kişi sayısı kontrolü (Simülasyon)
    if party_size > 6:
        return f"{customer_name} için {party_size} kişilik yerimiz maalesef şu an müsait değil. Daha küçük bir grup veya başka bir tarih deneyebilir misiniz?"
    
    # 💾 Rezervasyonu Kaydet
    # Rezervasyon ID'si oluşturma
    reservation_id = "RZ" + str(random.randint(1000, 9999)) 
    masa_adı = "Masa 5 (Pencere Kenarı)" 
    
    reservation_data = {
        "date": date,
        "time": time,
        "party_size": party_size,
        "customer_name": customer_name,
        "masa_adı": masa_adı,
        "telegram_user_id": user_id 
    }
    
    RESERVATIONS_DB[reservation_id] = reservation_data
    logger.info(f"Yeni Rezervasyon Kaydedildi: {reservation_id} - {customer_name}")

    final_message = f"""
Harika, **{customer_name}**!
Rezervasyonunuz (No: **{reservation_id}**) başarıyla oluşturuldu ve sistemimize kaydedildi.

Detaylar:
📅 Tarih: {date}
⏰ Saat: {time}
👥 Kişi Sayısı: {party_size}
📍 Masa: {masa_adı}

Sizi ağırlamak için sabırsızlanıyoruz!
    """
    
    await update.message.reply_html(final_message)
    # Başarılı kayıt sonrası hafızayı temizle
    if user_id in user_conversations:
        del user_conversations[user_id]
    
    return None # Başarılıysa LLM'e geri bildirim gönderme

async def handle_retrieve_reservation(details: dict, update: Update):
    """LLM'den gelen sorgulama JSON'unu işler ve rezervasyonu bulur."""
    reservation_id = details.get("reservation_id", "").upper().strip()
    customer_name = details.get("customer_name", "").strip()
    
    # Veritabanında kontrol et
    reservation = RESERVATIONS_DB.get(reservation_id)
    
    if reservation:
        # Rezervasyon bulundu, isim eşleşmesini kontrol et
        if reservation["customer_name"].lower() == customer_name.lower():
            
            final_message = f"""
**{reservation['customer_name']}** Bey/Hanım, işte **{reservation_id}** numaralı rezervasyonunuzun detayları:

Detaylar:
📅 Tarih: {reservation['date']}
⏰ Saat: {reservation['time']}
👥 Kişi Sayısı: {reservation['party_size']}
📍 Masa: {reservation['masa_adı']}

Sizi bekliyoruz!
            """
            await update.message.reply_html(final_message)
            user_id = update.effective_user.id
            if user_id in user_conversations:
                del user_conversations[user_id]
            return None # Başarılıysa LLM'e geri bildirim gönderme

        else:
            # İsim rezervasyon no ile eşleşmedi
            return f"Üzgünüm, {reservation_id} numaralı rezervasyon, verdiğiniz isim ({customer_name}) ile eşleşmiyor. Lütfen isminizi veya rezervasyon numaranızı tekrar kontrol edin."
    else:
        # Rezervasyon No bulunamadı
        return f"Üzgünüm, **{reservation_id}** numaralı bir rezervasyon kaydı bulamadık. Lütfen numaranızı kontrol edin."


# --- III. TELEGRAM İŞLEYİCİ FONKSİYONLARI ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start komutuna yanıt verir ve hafızayı temizler."""
    user_id = update.effective_user.id
    if user_id in user_conversations:
        del user_conversations[user_id]
    
    # Güncel rezervasyon sayısı
    rez_sayisi = len(RESERVATIONS_DB)
    
    await update.message.reply_html(
        f'Hoş geldiniz! Ben **{RESTORAN_ADI}** için rezervasyon asistanınız. '
        f'Size yardımcı olmaktan mutluluk duyarım. '
        f'Sistemimizde şu anda **{rez_sayisi}** kayıtlı rezervasyon bulunmaktadır.'
        f'\n\n**Yeni bir rezervasyon yapmak** için tarih, saat, kişi sayısı ve ad/soyadınızı belirtin.'
        f'\n**Mevcut rezervasyonunuzu sorgulamak** için ise "Rezervasyonumu sorgula" veya "rezervasyonum ne zaman?" gibi bir soru sorabilirsiniz.'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcının her mesajını işler ve intent'e göre yönlendirir."""
    if not gemini_client:
        await update.message.reply_text("Üzgünüm, Gemini API istemcisi doğru şekilde başlatılamadı.")
        return
        
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Konuşma geçmişini al veya oluştur
    if user_id not in user_conversations:
        initial_system_prompt_content = genai_types.Content(
            role="user", 
            parts=[genai_types.Part(text=get_system_prompt())]
        )
        user_conversations[user_id] = [initial_system_prompt_content] 
        
    # Kullanıcı mesajını geçmişe ekle
    user_conversations[user_id].append(genai_types.Content(role="user", parts=[genai_types.Part(text=user_message)]))
    
    await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.TYPING)
    
    # 2. LLM Çağrısı
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
        await update.message.reply_text("Üzgünüm, Gemini API'ye ulaşılamıyor. Lütfen tekrar deneyin.")
        return
    except Exception as e:
        logger.error(f"Beklenmedik LLM Hatası: {e}")
        await update.message.reply_text("Üzgünüm, bir hata oluştu.")
        return

    # 3. LLM Cevabını İşleme ve Niyete Göre Yönlendirme
    
    # Kod bloğu şeklindeki JSON'u yakala (örnek: ```json { ... } ```)
    json_match = re.search(r'\{.*\}', llm_response_text, re.DOTALL)
    json_text = json_match.group(0) if json_match else llm_response_text

    llm_feedback = None
    if json_text.startswith('{') and json_text.endswith('}'):
        try:
            reservation_details = json.loads(json_text)
            intent = reservation_details.get("intent")
            
            await update.message.reply_html(f"Detaylarınızı kontrol ediyorum ({intent} niyetinde), lütfen bekleyin... ⏳")
            logger.info(f"LLM JSON Çıktısı Aldı - Intent: {intent}")

            if intent == "check_availability":
                llm_feedback = await handle_check_availability(reservation_details, update)
            
            elif intent == "retrieve_reservation":
                llm_feedback = await handle_retrieve_reservation(reservation_details, update)
            
            else:
                llm_feedback = "Tanınmayan bir rezervasyon niyeti ('intent') algılandı. Lütfen sadece rezervasyon oluşturma veya sorgulama amaçlı konuşun."

        except json.JSONDecodeError:
            # Geçersiz JSON ise, LLM'in cevabını normal metin olarak gönder
            await update.message.reply_html(llm_response_text)
            user_conversations[user_id].append(genai_types.Content(role="model", parts=[genai_types.Part(text=llm_response_text)]))
            return
    
    else:
        # LLM eksik bilgi istedi veya sohbet etti (JSON yok)
        await update.message.reply_html(llm_response_text)
        user_conversations[user_id].append(genai_types.Content(role="model", parts=[genai_types.Part(text=llm_response_text)]))
        return

    # 4. İşlem Sonrası Geri Bildirimi Yönetme (LLM_feedback varsa)
    if llm_feedback:
        # Hata/Başarısızlık geri bildirimi geldiyse (llm_feedback not None), LLM'e doğal dilde yanıt üretmesini iste.
        
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
