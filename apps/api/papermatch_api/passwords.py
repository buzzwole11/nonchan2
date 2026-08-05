"""Password hashing (spec section 24: POST /auth/login).

**scrypt from the standard library**, not a fast hash and not a new dependency. A password
column exists so that a reader can keep their library when they change device; the whole
value of that is lost if the column is one database leak away from being a list of everyone's
passwords.

**The stored string carries its own parameters.** `scrypt$n$r$p$salt$hash`. Cost parameters
get raised over the years, and a verifier that used today's constants to check a hash written
under yesterday's would reject every old password at once — a self-inflicted lockout that
looks exactly like an attack.

**Verification is constant-time and gives one answer.** `verify_password` returns False for a
wrong password, a malformed record, and a user with no password set. Distinguishing those in
the return value would let anyone with a login form enumerate which accounts exist.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

__all__ = ["MIN_PASSWORD_LENGTH", "hash_password", "verify_password"]

#: Interactive-login cost. `n` is the memory/CPU factor; raising it later is safe because the
#: parameters travel with each stored hash.
_N = 2**14
_R = 8
_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32

#: Long enough to matter, short enough not to push people towards writing it down.
#: Section 25 is about not holding what we do not need; a length rule is the one cheap thing
#: that actually helps here.
MIN_PASSWORD_LENGTH = 10


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    """`scrypt$n$r$p$salt$hash`, with a fresh random salt."""
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_BYTES
    )
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, stored: str | None) -> bool:
    """True only when the password produces the stored hash.

    Every failure — no password on the account, a record we cannot parse, a wrong password —
    returns False and nothing else. A caller that could tell them apart would be an account
    enumeration oracle.
    """
    if not stored:
        return False
    try:
        algorithm, n, r, p, salt, expected = stored.split("$")
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_unb64(expected)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, _unb64(expected))
