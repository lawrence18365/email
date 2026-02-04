from __future__ import annotations

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from config import Config

_UNSUBSCRIBE_SALT = "unsubscribe-v1"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(Config.SECRET_KEY, salt=_UNSUBSCRIBE_SALT)


def generate_unsubscribe_token(lead_id: int, email: str) -> str:
    serializer = _serializer()
    return serializer.dumps({"lead_id": lead_id, "email": email})


def verify_unsubscribe_token(token: str, max_age_seconds: int) -> dict | None:
    serializer = _serializer()
    try:
        data = serializer.loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None

    if not isinstance(data, dict):
        return None

    if "lead_id" not in data or "email" not in data:
        return None

    return data
