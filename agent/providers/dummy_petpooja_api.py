"""
A dummy simulation of Petpooja's real Online Ordering API
(petpooja-api-docs.pdf, v2.1.0) — /saveorder and /orderstatus, matching the
real request/response contracts (including the exact validation-error
shapes) as closely as a local stand-in reasonably can, WITHOUT any real
network call to Petpooja. Mounted into the same FastAPI app (agent/main.py)
under /dummy-petpooja, so it runs with zero new infrastructure.

Why a real HTTP endpoint instead of just an in-process stub (see
MockPetpoojaOrderProvider in petpooja_order_provider.py, which already does
that): this exercises the FULL client code path — building the real
request, a real HTTP round trip, parsing a real response/error body — so
swapping in the real Petpooja base URL + real credentials in Phase 2 is a
config change, not a rewrite. Petpooja's own docs give us this contract (see
their request/response examples below) to simulate against.

In-memory only — orders don't survive a restart. That's fine: the
authoritative record of every order is Supabase (petpooja_captain_orders),
not this dummy server; it only needs to behave consistently for as long as
one process is up.
"""
import random
import re
from datetime import datetime, timezone

from fastapi import APIRouter
from loguru import logger

router = APIRouter()

# clientOrderID -> stored order (for /orderstatus's cancel to find it, and
# so a resubmitted orderID is recognizable instead of silently duplicating —
# the real docs don't document Petpooja's own dedup behavior here, so this
# dummy's choice — "same clientOrderID -> same order, already saved" — is a
# reasonable, documented guess to carry into Phase 2's real integration test.
_orders: dict[str, dict] = {}
_next_petpooja_order_id = 1000


def _validation_error(error_code: str, field: str, message: str) -> dict:
    """Matches petpooja-api-docs.pdf's exact 400 shape for /saveorder."""
    return {
        "success": "0",
        "message": "There were some error in order details." if field != "name" else "There were some error in order item details.",
        "errorCode": error_code,
        "validation_errors": {field: [message]},
    }


@router.post("/saveorder")
async def dummy_save_order(body: dict):
    global _next_petpooja_order_id

    order_details = (
        body.get("orderinfo", {}).get("OrderInfo", {}).get("Order", {}).get("details", {})
    )
    items = (
        body.get("orderinfo", {}).get("OrderInfo", {}).get("OrderItem", {}).get("details", [])
    )
    rest_id = (
        body.get("orderinfo", {}).get("OrderInfo", {}).get("Restaurant", {}).get("details", {}).get("restID", "")
    )

    order_id = order_details.get("orderID")
    if not order_id:
        logger.warning("[DummyPetpooja] /saveorder rejected — missing orderID")
        return _validation_error("SO_105", "orderID", "Please provide order id.")

    preorder_date = order_details.get("preorder_date")
    if preorder_date and re.match(r"^\d{4}-\d{2}-\d{2}$", preorder_date):
        if preorder_date > datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            logger.warning(f"[DummyPetpooja] /saveorder rejected — preorder_date {preorder_date} is in the future")
            return _validation_error("SO_105", "preorder_date", "Preorder date is greater than current date.[Format:Y-m-d]")

    if not items:
        logger.warning("[DummyPetpooja] /saveorder rejected — no order items")
        return _validation_error("SO_106", "name", "Please enter item name.")
    for item in items:
        if not item.get("name"):
            logger.warning("[DummyPetpooja] /saveorder rejected — item missing name")
            return _validation_error("SO_106", "name", "Please enter item name.")

    # Idempotent by our own orderID — a resubmission of the same orderID
    # returns the SAME stored petpooja orderID instead of minting a new one,
    # standing in for whatever real dedup behavior Petpooja's live system has
    # (undocumented in the PDF) until that's verified in Phase 2.
    if order_id in _orders:
        existing = _orders[order_id]
        logger.info(f"[DummyPetpooja] /saveorder — {order_id} already saved as petpooja order {existing['petpooja_order_id']}, not duplicating")
        return {
            "success": "1",
            "message": "Your order is saved.",
            "restID": rest_id,
            "clientOrderID": order_id,
            "orderID": existing["petpooja_order_id"],
        }

    petpooja_order_id = str(_next_petpooja_order_id)
    _next_petpooja_order_id += 1
    _orders[order_id] = {
        "petpooja_order_id": petpooja_order_id,
        "status": "pending",
        "body": body,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"[DummyPetpooja] /saveorder — saved {order_id} -> petpooja order {petpooja_order_id} ({len(items)} item(s))")

    return {
        "success": "1",
        "message": "Your order is saved.",
        "restID": rest_id,
        "clientOrderID": order_id,
        "orderID": petpooja_order_id,
    }


@router.post("/orderstatus")
async def dummy_order_status(body: dict):
    client_order_id = body.get("clientorderID")
    status = body.get("status")

    if not client_order_id:
        return {"success": "0", "message": "There were some error in update order status.", "errorCode": "UOS_105", "validation_errors": ""}

    existing = _orders.get(client_order_id)
    if not existing:
        logger.warning(f"[DummyPetpooja] /orderstatus — unknown clientorderID {client_order_id}")
        return {"success": "0", "message": "There were some error in update order status.", "errorCode": "UOS_105", "validation_errors": ""}

    if status == "-1":
        existing["status"] = "cancelled"
        logger.info(f"[DummyPetpooja] /orderstatus — {client_order_id} cancelled")

    return {
        "success": "1",
        "message": "Order status updated successfully.",
        "restID": body.get("restID", ""),
        "orderID": existing["petpooja_order_id"],
        "status": status,
    }


@router.get("/_debug/orders")
async def dummy_debug_orders():
    """Not part of the real API — a convenience peek at this dummy's
    in-memory state while testing. Intentionally unauthenticated like the
    rest of /dummy-petpooja: this whole router only exists for local
    testing, never reachable from outside localhost in any real deployment."""
    return {"count": len(_orders), "orders": _orders}
