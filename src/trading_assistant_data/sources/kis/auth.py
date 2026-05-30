"""KIS auth value objects.

Token creation is intentionally separate from the read-only client. No order or account
mutation endpoints are exposed in this repo.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KisCredentials:
    base_url: str
    app_key: str
    app_secret: str
    access_token: str

