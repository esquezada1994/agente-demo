"""Controles deterministas de entrada y salida.

Primera línea de defensa, sin depender del modelo: reglas explícitas que se
pueden auditar y probar. Un modelo validador puede sumarse como otro nodo.
"""

from __future__ import annotations

import re
import unicodedata

# Cédula o RUC de Ecuador, tarjetas, correos y teléfonos.
_CEDULA = re.compile(r"\b\d{10}(?:001)?\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PHONE = re.compile(r"(?:\+593|\b0)9\d{8}\b")

_INJECTION = [
    "ignora las instrucciones",
    "ignora tus instrucciones",
    "olvida tus instrucciones",
    "olvida las instrucciones",
    "ignore previous instructions",
    "ignore all previous",
    "system prompt",
    "prompt del sistema",
    "eres ahora",
    "actua como si",
    "modo desarrollador",
    "developer mode",
]
_UNAUTHORIZED_OFFER = re.compile(
    r"\b(descuento|condon\w*|rebaja|perdon\w* (la|el|los) (deuda|interes))", re.I
)
_MONEY = re.compile(r"\$\s?((?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d{1,2})?)(?!\d)")


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _luhn(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def find_personal_data(text: str) -> list[str]:
    """Categorías de datos personales presentes (nunca los valores)."""
    found = []
    if _CEDULA.search(text):
        found.append("id_number")
    for match in _CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append("card_number")
            break
    if _EMAIL.search(text):
        found.append("email")
    if _PHONE.search(text):
        found.append("phone")
    return found


def mask_personal_data(text: str) -> str:
    text = _CARD.sub(
        lambda m: "[tarjeta]" if _luhn(re.sub(r"\D", "", m.group())) else m.group(), text
    )
    text = _CEDULA.sub("[identificación]", text)
    text = _EMAIL.sub("[correo]", text)
    return _PHONE.sub("[teléfono]", text)


def looks_like_injection(text: str) -> bool:
    plain = _plain(text)
    return any(pattern in plain for pattern in _INJECTION)


def unauthorized_offer(text: str) -> bool:
    return bool(_UNAUTHORIZED_OFFER.search(_plain(text)))


def _normalize_amount(raw: str) -> str:
    raw = raw.replace(" ", "")
    if "," in raw and "." in raw:
        raw = (
            raw.replace(",", "")
            if raw.rfind(".") > raw.rfind(",")
            else raw.replace(".", "").replace(",", ".")
        )
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return f"{float(raw):.2f}"
    except ValueError:
        return raw


def amounts_in(text: str) -> set[str]:
    return {_normalize_amount(m) for m in _MONEY.findall(text)}


def ungrounded_amounts(answer: str, evidence: str) -> set[str]:
    """Montos que la respuesta menciona y no aparecen en lo que devolvieron las
    herramientas: el modelo los habría inventado."""
    known = {_normalize_amount(m) for m in re.findall(r"\d+(?:[.,]\d{1,2})?", evidence)}
    return {a for a in amounts_in(answer) if a not in known}
