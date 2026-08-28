"""Versioned stdlib scrypt password hashes and a stdin-only generator."""

from __future__ import annotations

import base64
import hashlib
import secrets
import sys

N, R, P, DKLEN = 32768, 8, 1, 32


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=N, r=R, p=P, dklen=DKLEN,
        maxmem=64 * 1024 * 1024,
    )
    return ".".join(("scrypt", "v1", str(N), str(R), str(P), _encode(salt), _encode(digest)))


def verify_password(password: str, encoded: str) -> bool:
    try:
        name, version, n, r, p, salt, expected = encoded.split(".")
        if (name, version) != ("scrypt", "v1"):
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=_decode(salt), n=int(n), r=int(r), p=int(p),
            dklen=len(_decode(expected)), maxmem=64 * 1024 * 1024,
        )
        return secrets.compare_digest(actual, _decode(expected))
    except (ValueError, TypeError):
        return False


def main() -> int:
    if sys.argv[1:] != ["hash-stdin"]:
        print("usage: python -m src.duesoon.auth.passwords hash-stdin", file=sys.stderr)
        return 2
    password = sys.stdin.read().rstrip("\r\n")
    print(hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
