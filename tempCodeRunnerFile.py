import os
import pandas as pd
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

load_dotenv()

# --- TOKENLAR ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
EXCEL_FILE = "rezervasyonlar.xlsx"

# --- Excel Dosyası Kontrol ---
if not os.path.exists(EXCEL_FILE):
    df = pd.DataFrame(columns=["kullanici", "tarih", "saat", "durum"])
    df.to_excel(EXCEL_FILE, index=False)

# --- Yardımcı Fonksiyonlar ---
def load_reservations():
    return pd.read_excel(EXCEL_FILE)

def save_reservations(df):
    df.to_excel(EXCEL_FILE, index=False)

def format_reservation(res):
    return f"{res['tarih'].strftime('%Y-%m-%d')} {res['saat']} - {res['durum']}"

# --- Komutlar ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Merhaba! Rezervasyon yapmak için /reserve yazın.\n"
        "Rezervasyonlarınızı görmek için /myreservations yazın."
    )

async def reserve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Rezervasyon yapmak istediğiniz tarihi ve saati yazın (Örn: 2025-10-25 15:00):"
    )
    return

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    # Tarih ve saat ayrımı
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        user = update.message.from_user.username or update.message.from_user.first_name
        df = load_reservations()
        MAX_PERSON_PER_SLOT = 2  # Her slotta maksimum kişi sayısı

        # Çakışma kontrolü (handle_text fonksiyonunda)
        conflict = df[
            (df["tarih"] == dt.date()) & 
            (df["saat"] == dt.strftime("%H:%M")) & 
            (df["durum"]=="aktif")
        ]
        
        # Çakışma kontrolü
        conflict = df[(df["tarih"] == dt.date()) & (df["saat"] == dt.strftime("%H:%M")) & (df["durum"]=="aktif")]
        if not conflict.empty:
            await update.message.reply_text("Maalesef bu tarih ve saat dolu. Lütfen başka bir zaman seçin.")
            return
        

        # Yeni rezervasyon ekle
        df = pd.concat([df, pd.DataFrame([{
            "kullanici": user,
            "tarih": dt.date(),
            "saat": dt.strftime("%H:%M"),
            "durum": "aktif"
        }])], ignore_index=True)
        save_reservations(df)
        await update.message.reply_text(f"Rezervasyonunuz kaydedildi: {dt.strftime('%Y-%m-%d %H:%M')}")
    except ValueError:
        await update.message.reply_text("Tarih ve saat formatı yanlış. Lütfen YYYY-MM-DD HH:MM şeklinde yazın.")

async def my_reservations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username or update.message.from_user.first_name
    df = load_reservations()
    user_res = df[df["kullanici"]==user]
    
    if user_res.empty:
        await update.message.reply_text("Hiç rezervasyonunuz yok.")
        return
    
    # Rezervasyonları göster
    message = "Rezervasyonlarınız:\n"
    for _, row in user_res.iterrows():
        message += f"{format_reservation(row)}\n"
    await update.message.reply_text(message)

async def cancel_reservation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username or update.message.from_user.first_name
    df = load_reservations()
    user_res = df[(df["kullanici"]==user) & (df["durum"]=="aktif")]
    
    if user_res.empty:
        await update.message.reply_text("İptal edilecek rezervasyonunuz yok.")
        return
    
    # Inline keyboard ile iptal seçenekleri
    keyboard = [
        [InlineKeyboardButton(f"{row['tarih']} {row['saat']}", callback_data=str(idx))]
        for idx, row in user_res.iterrows()
    ]
    await update.message.reply_text("İptal etmek istediğiniz rezervasyonu seçin:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    idx = int(query.data)
    df = load_reservations()
    df.at[idx, "durum"] = "iptal"
    save_reservations(df)
    await query.edit_message_text(text="Rezervasyonunuz iptal edildi ✅")

# --- Bot Başlat ---
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reserve", reserve))
    app.add_handler(CommandHandler("myreservations", my_reservations))
    app.add_handler(CommandHandler("cancel", cancel_reservation))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button))
    
    print("Bot çalışıyor...")
    app.run_polling()

if __name__ == "__main__":
    main()
