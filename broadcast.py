from aiogram import types, F
import asyncio
from mailer import send_receipt_email

def register_broadcast(
    dp,
    bot,
    ADMIN_IDS,
    execute
):

    @dp.message(F.text.startswith("/info "))
    async def broadcast_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return

        text = msg.text[len("/info "):].strip()

        if not text:
            await msg.answer("❌ Укажите текст рассылки")
            return

        users = await execute(
            "SELECT user_id FROM users",
            fetchall=True
        )

        sent = 0
        failed = 0

        status = await msg.answer("📤 Начинаю рассылку...")

        for user in users:
            try:
                await bot.send_message(
                    user["user_id"],
                    text
                )
                sent += 1
                await asyncio.sleep(0.05)
            except:
                failed += 1

        await status.edit_text(
            f"✅ Рассылка завершена\n\n"
            f"📨 Отправлено: {sent}\n"
            f"❌ Ошибок: {failed}"
        )

    @dp.message(F.text.startswith("/mail "))
    async def send_custom_mail(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return

        try:
            parts = msg.text.split(" ", 2)
            user_id = int(parts[1])
            text = parts[2]
        except:
            await msg.answer(
                "Использование:\n/mail user_id текст"
            )
            return

        row = await execute(
            """
            SELECT email
            FROM users
            WHERE user_id=$1
            """,
            user_id,
            fetchone=True
        )

        if not row or not row["email"]:
            await msg.answer(
                "❌ Email не найден"
            )
            return

        email = row["email"]

        try:
            send_receipt_email(
                email,
                "INFO",
                "PremStars",
                "-",
                text
            )
            await msg.answer(
                f"✅ Письмо отправлено\n{email}"
            )
        except Exception as e:
            await msg.answer(
                f"❌ Ошибка:\n{e}"
            )
