from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def register_profile(dp, safe_execute, get_user_balance, format_price, user_state):

    @dp.message(F.text.in_(["👤 Профиль", "👤 Profil"]))
    async def profile(msg: types.Message):
        uid = msg.from_user.id

        row = safe_execute(
            """
            SELECT email,email_verified
            FROM users
            WHERE user_id=%s
            """,
            (uid,),
            fetchone=True
        )

        email = "Не подключен"
        verified = "❌"

        if row and row[0]:
            email = row[0]
            verified = "✅" if row[1] else "❌"

        stats = safe_execute(
            """
            SELECT
                COUNT(*),
                COALESCE(SUM(amount),0)
            FROM orders
            WHERE user_id=%s
            AND status='success'
            """,
            (uid,),
            fetchone=True
        )

        orders_count = stats[0] if stats else 0
        stars_count = stats[1] if stats else 0

        balance = get_user_balance(uid)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📧 Подключить Email",
                        callback_data="connect_email"
                    )
                ]
            ]
        )

        await msg.answer(
            f"👤 Профиль\n\n"
            f"🆔 ID: {uid}\n"
            f"📧 Email: {email} {verified}\n\n"
            f"💰 Баланс: {format_price(balance)} UZS\n"
            f"🧾 Заказов: {orders_count}\n"
            f"⭐ Куплено звезд: {stars_count}",
            reply_markup=kb
        )

    @dp.callback_query(F.data == "connect_email")
    async def connect_email(call: types.CallbackQuery):
        uid = call.from_user.id

        user_state[uid] = {
            "step": "email_input"
        }

        await call.message.delete()

        msg = await call.message.answer(
            "📧 Введите Email:"
        )

        user_state[uid]["prompt_msg_id"] = msg.message_id

        await call.answer()
