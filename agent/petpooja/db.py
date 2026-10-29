"""
Supabase data access for petpooja_captain_orders, scoped to its OWN project
(PETPOOJA_SUPABASE_URL/PETPOOJA_SUPABASE_SERVICE_ROLE_KEY) — separate from
the shared ../db.py every other tool uses, because this table was migrated
into a different Supabase project than the one every other feature shares.
Same shape/guardrail as ../db.py (no DELETE, no RPC) — kept as a near-
duplicate rather than parameterizing ../db.py's client, so this feature
stays isolated and nothing about ../db.py's behavior for other tools
changes at all.
"""

import httpx
from loguru import logger
from config import config

_BASE = f"{config.petpooja_supabase_url}/rest/v1"
_HEADERS = {
    "apikey": config.petpooja_supabase_service_role_key,
    "Authorization": f"Bearer {config.petpooja_supabase_service_role_key}",
    "Content-Type": "application/json",
}
_TIMEOUT = 30


class ForbiddenDbActionError(Exception):
    """Raised when this module is asked for a database action it must never do."""


_ALLOWED_METHODS = {"GET", "POST", "PATCH", "HEAD"}


async def _guard_request(request: httpx.Request):
    method = request.method.upper()
    if method not in _ALLOWED_METHODS:
        logger.error(f"[PetpoojaDB GUARD] Blocked {method} {request.url}")
        raise ForbiddenDbActionError(f"Blocked {method} to {request.url.path} — not allowed to delete data")
    if "/rpc/" in request.url.path:
        logger.error(f"[PetpoojaDB GUARD] Blocked RPC call {request.url}")
        raise ForbiddenDbActionError(f"Blocked RPC call to {request.url.path} — not allowed to run server-side functions")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT, event_hooks={"request": [_guard_request]})


class _Result:
    def __init__(self, data):
        self.data = data


async def query(table: str, filters: dict = None, select: str = "*", order: str = None, limit: int = None) -> _Result:
    params = {"select": select}
    for col, val in (filters or {}).items():
        params[col] = f"eq.{val}"
    if order:
        params["order"] = order
    if limit:
        params["limit"] = str(limit)
    async with _client() as client:
        r = await client.get(f"{_BASE}/{table}", headers=_HEADERS, params=params)
        r.raise_for_status()
        return _Result(r.json())


async def insert(table: str, data: dict) -> _Result:
    headers = {**_HEADERS, "Prefer": "return=representation"}
    async with _client() as client:
        r = await client.post(f"{_BASE}/{table}", headers=headers, json=data)
        r.raise_for_status()
        return _Result(r.json())


async def upsert(table: str, data: dict, on_conflict: str) -> _Result:
    headers = {**_HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"}
    async with _client() as client:
        r = await client.post(f"{_BASE}/{table}", headers=headers, params={"on_conflict": on_conflict}, json=data)
        r.raise_for_status()
        return _Result(r.json())


async def update(table: str, filters: dict, patch: dict) -> _Result:
    """PATCH rows matching `filters` (raw PostgREST operators, e.g.
    {"whatsapp_message_id": "eq.xyz"}) with `patch`. Unlike upsert(), this
    is a true partial update — it never re-validates NOT NULL columns the
    caller doesn't mention, because PostgREST's upsert-via-POST path
    re-runs the full INSERT's constraint check even when a conflict would
    resolve it (confirmed: omitting raw_text on a later write failed NOT
    NULL before conflict resolution ever ran). Every write after the
    initial insert_ignore() claim must use this, not upsert()."""
    headers = {**_HEADERS, "Prefer": "return=representation"}
    async with _client() as client:
        r = await client.patch(f"{_BASE}/{table}", headers=headers, params=filters, json=patch)
        r.raise_for_status()
        return _Result(r.json())


async def insert_ignore(table: str, data: dict, on_conflict: str) -> _Result:
    """INSERT, doing nothing if on_conflict's column already has a matching
    row — see ../db.py's insert_ignore for why this (not upsert) is the
    correct idempotency primitive here."""
    headers = {**_HEADERS, "Prefer": "resolution=ignore-duplicates,return=representation"}
    async with _client() as client:
        r = await client.post(f"{_BASE}/{table}", headers=headers, params={"on_conflict": on_conflict}, json=data)
        r.raise_for_status()
        return _Result(r.json())
