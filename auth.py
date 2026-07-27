"""JWT-аутентификация и хеширование паролей."""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-to-a-random-string")
JWT_ALGORITHM = "HS256"
# Токен живёт 365 дней
JWT_EXPIRE_DAYS = 365


def hash_password(password: str) -> str:
    """Захешировать пароль через bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Проверить пароль против хеша."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Создать JWT-токен.

    data — словарь с данными для payload (минимум 'sub').
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(days=JWT_EXPIRE_DAYS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Раскодировать JWT-токен. Возвращает payload или выбрасывает JWTError."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
