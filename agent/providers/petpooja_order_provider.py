"""
PetpoojaOrderProvider interface — see
docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md section 6. The tool only ever
calls this interface, never branches on provider type, so swapping
dummy_api -> real later changes zero business logic.
"""
import random
import string
from abc import ABC, abstractmethod

import httpx
from loguru import logger

from config import config
from providers.petpooja_payload import build_save_order_payload


class PetpoojaOrderProvider(ABC):
    @abstractmethod
    async def create_order(self, order: dict) -> dict:
        """order: { whatsapp_message_id, bus_number, passenger_count, items:
        [{quantity, matched_item_id, matched_item_name, price}] }. Returns
        { order_id: str, raw_response: dict }. Raises on failure — callers
        decide retry/backoff, this method never retries internally."""

    @abstractmethod
    async def get_order_status(self, order_row: dict) -> dict | None:
        """Reconciliation hook used by the retry sweep BEFORE retrying (never
        blindly retry — see design doc section 5.2). Returns None if this
        provider can't answer or genuinely has no record.

        NOTE: the real Petpooja API (petpooja-api-docs.pdf) has no polling
        "get order status" endpoint at all — reconciliation on the real
        system happens via Petpooja calling OUR /callback webhook, not us
        polling them. Phase 2 will need to rethink retry-before-reconcile
        around that fact rather than this method as currently shaped."""


class MockPetpoojaOrderProvider(PetpoojaOrderProvider):
    """Pure in-process dry-run — no network at all, deterministic, for unit
    tests (see design doc section 11). Use DummyApiPetpoojaOrderProvider
    instead for anything that should exercise a real HTTP round trip."""

    async def create_order(self, order: dict) -> dict:
        payload = build_save_order_payload(order, rest_id="MOCK-REST-ID")
        fake_order_id = "MOCK-" + "".join(random.choices(string.digits, k=8))
        logger.info(f"[PetpoojaMock] create_order (dry-run, no HTTP call) -> {fake_order_id}\n{payload}")
        return {"order_id": fake_order_id, "raw_response": {"mock": True, "payload": payload}}

    async def get_order_status(self, order_row: dict) -> dict | None:
        return None


class DummyApiPetpoojaOrderProvider(PetpoojaOrderProvider):
    """Calls our own local dummy simulation of Petpooja's real /saveorder +
    /orderstatus (agent/providers/dummy_petpooja_api.py, mounted at
    /dummy-petpooja in agent/main.py) over real HTTP, using the exact
    payload shape from petpooja-api-docs.pdf. This is what
    PETPOOJA_ORDER_PROVIDER=dummy_api selects — the default while testing
    the pipeline end-to-end, before real Petpooja credentials exist."""

    def __init__(self):
        self.base_url = config.petpooja_dummy_api_base_url
        self.rest_id = config.petpooja_rest_id or "DUMMY-REST-ID"

    async def create_order(self, order: dict) -> dict:
        payload = build_save_order_payload(order, rest_id=self.rest_id)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/saveorder", json=payload)
            body = resp.json()

        if body.get("success") != "1":
            # Real /saveorder's 400 shape (errorCode + validation_errors) —
            # surfaced as the exception message so the tool's failed-state
            # bookkeeping (last_error) is actually useful to read later.
            raise RuntimeError(f"Petpooja save_order rejected: {body.get('message')} ({body.get('errorCode')}) {body.get('validation_errors')}")

        logger.info(f"[PetpoojaDummyApi] create_order -> petpooja orderID {body['orderID']} (client {body['clientOrderID']})")
        return {"order_id": body["orderID"], "raw_response": body}

    async def get_order_status(self, order_row: dict) -> dict | None:
        # See the ABC docstring above — the real API has no such endpoint,
        # and the dummy intentionally doesn't invent one it would have to
        # un-invent later. The dummy's /_debug/orders is for manual
        # inspection only, not meant to be relied on by application code.
        return None


class RealPetpoojaOrderProvider(PetpoojaOrderProvider):
    """Not implemented until real app_key/app_secret/access_token and a
    verified staging test against Petpooja's actual servers are all in hand
    (requirement 8). Raises loudly rather than silently falling back to the
    dummy."""

    async def create_order(self, order: dict) -> dict:
        raise NotImplementedError("Real Petpooja integration pending verified staging credentials")

    async def get_order_status(self, order_row: dict) -> dict | None:
        raise NotImplementedError("Real Petpooja integration pending verified staging credentials")


def get_provider(provider_mode: str) -> PetpoojaOrderProvider:
    if provider_mode == "real":
        return RealPetpoojaOrderProvider()
    if provider_mode == "mock":
        return MockPetpoojaOrderProvider()
    return DummyApiPetpoojaOrderProvider()
