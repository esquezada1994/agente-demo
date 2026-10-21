"""Contraseñas, sesiones y secretos guardados.

- Contraseñas: scrypt de la biblioteca estándar (resistente a GPU), con sal
  por usuario. Sin dependencias extra.
- Sesiones: JWT firmado (HS256) en una cookie httpOnly, SameSite=Lax. El
  navegador nunca ve el token desde JavaScript.
- Secretos guardados (llave del portal): Fernet con una llave derivada de
  SECRET_KEY. Nunca se devuelven por la API ni se escriben en logs.
"""

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from agente.config import get_settings
from agente.db import StoredSecret, utcnow

SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 64}
SESSION_HOURS = 12
COOKIE = "agente_sesion"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def check_password_policy(password: str) -> None:
    if len(password) < 10:
        raise ValueError("La contraseña debe tener al menos 10 caracteres")
    if password.isalpha() or password.isdigit():
        raise ValueError("La contraseña debe combinar letras y números o símbolos")


def generate_password() -> str:
    return secrets.token_urlsafe(12)


def _secret() -> str:
    return get_settings().secret_key.get_secret_value()


def create_session_token(user_id: uuid.UUID, role: str) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=SESSION_HOURS),
    }
    return jwt.encode(claims, _secret(), algorithm="HS256")


def read_session_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def _fernet() -> Fernet:
    key = hashlib.sha256(("secretos:" + _secret()).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def store_secret(session: Session, key: str, value: str) -> None:
    row = session.get(StoredSecret, key) or StoredSecret(key=key, value_encrypted="")
    row.value_encrypted = _fernet().encrypt(value.encode()).decode()
    row.hint = value[:6] + "…" + value[-4:]
    row.updated_at = utcnow()
    session.add(row)


def read_secret(session: Session, key: str) -> str | None:
    row = session.get(StoredSecret, key)
    if row is None:
        return None
    return _fernet().decrypt(row.value_encrypted.encode()).decode()
