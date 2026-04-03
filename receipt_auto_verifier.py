import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, Optional

import requests


OCR_SPACE_URL = "https://api.ocr.space/parse/image"
XAI_CHAT_URL = "https://api.x.ai/v1/chat/completions"


@dataclass
class VerificationResult:
    is_valid: bool
    checks: Dict[str, bool]
    extracted: Dict[str, Any]
    reasons: list[str]
    raw_ocr_text: str


class ReceiptAutoVerifier:
    """
    Автопроверка чека:
    1) OCR (OCR.space)
    2) Анализ OCR-текста через Grok (xAI API)
    3) Сопоставление с ожидаемыми данными заказа

    ENV:
    - OCR_SPACE_API_KEY: ключ OCR.space (можно использовать free tier)
    - XAI_API_KEY: ключ xAI для Grok
    """

    def __init__(self, ocr_api_key: str, xai_api_key: Optional[str] = None, timeout: int = 25):
        self.ocr_api_key = ocr_api_key
        self.xai_api_key = xai_api_key
        self.timeout = timeout

    def ocr_image(self, image_url: Optional[str] = None, image_path: Optional[str] = None) -> str:
        if not image_url and not image_path:
            raise ValueError("Нужно передать image_url или image_path")

        data = {
            "apikey": self.ocr_api_key,
            "language": "rus",
            "isOverlayRequired": False,
            "scale": True,
            "isTable": False,
            "detectOrientation": True,
            "OCREngine": 2,
        }

        if image_url:
            data["url"] = image_url
            response = requests.post(OCR_SPACE_URL, data=data, timeout=self.timeout)
        else:
            with open(image_path, "rb") as f:
                files = {"filename": f}
                response = requests.post(OCR_SPACE_URL, data=data, files=files, timeout=self.timeout)

        response.raise_for_status()
        payload = response.json()

        if payload.get("IsErroredOnProcessing"):
            raise RuntimeError(f"OCR ошибка: {payload.get('ErrorMessage')}")

        chunks = payload.get("ParsedResults") or []
        return "\n".join((x.get("ParsedText") or "").strip() for x in chunks).strip()

    @staticmethod
    def extract_with_regex(ocr_text: str) -> Dict[str, Optional[str]]:
        text = ocr_text.replace("\xa0", " ")

        amount_match = re.search(r"(\d[\d\s]{1,12})\s*(сум|so['’]?m|uzs)", text, flags=re.IGNORECASE)
        amount = None
        if amount_match:
            amount = re.sub(r"\D", "", amount_match.group(1))

        time_match = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", text)
        receipt_time = None
        if time_match:
            receipt_time = f"{time_match.group(1).zfill(2)}:{time_match.group(2)}"

        card_match = re.search(r"[•*.]\s?(\d{4})\b", text)
        card_last4 = card_match.group(1) if card_match else None

        # Для paynet-подобных чеков: строка с именем обычно перед last4
        name_match = re.search(r"\n([A-Za-zА-Яа-яЁё\s]{2,40})\s*[XxХх]\s*\n?[•*.]\s?\d{4}", text)
        cardholder_name = name_match.group(1).strip() if name_match else None

        return {
            "amount": amount,
            "receipt_time": receipt_time,
            "card_last4": card_last4,
            "cardholder_name": cardholder_name,
        }

    def analyze_with_grok(self, ocr_text: str) -> Dict[str, Optional[str]]:
        if not self.xai_api_key:
            return {}

        headers = {
            "Authorization": f"Bearer {self.xai_api_key}",
            "Content-Type": "application/json",
        }
        prompt = (
            "Извлеки из OCR-текста данные платежного чека и верни ТОЛЬКО JSON с ключами: "
            "amount, receipt_time(HH:MM), card_last4, cardholder_name. "
            "Если не найдено — null. Без markdown и пояснений.\n\n"
            f"OCR:\n{ocr_text}"
        )

        body = {
            "model": "grok-2-latest",
            "messages": [
                {"role": "system", "content": "Ты извлекаешь структурированные поля из чека."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }

        response = requests.post(XAI_CHAT_URL, headers=headers, json=body, timeout=self.timeout)
        response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"].strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            cleaned = re.sub(r"^```json|```$", "", content, flags=re.MULTILINE).strip()
            return json.loads(cleaned)

    @staticmethod
    def _normalize_name(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return re.sub(r"\s+", " ", value).strip().lower()

    @staticmethod
    def _time_diff_minutes(receipt_hhmm: str, message_dt: datetime) -> int:
        h, m = map(int, receipt_hhmm.split(":"))
        receipt_minutes = h * 60 + m
        message_minutes = message_dt.hour * 60 + message_dt.minute
        return abs(receipt_minutes - message_minutes)

    def verify(
        self,
        image_url: Optional[str],
        image_path: Optional[str],
        expected_amount: int,
        expected_card_last4: str,
        expected_cardholder_name: str,
        message_datetime: datetime,
        time_tolerance_minutes: int = 2,
    ) -> VerificationResult:
        ocr_text = self.ocr_image(image_url=image_url, image_path=image_path)

        regex_data = self.extract_with_regex(ocr_text)
        grok_data = self.analyze_with_grok(ocr_text)

        extracted = {
            "amount": grok_data.get("amount") or regex_data.get("amount"),
            "receipt_time": grok_data.get("receipt_time") or regex_data.get("receipt_time"),
            "card_last4": grok_data.get("card_last4") or regex_data.get("card_last4"),
            "cardholder_name": grok_data.get("cardholder_name") or regex_data.get("cardholder_name"),
        }

        checks: Dict[str, bool] = {}
        reasons: list[str] = []

        extracted_amount = int(extracted["amount"]) if extracted.get("amount") and str(extracted["amount"]).isdigit() else None
        checks["amount_exact"] = extracted_amount == int(expected_amount)
        if not checks["amount_exact"]:
            reasons.append(f"Сумма не совпала: чек={extracted_amount}, ожидалось={expected_amount}")

        checks["card_last4_match"] = str(extracted.get("card_last4") or "") == str(expected_card_last4)
        if not checks["card_last4_match"]:
            reasons.append(
                f"Последние 4 цифры карты не совпали: чек={extracted.get('card_last4')}, ожидалось={expected_card_last4}"
            )

        extracted_name = self._normalize_name(extracted.get("cardholder_name"))
        expected_name = self._normalize_name(expected_cardholder_name)
        checks["cardholder_name_match"] = bool(extracted_name and expected_name and expected_name in extracted_name)
        if not checks["cardholder_name_match"]:
            reasons.append(
                f"Имя карты не совпало: чек={extracted.get('cardholder_name')}, ожидалось={expected_cardholder_name}"
            )

        receipt_time = extracted.get("receipt_time")
        if receipt_time:
            diff = self._time_diff_minutes(receipt_time, message_datetime)
            checks["time_within_tolerance"] = diff <= time_tolerance_minutes
            if not checks["time_within_tolerance"]:
                reasons.append(
                    f"Время чека вне допуска: чек={receipt_time}, сообщение={message_datetime.strftime('%H:%M')}, diff={diff} мин"
                )
        else:
            checks["time_within_tolerance"] = False
            reasons.append("Не удалось извлечь время с чека")

        is_valid = all(checks.values())

        return VerificationResult(
            is_valid=is_valid,
            checks=checks,
            extracted=extracted,
            reasons=reasons,
            raw_ocr_text=ocr_text,
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Автоматическая проверка чека через OCR + Grok")
    parser.add_argument("--image-url", help="URL изображения чека")
    parser.add_argument("--image-path", help="Локальный путь к изображению чека")
    parser.add_argument("--expected-amount", type=int, required=True, help="Ожидаемая сумма")
    parser.add_argument("--expected-last4", required=True, help="Ожидаемые последние 4 цифры карты")
    parser.add_argument("--expected-name", required=True, help="Ожидаемое имя на карте")
    parser.add_argument(
        "--message-datetime",
        required=True,
        help="Время сообщения с чеком в формате YYYY-MM-DD HH:MM (например, 2026-04-03 21:28)",
    )
    parser.add_argument("--time-tolerance", type=int, default=2, help="Погрешность времени в минутах")
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    ocr_key = os.getenv("OCR_SPACE_API_KEY")
    if not ocr_key:
        raise RuntimeError("Не задан OCR_SPACE_API_KEY")

    verifier = ReceiptAutoVerifier(
        ocr_api_key=ocr_key,
        xai_api_key=os.getenv("XAI_API_KEY"),
    )

    message_dt = datetime.strptime(args.message_datetime, "%Y-%m-%d %H:%M")

    result = verifier.verify(
        image_url=args.image_url,
        image_path=args.image_path,
        expected_amount=args.expected_amount,
        expected_card_last4=args.expected_last4,
        expected_cardholder_name=args.expected_name,
        message_datetime=message_dt,
        time_tolerance_minutes=args.time_tolerance,
    )

    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
