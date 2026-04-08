import asyncio
import requests
import os
from datetime import datetime

import psycopg2
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from analytics import generate_stats
from aiogram.enums import ParseMode

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
CARD_NUMBER = os.getenv("CARD_NUMBER")
PRICE_PER_STAR = int(os.getenv("PRICE_PER_STAR"))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

API_URL = "https://smm.myxvest2.ru/api/v2"

user_lang_cache = {}

# ---- LANGUAGE CHANGER ----
TEXTS = {
    "welcome": {
        "ru": "⭐ Добро пожаловать!",
        "uz": "⭐ Xush kelibsiz!"
    },
    "choose_stars": {
        "ru": "⭐️ Сколько звёзд вы хотите купить?",
        "uz": "⭐️ Nechta yulduz sotib olmoqchisiz?"
    },
    "price": {
        "ru": "💰 Цена",
        "uz": "💰 Narx"
    },
    "min": {
        "ru": "🔹 Минимум: 50 звёзд",
        "uz": "🔹 Minimum: 50 yulduz"
    },
    "use_buttons": {
        "ru": "👇 Используйте кнопки ниже:",
        "uz": "👇 Quyidagi tugmalardan foydalaning:"
    },
    "balance": {
        "ru": "💰 Ваш баланс",
        "uz": "💰 Sizning balansingiz"
    },
    "deposit": {
        "ru": "💳 Пополнение\nВведите сумму (мин 1000 UZS):",
        "uz": "💳 Hisobni to‘ldirish\nSummani kiriting (min 1000 UZS):"
    },
    "history_empty": {
        "ru": "📭 История пуста",
        "uz": "📭 Tarix bo‘sh"
    },
    "history": {
        "ru": " История заказов",
        "uz": " Buyurtmalar tarixi"
    },
    "choose_lang": {
        "ru": "🌐 Выберите язык:",
        "uz": "🌐 Tilni tanlang:"
    },
    "lang_changed": {
        "ru": "✅ Язык изменён",
        "uz": "✅ Til o‘zgartirildi"
    },
    "main_menu": {
        "ru": "🏠 Главное меню",
        "uz": "🏠 Asosiy menyu"
    },
    "not_enough": {
        "ru": "❌ Недостаточно средств",
        "uz": "❌ Mablag‘ yetarli emas"
    },
    "processing": {
        "ru": "⏳ Обрабатываем заказ... Пожалуйста подождите",
        "uz": "⏳ Buyurtma bajarilmoqda... Iltimos kuting"
    },
    "order_success": {
        "ru": "🌟 Заказ успешно выполнен!",
        "uz": "🌟 Buyurtma muvaffaqiyatli bajarildi!"
    },
    "error_order": {
        "ru": "❌ Ошибка при выполнении заказа",
        "uz": "❌ Buyurtmada xatolik yuz berdi"
    },
    "send_admin": {
        "ru": "💬 Напишите нашему админу",
        "uz": "💬 Admin bilan bog‘laning"
    },
    "min_deposit": {
        "ru": "❌ Минимум 1000 UZS",
        "uz": "❌ Minimum 1000 UZS"
    },
    "send_screenshot": {
        "ru": "❌ Отправьте скриншот",
        "uz": "❌ Skrinshot yuboring"
    },
    "check_sent": {
        "ru": "✅ Чек отправлен на проверку",
        "uz": "✅ Chek tekshiruvga yuborildi"
    }
}

# --- FORMAT ---
def format_price(n):
    return f"{n:,}".replace(",", " ")
    
# --- DB ---
conn = psycopg2.connect(DATABASE_URL, sslmode="require")

def get_cursor():
    global conn
    try:
        conn.cursor().execute("SELECT 1")
    except:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    return conn.cursor()

# создаём cursor перед использованием
cur = get_cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    lang TEXT DEFAULT 'ru'
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    username TEXT,
    amount INTEGER,
    price INTEGER,
    order_id TEXT,
    status TEXT,
    date TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS deposits (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    amount INTEGER,
    status TEXT,
    date TEXT,
    screenshot TEXT,
    expire_at TEXT
)
""")

conn.commit()

# --- FUNCTIONS ---
def get_user_balance(user_id):
    cur = get_cursor()
    cur.execute("SELECT balance FROM users WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    if row:
        return row[0]
    else:
        cur.execute("INSERT INTO users (user_id, balance) VALUES (%s, 0)", (user_id,))
        conn.commit()
        return 0

def update_balance(user_id, amount):
    cur = get_cursor()
    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id=%s", (amount, user_id))
    conn.commit()

def buy_stars(username, amount):
    return requests.get(API_URL, params={
        "action": "buyStars",
        "api_key": API_KEY,
        "username": username,
        "amount": amount
    }).json()

def set_user_lang(user_id, lang):
    cur = get_cursor()

    cur.execute(
        "INSERT INTO users (user_id, lang) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET lang = EXCLUDED.lang",
        (user_id, lang)
    )

    conn.commit()

    user_lang_cache[user_id] = lang  # ← ВАЖНО
    
def get_user_lang(user_id):
    if user_id in user_lang_cache:
        return user_lang_cache[user_id]

    cur = get_cursor()
    cur.execute("SELECT lang FROM users WHERE user_id=%s", (user_id,))
    row = cur.fetchone()

    lang = row[0] if row and row[0] else "ru"
    user_lang_cache[user_id] = lang
    return lang
    
def t(user_id, key):
    lang = user_lang_cache.get(user_id)

    if not lang:
        lang = get_user_lang(user_id)

    return TEXTS[key][lang]
    
# --- STATE ---
user_state = {}

# --- KEYBOARDS ---
def main_kb(uid):
    lang = user_lang_cache.get(uid) or get_user_lang(uid)

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⭐ Stars sotib olish" if lang == "uz" else "⭐ Купить Stars")],
            [
                KeyboardButton(text="💳 To‘ldirish" if lang == "uz" else "💳 Пополнить"),
                KeyboardButton(text="💰 Balans" if lang == "uz" else "💰 Баланс")
            ],
            [
                KeyboardButton(text="🌐 Tilni tanlash" if lang == "uz" else "🌐 Выбрать язык")
            ]
        ],
        resize_keyboard=True
    )
    
def stars_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ 50", callback_data="buy_50"),
                InlineKeyboardButton(text="⭐ 75", callback_data="buy_75"),
                InlineKeyboardButton(text="⭐ 100", callback_data="buy_100"),
            ],
            [
                InlineKeyboardButton(text="⭐ 150", callback_data="buy_150"),
                InlineKeyboardButton(text="⭐ 200", callback_data="buy_200"),
                InlineKeyboardButton(text="⭐ 250", callback_data="buy_250"),
            ],
            [
                InlineKeyboardButton(text="⭐ 300", callback_data="buy_300"),
                InlineKeyboardButton(text="⭐ 500", callback_data="buy_500"),
                InlineKeyboardButton(text="⭐ 1000", callback_data="buy_1000"),
            ],
            [
                InlineKeyboardButton(text="⭐ 2000", callback_data="buy_2000"),
                InlineKeyboardButton(text="⭐ 3000", callback_data="buy_3000"),
            ],
            [
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"),
            ],
        ]
    )
    
def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_stars")]
    ])

def admin_kb(deposit_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve_{deposit_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_{deposit_id}")
        ]
    ])

stats_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="24ч", callback_data="stats_1"),
        InlineKeyboardButton(text="7 дней", callback_data="stats_7"),
        InlineKeyboardButton(text="30 дней", callback_data="stats_30"),
    ]
])

def lang_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
            InlineKeyboardButton(text="🇺🇿 O‘zbek", callback_data="lang_uz")
        ]
    ])
    
# --- HANDLERS ---
@dp.message(F.text == "/start")
async def start(msg: types.Message):
    uid = msg.from_user.id

    get_user_balance(uid)
    get_user_lang(uid)  # ← ДОБАВЬ ЭТО

    await msg.answer(t(uid, "welcome"), reply_markup=main_kb(uid))
    
@dp.message(F.text == "/stats")
async def stats_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return

    await msg.answer("📊 Выберите период:", reply_markup=stats_kb)
    
@dp.message(F.text.in_(["💰 Баланс", "💰 Balans"]))
async def balance(msg: types.Message):
    user_balance = get_user_balance(msg.from_user.id)
    await msg.answer(f"{t(msg.from_user.id, 'balance')}: {format_price(user_balance)} UZS")

@dp.message(F.text.in_(["⭐ Купить Stars", "⭐ Stars sotib olish"]))
async def buy(msg: types.Message):
    await msg.answer(
        f"{'✅ Yulduz xaridini tanlang' if get_user_lang(msg.from_user.id)=='uz' else '✅ Выберите покупку звёзд'}\n\n"
        f"{t(msg.from_user.id, 'choose_stars')}\n\n"
        f"{t(msg.from_user.id, 'min')}\n"
        f"{t(msg.from_user.id, 'price')}: {PRICE_PER_STAR} UZS/Star\n\n"
        f"{t(msg.from_user.id, 'use_buttons')}",
        reply_markup=stars_kb()
    )
    user_state[msg.from_user.id] = {"step": "amount"}
    
@dp.message(F.text.in_(["💳 Пополнить", "💳 To‘ldirish"]))
async def deposit(msg: types.Message):
    await msg.answer(t(msg.from_user.id, "deposit"))
    user_state[msg.from_user.id] = {"step": "deposit_amount"}

@dp.message(F.text.in_(["🌐 Выбрать язык", "🌐 Tilni tanlash"]))
async def choose_lang(msg: types.Message):
    await msg.answer(t(msg.from_user.id, "choose_lang"), reply_markup=lang_kb())
    
# --- CALLBACK ---
@dp.callback_query()
async def callbacks(call: types.CallbackQuery):
    uid = call.from_user.id
    
    # --- LANGUAGE ---
    if call.data.startswith("lang_"):
        uid = call.from_user.id
        lang = call.data.split("_")[1]

        set_user_lang(uid, lang)

        await call.message.delete()  # удалить старое сообщение (не обязательно, но красиво)

        await call.message.answer(
            t(uid, "lang_changed"),
            reply_markup=main_kb(uid)  # 👈 ВОТ ЭТО ГЛАВНОЕ
        )

        return
    
    # --- STATS ---
    if call.data.startswith("stats_"):
        if call.from_user.id not in ADMIN_IDS:
            return

        days = int(call.data.split("_")[1])

        # ⏳ анимация загрузки
        await call.message.edit_text("⏳ Загружаем статистику...")

        text = await generate_stats(get_cursor, bot, days)

        # обновляем это же сообщение
        await call.message.edit_text(
            text,
            reply_markup=stats_kb
        )
        return
    
    # --- ПРОВЕРКА АДМИНА ---
    if call.data.startswith(("approve_", "cancel_")):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("❌ У вас нет доступа", show_alert=True)
            return
        
    if call.data == "back_main":
        user_state.pop(uid, None)

        await call.message.delete()
        await call.message.answer(
            t(uid, "main_menu"),
            reply_markup=main_kb(uid)
        )
        return

    if call.data == "back_stars":
        lang = get_user_lang(uid)

        await call.message.edit_text(
            f"{'✅ Yulduz xaridini tanlang' if lang=='uz' else '✅ Выберите покупку звёзд'}\n\n"
            f"{t(uid, 'choose_stars')}\n\n"
            f"{t(uid, 'min')}\n"
            f"{t(uid, 'price')}: {PRICE_PER_STAR} UZS/Star\n\n"
            f"{t(uid, 'use_buttons')}",
            reply_markup=stars_kb()
        )

        user_state[uid] = {"step": "amount"}
        return

    if call.data.startswith("buy_"):
        amount = int(call.data.split("_")[1])

        user_state[uid] = {
            "step": "username",
            "amount": amount
        }

        lang = get_user_lang(uid)

        await call.message.edit_text(
            f"{'⭐ Siz tanladingiz:' if lang=='uz' else '⭐ Вы выбрали:'} {amount} Stars\n"
            f"💰 {'Narxi' if lang=='uz' else 'Стоимость'}: {format_price(amount * PRICE_PER_STAR)} UZS\n"
            f"👤 {'Username kiriting:' if lang=='uz' else 'Введите username получателя:'}",
            reply_markup=back_kb()
        )
        
    # --- ADMIN ACTIONS ---
    if call.data.startswith("approve_"):
        deposit_id = int(call.data.split("_")[1])

        cur = get_cursor()
        cur.execute("SELECT user_id, amount FROM deposits WHERE id=%s", (deposit_id,))
        row = cur.fetchone()

        if row:
            user_id, amount = row

            update_balance(user_id, amount)

            cur = get_cursor()
            cur.execute("UPDATE deposits SET status='success' WHERE id=%s", (deposit_id,))
            conn.commit()

            # получаем username
            user = await bot.get_chat(user_id)
            user_display = f"@{user.username}" if user.username else f"id:{user_id}"

            text = (
                f"✅ Пополнение подтверждено\n\n"
                f"🆔 ID: {deposit_id}\n"
                f"👤 {user_display}\n"
                f"💰 {amount} UZS\n"
                f"👮 Админ: @{call.from_user.username or call.from_user.id}"
            )

            # пользователю
            await bot.send_message(
                user_id,
                f"✅ Баланс пополнен!\n\n"
                f"💰 +{amount} UZS\n"
                f"🆔 ID: {deposit_id}"
            )

            # ❗ reply под фото (вместо нового сообщения)
            await call.message.edit_caption(text)
            
            await call.message.reply(text)


    if call.data.startswith("cancel_"):
        deposit_id = int(call.data.split("_")[1])

        cur = get_cursor()
        cur.execute("SELECT user_id, amount FROM deposits WHERE id=%s", (deposit_id,))
        row = cur.fetchone()

        if row:
            user_id, amount = row

            cur = get_cursor()
            cur.execute("UPDATE deposits SET status='canceled' WHERE id=%s", (deposit_id,))
            conn.commit()

            # получаем username
            user = await bot.get_chat(user_id)
            user_display = f"@{user.username}" if user.username else f"id:{user_id}"

            text = (
                f"❌ Пополнение отклонено\n\n"
                f"🆔 ID: {deposit_id}\n"
                f"👤 {user_display}\n"
                f"💰 {amount} UZS\n"
                f"👮 Админ: @{call.from_user.username or call.from_user.id}"
            )

            # пользователю
            await bot.send_message(
                user_id,
                f"❌ Платёж отклонён\n\n"
                f"🆔 ID: {deposit_id}\n"
                f"💡 Проверьте чек или свяжитесь с админом"
            )

            # ❗ reply под фото
            await call.message.edit_caption(text)
            
            await call.message.reply(text)
            
# --- ORDER PROCESS ---
import random
import string

def generate_order_id():
    return "ST-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


async def process_order(uid, username, amount, msg):
    total_price = amount * PRICE_PER_STAR

    balance = get_user_balance(uid)
    if balance < total_price:
        await msg.answer(t(uid, "not_enough"))
        return

    update_balance(uid, -total_price)

    processing_msg = await msg.answer(t(uid, "processing"))
    
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, buy_stars, username, amount)

    if res["success"]:
        order_id = generate_order_id()

        cur = get_cursor()
        cur.execute(
            "INSERT INTO orders (user_id, username, amount, price, order_id, status, date) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (uid, username, amount, total_price, order_id, "success", datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        conn.commit()

        await asyncio.sleep(4)

        lang = get_user_lang(uid)

        text = (
            f"{'🌟 Buyurtma muvaffaqiyatli bajarildi!' if lang=='uz' else '🌟 Заказ успешно выполнен!'}\n\n"
            f"🆔 {'Buyurtma' if lang=='uz' else 'Заказ'}: #{order_id}\n"
            f"👤 {'Qabul qiluvchi' if lang=='uz' else 'Получатель'}: @{username}\n"
            f"⭐ {'Soni' if lang=='uz' else 'Количество'}: {amount} Stars\n"
            f"💰 {'To‘lov' if lang=='uz' else 'Оплата'}: {total_price} UZS\n\n"
            f"{'✅ Yulduzlar yuborildi!' if lang=='uz' else '✅ Звезды успешно отправлены!'}\n"
            f"{'💎 Rahmat!' if lang=='uz' else '💎 Спасибо за покупку!'}"
        )
        await processing_msg.edit_text(text)

        # --- ЛОГ В ГРУППУ ---
        user_username = msg.from_user.username
        user_display = f"@{user_username}" if user_username else f"id:{uid}"

        await bot.send_message(
            ADMIN_GROUP_ID,
            f"⭐ Приобретение звёзд!\n\n"
            f"🧾 Заказ: #{order_id}\n"
            f"👤 Пользователь: {user_display}\n"
            f"⭐ Кол-во: {amount}\n"
            f"💰 Сумма: {total_price} UZS"
        )
    else:
        update_balance(uid, total_price)

        await processing_msg.edit_text(
            f"{t(uid, 'error_order')}\n"
            f"{t(uid, 'send_admin')}: @your_admin_username"
        )
        
# --- EXPIRE ---
async def expire_payment(deposit_id, user_id):
    await asyncio.sleep(600)

    cur = get_cursor()
    cur.execute("SELECT status FROM deposits WHERE id=%s", (deposit_id,))
    row = cur.fetchone()

    # ❗ ВАЖНО: проверяем что ещё не отменён и не подтверждён
    if row and row[0] == "waiting":
        cur = get_cursor()
        cur.execute("UPDATE deposits SET status='expired' WHERE id=%s", (deposit_id,))
        conn.commit()

        lang = get_user_lang(user_id)
        await bot.send_message(
            user_id,
            f"❌ {'To‘lov bekor qilindi (vaqt tugadi)' if lang=='uz' else 'Платёж отменён (время вышло)'} #{deposit_id}"
        )
        
# --- PROCESS ---
@dp.message()
async def process(msg: types.Message):
    uid = msg.from_user.id

    if uid in user_state:
        state = user_state[uid]

        if state["step"] == "username":
            username = msg.text.replace("@", "")
            amount = state["amount"]

            asyncio.create_task(process_order(uid, username, amount, msg))
            user_state.pop(uid, None)

        elif state["step"] == "deposit_amount":
            amount = int(msg.text)

            if amount < 1000:
                await msg.answer(t(uid, "min_deposit"))
                return

            expire_time = datetime.now().timestamp() + 600

            cur = get_cursor()
            cur.execute(
                "INSERT INTO deposits (user_id, amount, status, date, expire_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (uid, amount, "waiting", datetime.now().strftime("%Y-%m-%d %H:%M"), str(expire_time))
            )
            deposit_id = cur.fetchone()[0]
            conn.commit()

            lang = get_user_lang(uid)

            await msg.answer(
                f"{'✅ To‘lov qabul qilindi!' if lang=='uz' else '✅ Сумма платежа принята!'}\n\n"
                f"🆔 ID: {deposit_id}\n"
                f"💵 {'Summa' if lang=='uz' else 'Сумма'}: {format_price(amount)}\n"
                f"💳 {'To‘lov uchun' if lang=='uz' else 'Для оплаты'}: <code>{CARD_NUMBER}</code>\n\n"

                f"📸 <b>{'To‘lovdan so‘ng chek yuboring' if lang=='uz' else 'После оплаты отправьте сюда чек (скриншот)'}</b>\n\n"

                f"<blockquote>{'♻️ To‘lov tekshiriladi va balansga qo‘shiladi' if lang=='uz' else '♻️ После совершения платежа средства будут рассмотрены админами и зачислены на ваш счет.'}</blockquote>\n\u200b\n"
                f"<blockquote>{'⏰ 10 daqiqa ichida to‘lov bo‘lmasa bekor qilinadi' if lang=='uz' else '⏰ Если платеж не поступит в течение 10 минут, он будет отменен.'}</blockquote>",

                parse_mode="HTML"
            )
            
            user_state[uid] = {"step": "await_screenshot", "deposit_id": deposit_id}

            asyncio.create_task(expire_payment(deposit_id, uid))

        elif state["step"] == "await_screenshot":
            if not msg.photo:
                await msg.answer(t(uid, "send_screenshot"))
                return

            deposit_id = state["deposit_id"]
            file_id = msg.photo[-1].file_id

            cur = get_cursor()
            cur.execute(
                "UPDATE deposits SET screenshot=%s, status='pending' WHERE id=%s",
                (file_id, deposit_id)
            )
            conn.commit()

            await msg.answer(t(uid, "check_sent"))

            cur = get_cursor()
            cur.execute("SELECT amount FROM deposits WHERE id=%s", (deposit_id,))
            amount = cur.fetchone()[0]
            
            user_username = msg.from_user.username
            user_display = f"@{user_username}" if user_username else f"id:{uid}"

            await bot.send_photo(
                ADMIN_GROUP_ID,
                photo=file_id,
                caption=(
                    f"💳 Новый платёж\n"
                    f"🆔 ID: {deposit_id}\n"
                    f"👤 {user_display}\n"
                    f"💰 {amount} UZS"
                ),
                reply_markup=admin_kb(deposit_id)
            )

            user_state.pop(uid, None)
            
# --- RUN ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
