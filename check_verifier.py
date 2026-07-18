import io
import re
from PIL import Image, ImageEnhance
import pytesseract

class UzumCheckVerifier:
    def __init__(self):
        self.used_hashes = set()
    
    async def verify(self, image_bytes, expected_amount):
        # Хеш против повторов (простая защита)
        import hashlib
        img_hash = hashlib.md5(image_bytes).hexdigest()
        if img_hash in self.used_hashes:
            return False, "Чек уже использован", None
        
        # OCR
        img = Image.open(io.BytesIO(image_bytes))
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        
        text = pytesseract.image_to_string(img, lang='rus+eng')
        
        # Ищем сумму
        patterns = [
            r'Перевели\s+(\d+[\s.]?\d*)\s*сум',
            r'(\d+[\s.]?\d*)\s*сум',
            r'(\d+[\s.]?\d*)\s*UZS',
        ]
        
        amount = None
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount = int(match.group(1).replace(' ', '').replace('.', ''))
                break
        
        if not amount:
            return False, "Не удалось распознать сумму", None
        
        # Проверка с допуском 5%
        if abs(amount - expected_amount) / expected_amount > 0.05:
            return False, f"Сумма не совпадает: {amount} (ожидалось {expected_amount})", amount
        
        self.used_hashes.add(img_hash)
        return True, f"✅ {amount} UZS", amount
