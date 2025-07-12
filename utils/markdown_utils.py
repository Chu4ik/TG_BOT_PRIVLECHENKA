# utils/markdown_utils.py
import re

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for MarkdownV2."""
    if text is None:
        return ""

    # Экранируем сам обратный слэш первым
    text = text.replace('\\', '\\\\')

    # Остальные специальные символы MarkdownV2
    special_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)