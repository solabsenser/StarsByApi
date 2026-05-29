import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

EMAIL_LOGIN = os.getenv("EMAIL_LOGIN")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")


def send_receipt_email(
    email,
    order_id,
    username,
    stars,
    amount
):
    text = f"""
Спасибо за покупку!

Номер заказа: {order_id}
Получатель: @{username}
Количество звезд: {stars}
Сумма: {amount} UZS

Ваш заказ успешно выполнен.
"""

    msg = MIMEText(text, "plain", "utf-8")

    msg["Subject"] = f"Заказ #{order_id}"
    msg["From"] = EMAIL_LOGIN
    msg["To"] = email

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465
    ) as server:

        server.login(
            EMAIL_LOGIN,
            EMAIL_PASSWORD
        )

        server.send_message(msg)
