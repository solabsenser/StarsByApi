import os
import requests
from dotenv import load_dotenv

load_dotenv()

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")
SENDER_NAME = os.getenv("BREVO_SENDER_NAME")


def send_receipt_email(
    email,
    order_id,
    username,
    stars,
    amount
):
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }

    payload = {
        "sender": {
            "name": SENDER_NAME,
            "email": SENDER_EMAIL
        },
        "to": [
            {
                "email": email
            }
        ],
        "subject": f"Заказ #{order_id}",
        "htmlContent": f"""
        <h2>Спасибо за покупку!</h2>

        <p><b>Номер заказа:</b> {order_id}</p>
        <p><b>Получатель:</b> @{username}</p>
        <p><b>Количество звёзд:</b> {stars}</p>
        <p><b>Сумма:</b> {amount} UZS</p>

        <hr>

        <p>Ваш заказ успешно выполнен.</p>
        """
    }

    response = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers=headers,
        json=payload,
        timeout=30
    )

    print("BREVO STATUS:", response.status_code)
    print("BREVO RESPONSE:", response.text)ц
