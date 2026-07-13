import asyncio
import requests
import os
import logging
import random
import string
from datetime import datetime
from aiohttp import web

from aiogram import Bot, Dispatcher, types, F
from aiogram import BaseMiddleware
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from aiogram.enums import ParseMode

from database import execute, init_pool, init_tables
from analytics import generate_stats
from profile_module import register_profile
from mailer import send_receipt_email
from broadcast import register_broadcast

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
CARD_NUMBER = os.getenv("CARD_NUMBER")
PRICE_PER_STAR = int(os.getenv("PRICE_PER_STAR"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

API_URL = "https://smm.myxvest2.ru/api/v2"

user_lang_cache = {}
user_last_action = {}
SPAM_DELAY = 0.3

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
    "enter_number": {
        "ru": "❌ Введите число",
        "uz": "❌ Raqam kiriting"
    },
    "check_sent": {
        "ru": "✅ Чек отправлен на проверку",
        "uz": "✅ Chek tekshiruvga yuborildi"
    }
}

def format_price(n):
    return f"{n:,}".replace(",", " ")

async def get_user_balance(user_id):
    row = await execute(
        "SELECT balance FROM users WHERE user_id=$1",
        user_id,
        fetchone=True
    )
    if row:
        return row['balance']
    await execute("INSERT INTO users (user_id, balance) VALUES ($1, 0)", user_id)
    return 0

async def update_balance(user_id, amount):
    await execute(
        "UPDATE users SET balance = balance + $1 WHERE user_id=$2",
        amount, user_id
    )

def buy_stars_sync(username, amount):
    return requests.get(API_URL, params={
        "action": "buyStars",
        "api_key": API_KEY,
        "username": username,
        "amount": amount
    }).json()

async def set_user_lang(user_id, lang):
    await execute(
        "INSERT INTO users (user_id, lang) VALUES ($1, $2) "
        "ON CONFLICT (user_id) DO UPDATE SET lang = EXCLUDED.lang",
        user_id, lang
    )
    user_lang_cache[user_id] = lang

async def get_user_lang(user_id):
    if user_id in user_lang_cache:
        return user_lang_cache[user_id]
    row = await execute(
        "SELECT lang FROM users WHERE user_id=$1",
        user_id,
        fetchone=True
    )
    lang = row['lang'] if row else "ru"
    user_lang_cache[user_id] = lang
    return lang

def t(user_id, key):
    lang = user_lang_cache.get(user_id, "ru")
    return TEXTS[key][lang]

def is_spamming(uid):
    now = asyncio.get_event_loop().time()
    last = user_last_action.get(uid)
    if last and (now - last < SPAM_DELAY):
        return True
    user_last_action[uid] = now
    return False

class AntiSpamMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if hasattr(event, "from_user"):
            uid = event.from_user.id
            if is_spamming(uid):
                if hasattr(event, "answer"):
                    await event.answer("⏳ Подождите...")
                return
        return await handler(event, data)

dp.message.middleware(AntiSpamMiddleware())
dp.callback_query.middleware(AntiSpamMiddleware())

user_state = {}

register_broadcast(dp, bot, ADMIN_IDS, execute)
register_profile(dp, execute, get_user_balance, format_price, user_state)

def main_kb(uid):
    lang = user_lang_cache.get(uid, "ru")
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="⭐ Stars sotib olish" if lang == "uz" else "⭐ Купить Stars"),
                KeyboardButton(text="💳 To‘ldirish" if lang == "uz" else "💳 Пополнить")
            ],
            [
                KeyboardButton(text="💰 Balans" if lang == "uz" else "💰 Баланс"),
                KeyboardButton(text="👤 Profil" if lang == "uz" else "👤 Профиль")
            ],
            [
                KeyboardButton(text="❓ Yordam" if lang == "uz" else "❓ Помощь"),
                KeyboardButton(text="🌐 Tilni tanlash" if lang == "uz" else "🌐 Выбрать язык")
            ]
        ],
        resize_keyboard=True
    )

def stars_kb(uid):
    lang = user_lang_cache.get(uid, "ru")
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
                InlineKeyboardButton(
                    text="🔙 Orqaga" if lang == "uz" else "🔙 Назад",
                    callback_data="back_main"
                ),
            ],
        ]
    )

def back_kb(uid):
    lang = user_lang_cache.get(uid, "ru")
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔙 Orqaga" if lang == "uz" else "🔙 Назад",
                callback_data="back_stars"
            )
        ]
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

@dp.message(F.text == "/start")
async def start(msg: types.Message):
    uid = msg.from_user.id
    user_state.pop(uid, None)
    if uid not in user_lang_cache:
        user_lang_cache[uid] = "ru"
    await msg.answer(t(uid, "welcome"), reply_markup=main_kb(uid))

@dp.message(F.text == "/stats")
async def stats_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    await msg.answer("📊 Выберите период:", reply_markup=stats_kb)

@dp.message(F.text.in_(["💰 Баланс", "💰 Balans"]))
async def balance(msg: types.Message):
    uid = msg.from_user.id
    user_state.pop(uid, None)
    user_balance = await get_user_balance(uid)
    await msg.answer(f"{t(msg.from_user.id, 'balance')}: {format_price(user_balance)} UZS")

@dp.message(F.text.in_(["⭐ Купить Stars", "⭐ Stars sotib olish"]))
async def buy(msg: types.Message):
    uid = msg.from_user.id
    user_state.pop(uid, None)
    lang = user_lang_cache.get(uid, "ru")
    await msg.answer(
        f"{'✅ Yulduz xaridini tanlang' if lang=='uz' else '✅ Выберите покупку звёзд'}\n\n"
        f"{t(uid, 'choose_stars')}\n\n"
        f"{t(uid, 'min')}\n"
        f"{t(uid, 'price')}: {PRICE_PER_STAR} UZS/Star\n\n"
        f"{t(uid, 'use_buttons')}",
        reply_markup=stars_kb(uid)
    )
    user_state[uid] = {"step": "amount"}

@dp.message(F.text.in_(["💳 Пополнить", "💳 To‘ldirish"]))
async def deposit(msg: types.Message):
    uid = msg.from_user.id
    user_state.pop(uid, None)
    row = await execute(
        """
        SELECT id FROM deposits 
        WHERE user_id=$1 
        AND status IN ('waiting', 'pending')
        ORDER BY id DESC LIMIT 1
        """,
        uid,
        fetchone=True
    )
    lang = user_lang_cache.get(uid, "ru")
    if row:
        deposit_id = row['id']
        user_state[uid] = {"step": "await_screenshot", "deposit_id": deposit_id}
        await msg.answer(
            "📸 Sizda faol to‘lov bor — chek yuboring"
            if lang == "uz"
            else "📸 У вас уже есть активный платёж — отправьте чек"
        )
        return
    user_state.pop(uid, None)
    await msg.answer(t(uid, "deposit"))
    user_state[uid] = {"step": "deposit_amount"}

@dp.message(F.text.in_(["🌐 Выбрать язык", "🌐 Tilni tanlash"]))
async def choose_lang(msg: types.Message):
    uid = msg.from_user.id
    user_state.pop(uid, None)
    await msg.answer(t(uid, "choose_lang"), reply_markup=lang_kb())

@dp.message(F.text.in_(["❓ Помощь", "❓ Yordam"]))
async def help_menu(msg: types.Message):
    lang = user_lang_cache.get(msg.from_user.id, "ru")
    if lang == "uz":
        text = (
            "❓ Yordam\n\n"
            "⭐ Ushbu bot orqali Telegram Stars sotib olishingiz mumkin.\n\n"
            "💳 Balansni to‘ldiring va bir necha soniyada yulduzlarni qabul qiling.\n\n"
            "📢 Kanal: @premstars77\n"
            "👨‍💻 Qo‘llab-quvvatlash: @premstars_support\n\n"
            "💎 Tez, qulay va xavfsiz."
        )
    else:
        text = (
            "❓ Помощь\n\n"
            "⭐ Через этого бота вы можете быстро покупать Telegram Stars.\n\n"
            "💳 Пополните баланс и получите звёзды за несколько секунд.\n\n"
            "📢 Канал: @premstars77\n"
            "👨‍💻 Поддержка: @premstars_support\n\n"
            "💎 Быстро, удобно и безопасно."
        )
    await msg.answer(text)

@dp.callback_query()
async def callbacks(call: types.CallbackQuery):
    uid = call.from_user.id
    
    if call.data.startswith("lang_"):
        lang = call.data.split("_")[1]
        await set_user_lang(uid, lang)
        await call.message.delete()
        await call.message.answer(t(uid, "lang_changed"), reply_markup=main_kb(uid))
        return
    
    if call.data.startswith("stats_"):
        if call.from_user.id not in ADMIN_IDS:
            return
        days = int(call.data.split("_")[1])
        await call.message.edit_text("⏳ Загружаем статистику...")
        text = await generate_stats(execute, bot, days)
        await call.message.edit_text(text, reply_markup=stats_kb)
        return
    
    if call.data.startswith(("approve_", "cancel_")):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("❌ У вас нет доступа", show_alert=True)
            return
        
    if call.data == "back_main":
        user_state.pop(uid, None)
        await call.message.delete()
        await call.message.answer(t(uid, "main_menu"), reply_markup=main_kb(uid))
        return

    if call.data == "back_stars":
        lang = user_lang_cache.get(uid, "ru")
        await call.message.edit_text(
            f"{'✅ Yulduz xaridini tanlang' if lang=='uz' else '✅ Выберите покупку звёзд'}\n\n"
            f"{t(uid, 'choose_stars')}\n\n"
            f"{t(uid, 'min')}\n"
            f"{t(uid, 'price')}: {PRICE_PER_STAR} UZS/Star\n\n"
            f"{t(uid, 'use_buttons')}",
            reply_markup=stars_kb(uid)
        )
        user_state[uid] = {"step": "amount"}
        return

    if call.data.startswith("buy_"):
        amount = int(call.data.split("_")[1])
        user_state[uid] = {"step": "username", "amount": amount}
        lang = user_lang_cache.get(uid, "ru")
        await call.message.edit_text(
            f"{'⭐ Siz tanladingiz:' if lang=='uz' else '⭐ Вы выбрали:'} {amount} Stars\n"
            f"💰 {'Narxi' if lang=='uz' else 'Стоимость'}: {format_price(amount * PRICE_PER_STAR)} UZS\n"
            f"👤 {'Username kiriting:' if lang=='uz' else 'Введите username получателя:'}",
            reply_markup=back_kb(uid)
        )
        
    if call.data.startswith("approve_"):
        deposit_id = int(call.data.split("_")[1])
        row = await execute(
            "SELECT user_id, amount FROM deposits WHERE id=$1",
            deposit_id,
            fetchone=True
        )
        if row:
            user_id = row['user_id']
            amount = row['amount']
            await update_balance(user_id, amount)
            await execute("UPDATE deposits SET status='success' WHERE id=$1", deposit_id)
            user = await bot.get_chat(user_id)
            user_display = f"@{user.username}" if user.username else f"id:{user_id}"
            text = (
                f"✅ Пополнение подтверждено\n\n"
                f"🆔 ID: {deposit_id}\n"
                f"👤 {user_display}\n"
                f"💰 {amount} UZS\n"
                f"👮 Админ: @{call.from_user.username or call.from_user.id}"
            )
            lang = user_lang_cache.get(user_id, "ru")
            await bot.send_message(
                user_id,
                f"✅ {'Balans to‘ldirildi!' if lang == 'uz' else 'Баланс пополнен!'}\n\n"
                f"💰 +{amount} UZS\n"
                f"🆔 ID: {deposit_id}"
            )
            await call.message.edit_caption(text)
            await call.message.reply(text)

    if call.data.startswith("cancel_"):
        deposit_id = int(call.data.split("_")[1])
        row = await execute(
            "SELECT user_id, amount FROM deposits WHERE id=$1",
            deposit_id,
            fetchone=True
        )
        if row:
            user_id = row['user_id']
            amount = row['amount']
            await execute("UPDATE deposits SET status='canceled' WHERE id=$1", deposit_id)
            user = await bot.get_chat(user_id)
            user_display = f"@{user.username}" if user.username else f"id:{user_id}"
            text = (
                f"❌ Пополнение отклонено\n\n"
                f"🆔 ID: {deposit_id}\n"
                f"👤 {user_display}\n"
                f"💰 {amount} UZS\n"
                f"👮 Админ: @{call.from_user.username or call.from_user.id}"
            )
            lang = user_lang_cache.get(user_id, "ru")
            await bot.send_message(
                user_id,
                f"❌ {'To‘lov rad etildi' if lang == 'uz' else 'Платёж отклонён'}\n\n"
                f"🆔 ID: {deposit_id}\n"
                f"💡 {'Chekni tekshiring yoki admin bilan bog‘laning' if lang == 'uz' else 'Проверьте чек или свяжитесь с админом'}"
            )
            await call.message.edit_caption(text)
            await call.message.reply(text)

def generate_order_id():
    return "ST-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

async def process_order(uid, username, amount, msg):
    total_price = amount * PRICE_PER_STAR
    balance = await get_user_balance(uid)
    if balance < total_price:
        await msg.answer(t(uid, "not_enough"))
        return
    await update_balance(uid, -total_price)
    processing_msg = await msg.answer(t(uid, "processing"))
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, buy_stars_sync, username, amount)
        if not isinstance(res, dict) or not res.get("success"):
            raise Exception(f"API вернул ошибку: {res}")
    except Exception as e:
        logging.error(f"API ERROR: {e}")
        await update_balance(uid, total_price)
        await processing_msg.edit_text(
            f"{t(uid, 'error_order')}\n"
            f"{t(uid, 'send_admin')}: @premstars_support"
        )
        return
    if res["success"]:
        order_id = generate_order_id()
        row = await execute(
            "SELECT email,email_verified FROM users WHERE user_id=$1",
            uid,
            fetchone=True
        )
        if row and row['email']:
            try:
                send_receipt_email(row['email'], order_id, username, amount, total_price)
            except Exception as e:
                print("EMAIL ERROR:", e)
        await execute(
            "INSERT INTO orders (user_id, username, amount, price, order_id, status, date) VALUES ($1,$2,$3,$4,$5,$6,$7)",
            uid, username, amount, total_price, order_id, "success", datetime.now().strftime("%Y-%m-%d %H:%M")
        )
        await asyncio.sleep(4)
        lang = user_lang_cache.get(uid, "ru")
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
        await update_balance(uid, total_price)
        await processing_msg.edit_text(
            f"{t(uid, 'error_order')}\n"
            f"{t(uid, 'send_admin')}: @your_admin_username"
        )

async def expire_payment(deposit_id, user_id):
    await asyncio.sleep(600)
    row = await execute(
        "SELECT status FROM deposits WHERE id=$1",
        deposit_id,
        fetchone=True
    )
    if row and row['status'] == "waiting":
        await execute("UPDATE deposits SET status='expired' WHERE id=$1", deposit_id)
        lang = user_lang_cache.get(user_id, "ru")
        await bot.send_message(
            user_id,
            f"❌ {'To‘lov bekor qilindi (vaqt tugadi)' if lang=='uz' else 'Платёж отменён (время вышло)'} #{deposit_id}"
        )

@dp.message()
async def process(msg: types.Message):
    uid = msg.from_user.id
    if uid in user_state:
        state = user_state[uid]
        if state["step"] == "email_input":
            lang = user_lang_cache.get(uid, "ru")
            email = msg.text.strip()
            await execute(
                "UPDATE users SET email=$1, email_verified=TRUE WHERE user_id=$2",
                email, uid
            )
            try:
                await bot.delete_message(msg.chat.id, state["prompt_msg_id"])
            except:
                pass
            try:
                await msg.delete()
            except:
                pass
            await msg.answer(
                f"✅ Email ulandi:\n{email}"
                if lang == "uz"
                else f"✅ Email подключён:\n{email}"
            )
            user_state.pop(uid, None)
            return
        if state["step"] == "username":
            username = msg.text.replace("@", "")
            amount = state["amount"]
            asyncio.create_task(process_order(uid, username, amount, msg))
            user_state.pop(uid, None)
        elif state["step"] == "deposit_amount":
            if not msg.text or not msg.text.isdigit():
                await msg.answer(t(uid, "enter_number"))
                return
            amount = int(msg.text)
            if amount < 1000:
                await msg.answer(t(uid, "min_deposit"))
                return
            expire_time = datetime.now().timestamp() + 600
            row = await execute(
                "INSERT INTO deposits (user_id, amount, status, date, expire_at) VALUES ($1,$2,$3,$4,$5) RETURNING id",
                uid, amount, "waiting", datetime.now().strftime("%Y-%m-%d %H:%M"), str(expire_time),
                fetchone=True
            )
            deposit_id = row['id']
            lang = user_lang_cache.get(uid, "ru")
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
            deposit_id = state["deposit_id"]
            row = await execute(
                "SELECT status FROM deposits WHERE id=$1",
                deposit_id,
                fetchone=True
            )
            if not row or row['status'] != "waiting":
                return
            if not msg.photo:
                await msg.answer(t(uid, "send_screenshot"))
                return
            file_id = msg.photo[-1].file_id
            await execute(
                "UPDATE deposits SET screenshot=$1, status='pending' WHERE id=$2",
                file_id, deposit_id
            )
            await msg.answer(t(uid, "check_sent"))
            row = await execute(
                "SELECT amount FROM deposits WHERE id=$1",
                deposit_id,
                fetchone=True
            )
            amount = row['amount']
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

async def handle(request):
    return web.Response(text="OK")

async def start_web():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await init_pool()
    await init_tables()
    asyncio.create_task(start_web())
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
