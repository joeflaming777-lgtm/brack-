"""
Password hashing using Argon2id.
"""
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

ph = PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # 64 MB
    parallelism=2,
    hash_len=32,
    salt_len=16,
)


def hash_password(plain: str) -> str:
    """Hash a password using Argon2id."""
    return ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its hash. Returns False on mismatch."""
    try:
        return ph.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """Check if the hash needs to be upgraded."""
    return ph.check_needs_rehash(hashed)
