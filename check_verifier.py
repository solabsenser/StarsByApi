"""
Модуль проверки чеков Uzum Bank через OCR.space API
Без установки Pillow, pytesseract и прочих тяжелых библиотек
"""

import requests
import base64
import re
import hashlib
import logging
import asyncio

logger = logging.getLogger(__name__)


class UzumCheckVerifier:
    def __init__(self, api_key='helloworld'):
        """
        Args:
            api_key: ключ OCR.space (helloworld - бесплатный, 500 запросов/месяц)
        """
        self.api_key = api_key
        self.used_hashes = set()
        self.amount_tolerance = 0.10  # 10% допуск для надёжности
    
    async def verify(self, image_bytes, expected_amount):
        """
        Проверяет чек и сверяет сумму
        
        Returns:
            (success: bool, message: str, amount: int or None)
        """
        # Проверка дубликата с правильной обработкой байтов
        try:
            if hasattr(image_bytes, 'getvalue'):
                img_hash = hashlib.md5(image_bytes.getvalue()).hexdigest()
            else:
                img_hash = hashlib.md5(image_bytes).hexdigest()
        except Exception as e:
            logger.error(f"Ошибка хеширования: {e}")
            # Если не можем вычислить хеш, пропускаем проверку дубликата
            img_hash = None
        
        if img_hash and img_hash in self.used_hashes:
            return False, "❌ Этот чек уже был использован", None
        
        # Отправляем на OCR с повторными попытками
        text = None
        for attempt in range(3):
            try:
                text = await self._ocr_image(image_bytes)
                if text:
                    break
            except Exception as e:
                logger.warning(f"OCR попытка {attempt+1} не удалась: {e}")
                await asyncio.sleep(1)
        
        if not text:
            return False, "❌ Не удалось распознать чек. Отправьте чёткое фото.", None
        
        logger.debug(f"OCR текст: {text[:200]}...")
        
        # Ищем сумму
        amount = self._extract_amount(text)
        if not amount:
            return False, "❌ Не удалось найти сумму на чеке", None
        
        # Проверяем совпадение
        if abs(amount - expected_amount) / expected_amount > self.amount_tolerance:
            return False, f"❌ Сумма не совпадает: {amount} UZS (ожидалось {expected_amount})", amount
        
        # Сохраняем хеш
        if img_hash:
            self.used_hashes.add(img_hash)
        
        return True, f"✅ Чек подтверждён!\n💰 Сумма: {amount} UZS", amount
    
    async def _ocr_image(self, image_bytes):
        """Отправляет изображение в OCR.space и возвращает распознанный текст"""
        try:
            # Конвертируем байты в base64
            if hasattr(image_bytes, 'getvalue'):
                b64 = base64.b64encode(image_bytes.getvalue()).decode('utf-8')
            else:
                b64 = base64.b64encode(image_bytes).decode('utf-8')
        except Exception as e:
            logger.error(f"Ошибка конвертации в base64: {e}")
            return None
        
        response = requests.post(
            'https://api.ocr.space/parse/image',
            data={
                'apikey': self.api_key,
                'base64Image': b64,
                'language': 'rus',
                'OCREngine': 2,
                'scale': True,
                'isTable': False,
                'detectOrientation': True,
                'filetype': 'PNG'
            },
            timeout=30
        )
        
        data = response.json()
        
        if data.get('IsErroredOnProcessing'):
            error_msg = data.get('ErrorMessage', ['Unknown error'])[0]
            logger.error(f"OCR.space ошибка: {error_msg}")
            return None
        
        if not data.get('ParsedResults'):
            return None
        
        return data['ParsedResults'][0].get('ParsedText', '')
    
    def _extract_amount(self, text):
        """Извлекает сумму из текста чека"""
        patterns = [
            # Uzum Bank формат
            r'Перевели\s+(\d+[\s.]?\d*)\s*сум',
            r'Перевели\s+(\d+[\s.]?\d*)\s*UZS',
            r'Перевели\s+(\d+[\s.]?\d*)',
            
            # Общие паттерны
            r'сумма[:\s]+(\d+[\s.]?\d*)\s*сум',
            r'итого[:\s]+(\d+[\s.]?\d*)\s*сум',
            r'(\d+[\s.]?\d*)\s*сум',
            r'(\d+[\s.]?\d*)\s*UZS',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    amount_str = match.group(1).replace(' ', '').replace('.', '')
                    amount = int(amount_str)
                    if amount >= 1000:  # Пропускаем слишком маленькие суммы
                        return amount
                except:
                    continue
        
        return None


# Функция для быстрой проверки (для отладки)
async def quick_verify(image_bytes, expected_amount):
    verifier = UzumCheckVerifier()
    return await verifier.verify(image_bytes, expected_amount)
