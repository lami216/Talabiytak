import re
import unicodedata


class ArabicNormalizationService:
    _digits = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    _alef = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})

    def normalize(self, text: str) -> str:
        text = (
            unicodedata.normalize("NFKC", text)
            .translate(self._digits)
            .translate(self._alef)
            .casefold()
        )
        text = re.sub(r"[\u064b-\u065f\u0670\u06d6-\u06edـ]", "", text)
        text = re.sub(r"[^\w\s\u0600-\u06ff]", " ", text, flags=re.UNICODE)
        return re.sub(r"\s+", " ", text).strip()
