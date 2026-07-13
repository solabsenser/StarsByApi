from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def register_profile(dp, execute, get_user_balance, format_price, user_state):

    @dp.message(F.text.in_(["👤 Профиль", "👤 Profil"]))
    async def profile(msg: types.Message):
        uid = msg.from_user.id

        lang_row = await execute(
            "SELECT lang FROM users WHERE user_id=$1",
            uid,
            fetchone=True
        )

        lang = lang_row["lang"] if lang_row else "ru"

        row = await execute(
            """
            SELECT email, email_verified
            FROM users
            WHERE user_id=$1
            """,
            uid,
            fetchone=True
        )

        email = "Ulanmagan" if lang == "uz" else "Не подключен"
        verified = "❌"

        if row and row["email"]:
            email = row["email"]
            verified = "✅" if row["email_verified"] else "❌"

        stats = await execute(
            """
            SELECT
                COUNT(*) AS orders_count,
                COALESCE(SUM(amount), 0) AS stars_count
            FROM orders
            WHERE user_id=$1
            AND status='success'
            """,
            uid,
            fetchone=True
        )

        orders_count = stats["orders_count"] if stats else 0
        stars_count = stats["stars_count"] if stats else 0

        balance = await get_user_balance(uid)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📧 Email ulash" if lang == "uz" else "📧 Подключить Email",
                        callback_data="connect_email"
                    )
                ]
            ]
        )

        if lang == "uz":
            text = (
                f"👤 Profil\n\n"
                f"🆔 ID: {uid}\n"
                f"📧 Email: {email} {verified}\n\n"
                f"💰 Balans: {format_price(balance)} UZS\n"
                f"🧾 Buyurtmalar: {orders_count}\n"
                f"⭐ Xarid qilingan yulduzlar: {stars_count}"
            )
        else:
            text = (
                f"👤 Профиль\n\n"
                f"🆔 ID: {uid}\n"
                f"📧 Email: {email} {verified}\n\n"
                f"💰 Баланс: {format_price(balance)} UZS\n"
                f"🧾 Заказов: {orders_count}\n"
                f"⭐ Куплено звезд: {stars_count}"
            )

        await msg.answer(
            text,
            reply_markup=kb
        )

    @dp.callback_query(F.data == "connect_email")
    async def connect_email(call: types.CallbackQuery):
        uid = call.from_user.id

        lang_row = await execute(
            "SELECT lang FROM users WHERE user_id=$1",
            uid,
            fetchone=True
        )

        lang = lang_row["lang"] if lang_row else "ru"

        user_state[uid] = {
            "step": "email_input"
        }

        await call.message.delete()

        msg = await call.message.answer(
            "📧 Email kiriting:"
            if lang == "uz"
            else "📧 Введите Email:"
        )

        user_state[uid]["prompt_msg_id"] = msg.message_id

        await call.answer()
