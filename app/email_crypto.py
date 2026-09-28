"""Parolni DB'da shifrlab saqlash (faqat stdlib).

DIQQAT: bu stdlib-only himoya (HMAC-SHA256 oqim kaliti + XOR), KMS/AEAD emas.
U DB fayli o'g'irlansa-yu, kalit fayli (backend/data/.email_key) o'g'irlanmasa
parolni oddiy ko'z bilan ko'rishdan saqlaydi. Kalit ham o'g'irlansa — himoya yo'q.
Yaxshiroq variant: `cryptography` kutubxonasi (Fernet/AES-GCM) — tasdiq kerak.

Format: base64( nonce(16) || ciphertext || tag(16) )
  keystream = HMAC(key, nonce || counter) bloklari; tag = HMAC(key, "tag" || nonce || ciphertext)[:16]
Tag buzilgan/kalit noto'g'ri bo'lsa deshifrlash ValueError beradi.
"""
import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
KEY_FILE = BACKEND_DIR / "data" / ".email_key"

_key_cache: bytes | None = None


def _load_key() -> bytes:
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    env_key = os.getenv("EMAIL_SECRET_KEY", "").strip()
    if env_key:
        _key_cache = hashlib.sha256(env_key.encode("utf-8")).digest()
        return _key_cache
    if KEY_FILE.is_file():
        raw = KEY_FILE.read_text(encoding="utf-8").strip()
    else:
        raw = secrets.token_urlsafe(32)
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
    _key_cache = hashlib.sha256(raw.encode("utf-8")).digest()
    return _key_cache


def _reset_key_cache() -> None:  # testlar uchun
    global _key_cache
    _key_cache = None


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def encrypt_password(plain: str) -> str:
    key = _load_key()
    data = plain.encode("utf-8")
    nonce = secrets.token_bytes(16)
    stream = _keystream(key, nonce, len(data))
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(key, b"tag" + nonce + cipher, hashlib.sha256).digest()[:16]
    return base64.b64encode(nonce + cipher + tag).decode("ascii")


def decrypt_password(token: str) -> str:
    key = _load_key()
    try:
        raw = base64.b64decode(token.encode("ascii"), validate=True)
    except Exception as exc:
        raise ValueError("Shifrlangan parol formati noto'g'ri.") from exc
    if len(raw) < 32:
        raise ValueError("Shifrlangan parol formati noto'g'ri.")
    nonce, cipher, tag = raw[:16], raw[16:-16], raw[-16:]
    expected = hmac.new(key, b"tag" + nonce + cipher, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("Parolni deshifrlab bo'lmadi (kalit o'zgargan yoki ma'lumot buzilgan).")
    stream = _keystream(key, nonce, len(cipher))
    return bytes(a ^ b for a, b in zip(cipher, stream)).decode("utf-8")
