"""
PetpoojaOrderProvider interface — see
docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md section 6. The tool only ever
calls this interface, never branches on provider type, so swapping
mock -> real later changes zero business logic.
"""
import random
import string
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from loguru import logger


class PetpoojaOrderProvider(ABC):
    @abstractmethod
    async def create_order(self, order: dict) -> dict:
        """order: { vehicle_number, passenger_count, items: [{quantity, matched_item_id,
        matched_item_name}] }. Returns { order_id: str, raw_response: dict }. Raises on
        failure — callers decide retry/backoff, this method never retries internally."""

    @abstractmethod
    async def get_order_status(self, order_row: dict) -> dict | None:
        """Reconciliation hook used by the retry sweep BEFORE retrying (never
        blindly retry — see design doc section 5.2). Returns None if this
        provider can't answer or genuinely has no record."""


class MockPetpoojaOrderProvider(PetpoojaOrderProvider):
    """Dry-run: never calls any network. Maps the order into the shape
    ordersapidummydocs.md describes (so payload-shape bugs surface now,
    against a real-looking structure, instead of only once the real API
    exists), logs it, and returns a fake order id. This is what every
    environment uses until Phase 2's real credentials/API docs are verified."""

    async def create_order(self, order: dict) -> dict:
        payload = self._build_dummy_payload(order)
        fake_order_id = "MOCK-" + "".join(random.choices(string.digits, k=8))
        logger.info(f"[PetpoojaMock] create_order (dry-run, not sent anywhere) -> {fake_order_id}\n{payload}")
        return {
            "order_id": fake_order_id,
            "raw_response": {"mock": True, "payload": payload, "status": "dry_run_created"},
        }

    async def get_order_status(self, order_row: dict) -> dict | None:
        return None  # nothing was ever really created server-side — nothing to find

    @staticmethod
    def _build_dummy_payload(order: dict) -> dict:
        """Mirrors ordersapidummydocs.md's "Save Order" shape as closely as a
        dummy/unofficial doc allows — restID/order_type/client_order_id header,
        order_items array, subtotal/tax/total block. Real field names will be
        verified against Petpooja's official docs before Phase 2."""
        items = [
            {
                "itemid": item["matched_item_id"],
                "item_name": item["matched_item_name"],
                "price": item.get("price", 0),
                "quantity": item["quantity"],
            }
            for item in order["items"]
        ]
        subtotal = sum(i["price"] * i["quantity"] for i in items)
        return {
            "restID": "DUMMY-REST-ID",
            "order_type": 1,  # Dine-in, per ordersapidummydocs.md
            "client_order_id": order["whatsapp_message_id"],
            "customer_name": f"Vehicle {order['vehicle_number']}",
            "order_items": items,
            "subtotal": round(subtotal, 2),
            "tax": 0,
            "total": round(subtotal, 2),
            "payment_type": "COD",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


class RealPetpoojaOrderProvider(PetpoojaOrderProvider):
    """Not implemented until the official Petpooja Orders API docs,
    app_key/app_secret/restID, and a verified staging test are all in hand
    (requirement 8). Raises loudly rather than silently falling back to mock."""

    async def create_order(self, order: dict) -> dict:
        raise NotImplementedError("Real Petpooja integration pending official API docs")

    async def get_order_status(self, order_row: dict) -> dict | None:
        raise NotImplementedError("Real Petpooja integration pending official API docs")


def get_provider(provider_mode: str) -> PetpoojaOrderProvider:
    if provider_mode == "real":
        return RealPetpoojaOrderProvider()
    return MockPetpoojaOrderProvider()
