"""
artha-v2/backend/crypto.py
Fernet-based encryption for all secrets.
Rule: NO plaintext secrets ever stored.
"""

import logging
from cryptography.fernet import Fernet, InvalidToken
from backend.config import settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.FERNET_KEY.encode()
        _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt plaintext string → URL-safe base64 ciphertext."""
    if not plaintext:
        raise ValueError("Cannot encrypt empty string")
    try:
        fernet = _get_fernet()
        return fernet.encrypt(plaintext.encode()).decode()
    except Exception as e:
        logger.error("Encryption failed", exc_info=True)
        raise RuntimeError("Encryption failed") from e


def decrypt(ciphertext: str) -> str:
    """Decrypt Fernet ciphertext → plaintext string."""
    if not ciphertext:
        raise ValueError("Cannot decrypt empty string")
    try:
        fernet = _get_fernet()
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.error("Decryption failed: invalid token or wrong key")
        raise ValueError("Decryption failed: invalid token")
    except Exception as e:
        logger.error("Decryption error", exc_info=True)
        raise RuntimeError("Decryption failed") from e


def rotate_key(old_key: str, new_key: str, ciphertext: str) -> str:
    """Re-encrypt ciphertext with new key. Use during key rotation."""
    old_fernet = Fernet(old_key.encode())
    plaintext = old_fernet.decrypt(ciphertext.encode()).decode()
    new_fernet = Fernet(new_key.encode())
    return new_fernet.encrypt(plaintext.encode()).decode()
