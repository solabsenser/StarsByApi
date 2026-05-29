from aiogram import types, F
import asyncio


def register_broadcast(
    dp,
    bot,
    ADMIN_IDS,
    safe_execute
):

    @dp.message(F.text.startswith("/info "))
    async def broadcast_cmd(msg: types.Message):

        if msg.from_user.id not in ADMIN_IDS:
            return

        text = msg.text[len("/info "):].strip()

        if not text:
            await msg.answer("❌ Укажите текст рассылки")
            return

        users = safe_execute(
            "SELECT user_id FROM users",
            fetchall=True
        )

        sent = 0
        failed = 0

        status = await msg.answer("📤 Начинаю рассылку...")

        for user in users:

            try:
                await bot.send_message(
                    user[0],
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
