import logging
from cryptography.fernet import Fernet
from src.config.config import ENCRYPTION_KEY

logger = logging.getLogger(__name__)

def _get_cipher_suite():
    try:
        return Fernet(ENCRYPTION_KEY.encode('utf-8'))
    except Exception:
        logger.error("Invalid ENCRYPTION_KEY. Must be 32 url-safe base64-encoded bytes. Falling back to default for safety.")
        # Fallback to a stable random key so the app doesn't crash, but warn heavily
        fallback_key = "uE_jK_d-zU2-nQqzYgV06b9N3m-B5QO__6rC_oXl1h0="
        return Fernet(fallback_key.encode('utf-8'))

cipher_suite = _get_cipher_suite()

def encrypt_value(value: str | None) -> str | None:
    """Encrypts a string value for safe storage in the database."""
    if not value:
        return None
    return cipher_suite.encrypt(value.encode('utf-8')).decode('utf-8')

def decrypt_value(value: str | None) -> str | None:
    """Decrypts a database-stored string value back into plaintext."""
    if not value:
        return None
    try:
        return cipher_suite.decrypt(value.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logger.warning("Decryption failed. Returning raw value. Ex: %s", e)
        # If decryption fails (e.g. key changed, or legacy unencrypted data), return as is
        return value
