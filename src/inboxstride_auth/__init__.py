"""Central Google OAuth service of the hosted Inboxstride offer (Planung 8.0).

It exchanges authorization codes, keeps the refresh tokens encrypted and hands out short-lived
access tokens to registered Mailhelp instances. It never sees mail content and never writes
calendar entries; every write stays a confirmed action of the instance.
"""
from __future__ import annotations

__all__: list[str] = []
