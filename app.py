import asyncio
import requests
import os
from datetime import datetime

import psycopg2
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

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
    balance INTEGER DEFAULT 0
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

# --- STATE ---
user_state = {}

# --- KEYBOARDS ---
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⭐ Купить Stars")],
        [KeyboardButton(text="💳 Пополнить"), KeyboardButton(text="💰 Баланс")],
        [KeyboardButton(text="📜 История")]
    ],
    resize_keyboard=True
)

def stars_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 50", callback_data="buy_50"),
         InlineKeyboardButton(text="⭐ 100", callback_data="buy_100")],
        [InlineKeyboardButton(text="⭐ 200", callback_data="buy_200"),
         InlineKeyboardButton(text="⭐ 500", callback_data="buy_500")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ])

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

# --- HANDLERS ---
@dp.message(F.text == "/start")
async def start(msg: types.Message):
    get_user_balance(msg.from_user.id)
    await msg.answer("⭐ Добро пожаловать!", reply_markup=main_kb)

@dp.message(F.text == "💰 Баланс")
async def balance(msg: types.Message):
    user_balance = get_user_balance(msg.from_user.id)
    await msg.answer(f"💰 Ваш баланс: {user_balance} UZS")

@dp.message(F.text == "⭐ Купить Stars")
async def buy(msg: types.Message):
    await msg.answer(
        f"💰 Цена: {PRICE_PER_STAR} UZS / ⭐\nВыберите количество:",
        reply_markup=stars_kb()
    )
    user_state[msg.from_user.id] = {"step": "amount"}

@dp.message(F.text == "💳 Пополнить")
async def deposit(msg: types.Message):
    await msg.answer("💳 Пополнение\nВведите сумму (мин 1000 UZS):")
    user_state[msg.from_user.id] = {"step": "deposit_amount"}

@dp.message(F.text == "📜 История")
async def history(msg: types.Message):
    cur = get_cursor()
    cur.execute("SELECT username, amount, price, date FROM orders WHERE user_id=%s ORDER BY id DESC LIMIT 5", (msg.from_user.id,))
    rows = cur.fetchall()

    if not rows:
        await msg.answer("📭 История пуста")
        return

    text = "📜 История заказов:\n\n"
    for r in rows:
        text += f"👤 {r[0]} | ⭐ {r[1]} | 💰 {r[2]} UZS\n🕒 {r[3]}\n\n"

    await msg.answer(text)
    
    # --- ПРОВЕРКА АДМИНА ---
    if call.data.startswith(("approve_", "cancel_")):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("❌ У вас нет доступа", show_alert=True)
            return
        
# --- CALLBACK ---
@dp.callback_query()
async def callbacks(call: types.CallbackQuery):
    uid = call.from_user.id

    if call.data == "back_main":
        user_state.pop(uid, None)
        await call.message.answer("Главное меню", reply_markup=main_kb)
        return

    if call.data == "back_stars":
        await call.message.edit_text(
            f"💰 Цена: {PRICE_PER_STAR} UZS / ⭐\nВыберите количество:",
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

        await call.message.edit_text(
            f"⭐ {amount} Stars\n"
            f"💰 {amount * PRICE_PER_STAR} UZS\n\n"
            f"Введите username:",
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
        await msg.answer("❌ Недостаточно средств")
        return

    update_balance(uid, -total_price)

    processing_msg = await msg.answer("⏳ Обрабатываем заказ... Пожалуйста подождите")

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

        text = (
            "🌟 <b>Заказ успешно выполнен!</b>\n\n"
            f"<b>🆔 Заказ:</b> <code>#{order_id}</code>\n"
            f"<b>👤 Получатель:</b> @{username}\n"
            f"<b>⭐ Количество:</b> {amount} Stars\n"
            f"<b>💰 Оплата:</b> {total_price} UZS\n\n"
            "✅ <b>Звезды успешно отправлены!</b>\n"
            "💎 Спасибо за покупку!"
        )
        await processing_msg.edit_text(text)

        # --- ЛОГ В ГРУППУ ---
        user_username = msg.from_user.username
        user_display = f"@{user_username}" if user_username else f"id:{uid}"

        await bot.send_message(
            ADMIN_GROUP_ID,
            f"🧾 #{order_id} | {user_display} | ⭐ {amount} | 💰 {total_price} UZS"
        )
    else:
        update_balance(uid, total_price)

        await processing_msg.edit_text(
            "❌ Ошибка при выполнении заказа\n"
            "💬 Напишите нашему админу: @your_admin_username"
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

        await bot.send_message(user_id, f"❌ Платёж #{deposit_id} отменён (время вышло)")
        
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
                await msg.answer("❌ Минимум 1000 UZS")
                return

            expire_time = datetime.now().timestamp() + 600

            cur = get_cursor()
            cur.execute(
                "INSERT INTO deposits (user_id, amount, status, date, expire_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (uid, amount, "waiting", datetime.now().strftime("%Y-%m-%d %H:%M"), str(expire_time))
            )
            deposit_id = cur.fetchone()[0]
            conn.commit()

            await msg.answer(
                f"✅ To'lov qabul qilindi!\n\n"
                f"🆔 ID: {deposit_id}\n"
                f"💰 {amount} so'm\n"
                f"💳 {CARD_NUMBER}\n\n"
                f"📸 Чек отправьте сюда"
            )

            user_state[uid] = {"step": "await_screenshot", "deposit_id": deposit_id}

            asyncio.create_task(expire_payment(deposit_id, uid))

        elif state["step"] == "await_screenshot":
            if not msg.photo:
                await msg.answer("❌ Отправьте скриншот")
                return

            deposit_id = state["deposit_id"]
            file_id = msg.photo[-1].file_id

            cur = get_cursor()
            cur.execute(
                "UPDATE deposits SET screenshot=%s, status='pending' WHERE id=%s",
                (file_id, deposit_id)
            )
            conn.commit()

            await msg.answer("✅ Чек отправлен на проверку")

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
