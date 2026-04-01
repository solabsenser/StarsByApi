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
ADMIN_ID = int(os.getenv("ADMIN_ID"))
PRICE_PER_STAR = int(os.getenv("PRICE_PER_STAR"))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

API_URL = "https://smm.myxvest2.ru/api/v2"

# --- DB ---
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

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
    date TEXT
)
""")

conn.commit()

# --- FUNCTIONS ---
def get_user_balance(user_id):
    cur.execute("SELECT balance FROM users WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    if row:
        return row[0]
    else:
        cur.execute("INSERT INTO users (user_id, balance) VALUES (%s, 0)", (user_id,))
        conn.commit()
        return 0

def update_balance(user_id, amount):
    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id=%s", (amount, user_id))
    conn.commit()

def get_balance_api():
    return requests.get(API_URL, params={
        "action": "getBalance",
        "api_key": API_KEY
    }).json()

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
    await msg.answer("Введите сумму пополнения (UZS):")
    user_state[msg.from_user.id] = {"step": "deposit_amount"}

@dp.message(F.text == "📜 История")
async def history(msg: types.Message):
    cur.execute("SELECT username, amount, price, date FROM orders WHERE user_id=%s ORDER BY id DESC LIMIT 5", (msg.from_user.id,))
    rows = cur.fetchall()

    if not rows:
        await msg.answer("📭 История пуста")
        return

    text = "📜 История заказов:\n\n"
    for r in rows:
        text += f"👤 {r[0]} | ⭐ {r[1]} | 💰 {r[2]} UZS\n🕒 {r[3]}\n\n"

    await msg.answer(text)

# --- CALLBACK ---
@dp.callback_query()
async def callbacks(call: types.CallbackQuery):
    uid = call.from_user.id

    if call.data == "back_main":
        user_state.pop(uid, None)
        await call.message.answer("Главное меню", reply_markup=main_kb)
        return

    if call.data == "back_stars":
        await call.message.answer(
            f"💰 Цена: {PRICE_PER_STAR} UZS / ⭐\nВыберите количество:",
            reply_markup=stars_kb()
        )
        user_state[uid] = {"step": "amount"}
        return

    if call.data.startswith("buy_"):
        amount = int(call.data.split("_")[1])
        user_state[uid] = {"step": "username", "amount": amount}

        await call.message.answer(
            f"⭐ {amount} Stars\n"
            f"💰 {amount * PRICE_PER_STAR} UZS\n\n"
            f"Введите username:",
            reply_markup=back_kb()
        )

# --- ORDER PROCESS ---
async def process_order(uid, username, amount, msg):
    total_price = amount * PRICE_PER_STAR

    balance = get_user_balance(uid)
    if balance < total_price:
        await msg.answer("❌ Недостаточно средств")
        return

    update_balance(uid, -total_price)

    await msg.answer("⏳ Обрабатываем заказ...")

    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, buy_stars, username, amount)

    if res["success"]:
        cur.execute(
            "INSERT INTO orders (user_id, username, amount, price, order_id, status, date) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (uid, username, amount, total_price, res["order_id"], "success", datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        conn.commit()

        await msg.answer(
            f"✅ Готово!\n"
            f"👤 {username}\n"
            f"⭐ {amount}\n"
            f"💰 {total_price} UZS\n"
            f"🆔 {res['order_id']}"
        )
    else:
        update_balance(uid, total_price)
        await msg.answer(f"❌ Ошибка: {res['error']}")

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

            cur.execute(
                "INSERT INTO deposits (user_id, amount, status, date) VALUES (%s,%s,%s,%s) RETURNING id",
                (uid, amount, "pending", datetime.now().strftime("%Y-%m-%d %H:%M"))
            )
            deposit_id = cur.fetchone()[0]
            conn.commit()

            await msg.answer(f"✅ Заявка #{deposit_id} создана\n💰 {amount} UZS")

            await bot.send_message(
                ADMIN_ID,
                f"💳 Пополнение\nID: {deposit_id}\nUser: {uid}\n💰 {amount}\n\n/approve_{deposit_id}"
            )

            user_state.pop(uid, None)

# --- ADMIN ---
@dp.message(F.text.startswith("/approve_"))
async def approve(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return

    deposit_id = int(msg.text.split("_")[1])

    cur.execute("SELECT user_id, amount FROM deposits WHERE id=%s AND status='pending'", (deposit_id,))
    row = cur.fetchone()

    if not row:
        await msg.answer("❌ Не найдено")
        return

    user_id, amount = row

    update_balance(user_id, amount)

    cur.execute("UPDATE deposits SET status='success' WHERE id=%s", (deposit_id,))
    conn.commit()

    await msg.answer("✅ Пополнено")

    await bot.send_message(user_id, f"💰 Баланс пополнен +{amount} UZS")

# --- RUN ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
