import os
import base64
from typing import Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from config import settings

class LinkMemoryVault:
    """
    Handles AES-256 Encryption for Link Memory.
    Uses a master key from environment variables (LINK_VAULT_KEY).
    """

    def __init__(self, key: Optional[str] = None):
        # In prod, load from env. For dev/demo, use a placeholder if not set.
        self_key = key or getattr(settings, "LINK_VAULT_KEY", os.environ.get("LINK_VAULT_KEY"))
        if not self_key:
            # Generate a temporary key for dev if missing (WARN: Not for prod)
             self_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
        
        self.key = base64.urlsafe_b64decode(self_key)
        if len(self.key) != 32:
            raise ValueError("LINK_VAULT_KEY must be a 32-byte base64 string")

    def encrypt(self, plain_text: str) -> str:
        nonce = os.urandom(12)
        cipher = Cipher(algorithms.AES(self.key), modes.GCM(nonce), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plain_text.encode()) + encryptor.finalize()
        
        # Format: nonce + tag + ciphertext (base64 encoded)
        combined = nonce + encryptor.tag + ciphertext
        return base64.urlsafe_b64encode(combined).decode()

    def decrypt(self, encrypted_text: str) -> str:
        data = base64.urlsafe_b64decode(encrypted_text)
        nonce = data[:12]
        tag = data[12:28]
        ciphertext = data[28:]
        
        cipher = Cipher(algorithms.AES(self.key), modes.GCM(nonce, tag), backend=default_backend())
        decryptor = cipher.decryptor()
        return (decryptor.update(ciphertext) + decryptor.finalize()).decode()

    def rotate_key(self, user_id: str) -> str:
        """
        Simulate key rotation. 
        In prod, this would update a per-user secret in KMS.
        """
        new_key_b64 = base64.urlsafe_b64encode(os.urandom(32)).decode()
        self.key = base64.urlsafe_b64decode(new_key_b64)
        return new_key_b64

# Singleton instance
try:
    vault = LinkMemoryVault()
except Exception:
    vault = None # Handle case where key is missing gracefully
