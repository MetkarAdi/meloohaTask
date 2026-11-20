"""Conservative language checks for answer validation, not reply-language selection."""

from __future__ import annotations

import re

LANGUAGE_RULE = (
    "reply in the same language as user's last message, in every language, including section headings. "
    "if message is in english, or you are not sure, reply in english. never switch to a language the user did not use. "
    "always write planet, sign and house names in english in brackets next to the translated term, "
    "e.g. Jupiter (गुरु) or Júpiter (Jupiter), and keep fact IDs, numbers and dates unchanged."
)

_MARKERS = {
    "english": set("the and what when where which who does your my is are in of to for with could would about career chart".split()),
    "spanish": set("el la los las un una y que qué cuando dónde como cómo de del en para por tu mi es son puede podría trabajo".split()),
    "turkish": set("ve bir bu şu için ile ne nasıl hangi kariyer iş hayatında olabilir gösteriyor".split()),
    "french": set("le la les un une et que quand où comment de du des dans pour votre mon est sont peut pourrait carrière".split()),
}


def detect_language(text: str) -> str | None:
    """Return a language only when script or lexical evidence is reasonably clear."""
    if re.search(r"[\u0900-\u097f]", text):
        return "hindi"
    words = set(re.findall(r"[^\W\d_]+", text.casefold(), flags=re.UNICODE))
    if not words:
        return None
    scores = {lang: len(words & markers) for lang, markers in _MARKERS.items()}
    # Accented letters and Turkish-specific letters are strong lexical signals.
    if re.search(r"[çğıİöşü]", text):
        scores["turkish"] += 2
    if re.search(r"[àâæçéèêëîïôœùûüÿ]", text, re.I):
        scores["french"] += 1
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    if ranked[0][1] < 2 or ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def language_mismatch(question: str, answer: str) -> tuple[str, str] | None:
    expected, actual = detect_language(question), detect_language(answer)
    if expected and actual and expected != actual:
        return expected, actual
    return None


def localized_unavailable(question: str) -> str:
    """Translate the generic safe failure notice without passing user content to another model."""
    language = detect_language(question)
    return {
        "hindi": "अभी ज्योतिषीय उत्तर उपलब्ध नहीं हैं। कृपया थोड़ी देर बाद फिर कोशिश करें।",
        "spanish": "Las respuestas astrológicas no están disponibles por ahora. Inténtalo de nuevo en un momento.",
        "turkish": "Astroloji yanıtları şu anda kullanılamıyor. Lütfen biraz sonra tekrar deneyin.",
        "french": "Les réponses astrologiques sont momentanément indisponibles. Veuillez réessayer dans un instant.",
    }.get(language, "Astrology answers are temporarily unavailable. Please try again in a little while.")
