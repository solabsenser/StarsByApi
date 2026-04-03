import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, Optional

import requests


OCR_SPACE_URL = "https://api.ocr.space/parse/image"


@dataclass
class VerificationResult:
    is_valid: bool
    checks: Dict[str, bool]
    extracted: Dict[str, Any]
    reasons: list[str]
    raw_ocr_text: str


class ReceiptAutoVerifier:
    def __init__(self, ocr_api_key: str, groq_api_key: Optional[str] = None, timeout: int = 25):
        self.ocr_api_key = ocr_api_key
        self.groq_api_key = groq_api_key
        self.timeout = timeout

    # --- OCR ---
    def ocr_image(self, image_url=None, image_path=None) -> str:
        if not image_url and not image_path:
            raise ValueError("Нужно передать image_url или image_path")

        data = {
            "apikey": self.ocr_api_key,
            "language": "eng",  # 🔥 лучше чем rus
            "scale": True,
            "OCREngine": 2,
        }

        if image_url:
            data["url"] = image_url
            response = requests.post(OCR_SPACE_URL, data=data, timeout=self.timeout)
        else:
            with open(image_path, "rb") as f:
                response = requests.post(OCR_SPACE_URL, data=data, files={"filename": f}, timeout=self.timeout)

        response.raise_for_status()
        payload = response.json()

        if payload.get("IsErroredOnProcessing"):
            raise RuntimeError(f"OCR ошибка: {payload.get('ErrorMessage')}")

        return "\n".join(x.get("ParsedText", "") for x in payload.get("ParsedResults", [])).strip()

    # --- REGEX ---
    @staticmethod
    def extract_with_regex(text: str):
        text = text.replace("\xa0", " ")

        amount_match = re.search(r"(\d[\d\s.,]{1,15})\s*(сум|so['’]?m|uzs)", text, re.I)
        amount = re.sub(r"\D", "", amount_match.group(1)) if amount_match else None

        time_match = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", text)
        receipt_time = f"{time_match.group(1).zfill(2)}:{time_match.group(2)}" if time_match else None

        card_match = re.search(r"[•*.]\s?(\d{4})\b", text)
        card_last4 = card_match.group(1) if card_match else None

        return {
            "amount": amount,
            "receipt_time": receipt_time,
            "card_last4": card_last4,
            "cardholder_name": None,  # отключили пока
        }

    # --- GROQ (LLAMA) ---
    def analyze_with_llama(self, ocr_text: str):
        if not self.groq_api_key:
            return {}

        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }

        prompt = (
            "Верни строго JSON:\n"
            '{ "amount": number, "receipt_time": "HH:MM", "card_last4": "1234" }\n'
            "Без текста.\n\n"
            f"Текст:\n{ocr_text}"
        )

        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": "Ты извлекаешь данные из чеков."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                },
                timeout=self.timeout,
            )

            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

            cleaned = re.sub(r"```json|```", "", content).strip()
            return json.loads(cleaned)

        except:
            return {}

    # --- VERIFY ---
    def verify(
        self,
        image_url,
        image_path,
        expected_amount,
        expected_card_last4,
        expected_cardholder_name,
        message_datetime,
        time_tolerance_minutes=2,
    ):
        ocr_text = self.ocr_image(image_url, image_path)

        regex_data = self.extract_with_regex(ocr_text)
        llama_data = self.analyze_with_llama(ocr_text)

        extracted = {
            "amount": llama_data.get("amount") or regex_data.get("amount"),
            "receipt_time": llama_data.get("receipt_time") or regex_data.get("receipt_time"),
            "card_last4": llama_data.get("card_last4") or regex_data.get("card_last4"),
        }

        checks = {}
        reasons = []

        # --- AMOUNT ---
        extracted_amount = int(extracted["amount"]) if extracted.get("amount") and str(extracted["amount"]).isdigit() else None
        checks["amount"] = extracted_amount == expected_amount
        if not checks["amount"]:
            reasons.append(f"Сумма не совпала: {extracted_amount} != {expected_amount}")

        # --- CARD ---
        checks["card"] = str(extracted.get("card_last4")) == str(expected_card_last4)
        if not checks["card"]:
            reasons.append(f"Карта не совпала: {extracted.get('card_last4')} != {expected_card_last4}")

        # --- TIME ---
        if extracted.get("receipt_time"):
            h, m = map(int, extracted["receipt_time"].split(":"))
            diff = abs((h * 60 + m) - (message_datetime.hour * 60 + message_datetime.minute))
            checks["time"] = diff <= time_tolerance_minutes
            if not checks["time"]:
                reasons.append(f"Время не совпало: diff={diff} мин")
        else:
            checks["time"] = False
            reasons.append("Время не найдено")

        return VerificationResult(
            is_valid=all(checks.values()),
            checks=checks,
            extracted=extracted,
            reasons=reasons,
            raw_ocr_text=ocr_text,
        )


# --- CLI ---
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-path")
    parser.add_argument("--expected-amount", type=int, required=True)
    parser.add_argument("--expected-last4", required=True)
    parser.add_argument("--message-datetime", required=True)

    args = parser.parse_args()

    verifier = ReceiptAutoVerifier(
        ocr_api_key=os.getenv("OCR_SPACE_API_KEY"),
        groq_api_key=os.getenv("XAI_API_KEY"),  # 👈 сюда кладёшь GROQ ключ
    )

    result = verifier.verify(
        image_url=None,
        image_path=args.image_path,
        expected_amount=args.expected_amount,
        expected_card_last4=args.expected_last4,
        expected_cardholder_name="",
        message_datetime=datetime.strptime(args.message_datetime, "%Y-%m-%d %H:%M"),
    )

    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
