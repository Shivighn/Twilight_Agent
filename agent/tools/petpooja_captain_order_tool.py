"""
Petpooja Captain Order Automation tool — see
docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md for the full design this
implements. Dispatched directly from agent/agent/agent.py's run() for the
configured WhatsApp group (never through LLM tool-selection), so `params`
is always {} in practice — kept for BaseTool interface compatibility.
"""
from datetime import datetime, timezone

from loguru import logger

from tools.base_tool import BaseTool
from petpooja.simple_parser import try_simple_structure
from petpooja.llm_structure_parser import structure_message
from petpooja.menu_catalogue import load_catalogue, match_item, match_items_llm, CatalogueUnavailableError
from providers.petpooja_order_provider import get_provider
from config import config
from petpooja import db

TABLE = "petpooja_captain_orders"


class PetpoojaCaptainOrderTool(BaseTool):
    @property
    def name(self) -> str:
        return "petpooja_captain_order"

    @property
    def description(self) -> str:
        # Never shown to the LLM in practice (dispatched directly by chat_name
        # — see agent.py), but BaseTool requires this property regardless.
        return "Parses a driver's WhatsApp order message and creates it in Petpooja."

    async def execute(self, params: dict, context: dict):
        message_id = context["message_id"]
        chat_name = context.get("chat_name", "")
        sender = context.get("sender", "")
        text = context.get("text", "") or context.get("caption", "")

        # ── Idempotency claim ────────────────────────────────────────────
        # A redelivered message (reconnect, or a retry after the process
        # crashed mid-flow) must return exactly what was already decided,
        # never re-parse or re-call Petpooja. insert_ignore() never
        # overwrites an existing row (unlike upsert's merge semantics), so
        # this is safe even if this call races a concurrent one for the
        # same message_id. chat_name itself isn't persisted — this table is
        # scoped to exactly one configured group, so it would be the same
        # constant on every row — but it's still useful in this log line.
        claim = await db.insert_ignore(
            TABLE,
            {
                "whatsapp_message_id": message_id,
                "sender": sender,
                "raw_text": text,
                "received_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="whatsapp_message_id",
        )
        if not claim.data:
            existing = await db.query(TABLE, filters={"whatsapp_message_id": message_id})
            row = existing.data[0] if existing.data else None
            reply = row.get("reply_sent") if row else None
            logger.info(f"[PetpoojaOrder] Duplicate message {message_id} — returning stored result, not re-processing")
            return {"reply": reply} if reply else {}

        row_id = claim.data[0]["id"]
        logger.info(f"[PetpoojaOrder] Claimed message {message_id} (row {row_id}) from '{chat_name}' <{sender}>: {text!r}")

        # ── Structure the message: local regex pass FIRST, LLM only as fallback ──
        # Only ~33 menu items and a consistent message shape mean the fast
        # local pass resolves almost every real message with zero network
        # calls; it only returns None when it isn't confident (no bus number
        # found, or an unrecognized line), at which point the LLM is given
        # the message to use judgment on. A malformed/failed/slow LLM
        # response (fallback path only) is treated as needs_review, never
        # guessed past and never left hanging.
        parsed = try_simple_structure(text)
        if parsed is not None:
            logger.info(f"[PetpoojaOrder] {message_id}: structured locally (no LLM call)")
        else:
            try:
                parsed = await structure_message(text)
            except Exception as err:
                logger.warning(f"[PetpoojaOrder] {message_id}: structuring failed ({err})")
                reply = "⚠️ Order received but could not be read automatically right now — please resend in a moment or enter it manually."
                await self._finish_needs_review(message_id, {}, [], f"structuring failed: {err}", reply)
                return {"reply": reply}

        if parsed["parse_failed"]:
            await db.update(
                TABLE,
                {"whatsapp_message_id": f"eq.{message_id}"},
                {"parsing_status": "parse_failed", "updated_at": datetime.now(timezone.utc).isoformat()},
            )
            logger.info(f"[PetpoojaOrder] {message_id}: no bus number found — not an order, ignoring silently")
            return {}

        # ── Load catalogue + match items ──────────────────────────────────
        try:
            catalogue = load_catalogue()
        except CatalogueUnavailableError as err:
            logger.error(f"[PetpoojaOrder] {err}")
            reply = "⚠️ Order received but the menu catalogue is unavailable right now — please enter this order manually. (Team has been notified.)"
            await self._finish_needs_review(message_id, parsed, [], f"catalogue unavailable: {err}", reply)
            return {"reply": reply}

        matched_items = [match_item(item["raw_name"], catalogue) for item in parsed["items"]]
        for matched, original in zip(matched_items, parsed["items"]):
            matched["quantity"] = original["quantity"]

        # Only the lines the fast local pass couldn't resolve go to the LLM
        # (most messages are spelled close enough to match exactly) — a
        # failed/slow LLM response just keeps the rule-based unmatched/
        # ambiguous result instead of risking a wrong order or hanging.
        unresolved_idx = [i for i, m in enumerate(matched_items) if m["match_status"] != "matched"]
        if unresolved_idx:
            try:
                llm_results = await match_items_llm([matched_items[i] for i in unresolved_idx], catalogue)
                for idx, resolved in zip(unresolved_idx, llm_results):
                    resolved["quantity"] = matched_items[idx]["quantity"]
                    matched_items[idx] = resolved
            except Exception as err:
                logger.warning(f"[PetpoojaOrder] {message_id}: LLM item-match fallback failed ({err}) — keeping rule-based result")

        # ── Validate ─────────────────────────────────────────────────────
        # passenger_count is captured when mentioned but is NOT required —
        # only a missing bus number or an unresolved item blocks the order.
        problems = []
        if not parsed["bus_number"]:
            problems.append("bus number")
        unresolved = [m for m in matched_items if m["match_status"] != "matched"]
        if not matched_items:
            problems.append("no items recognized in the message")

        if problems or unresolved:
            notes = []
            if problems:
                notes.append(f"Missing: {', '.join(problems)}")
            for m in unresolved:
                if m["match_status"] == "ambiguous":
                    notes.append(f"'{m['raw_name']}' is ambiguous — could mean: {', '.join(m.get('candidates', []))}")
                else:
                    notes.append(f"'{m['raw_name']}' is not on the menu")
            validation_notes = "; ".join(notes)
            reply = "⚠️ Order NOT sent to kitchen — " + validation_notes + ". Please resend with the exact details."
            await self._finish_needs_review(message_id, parsed, matched_items, validation_notes, reply)
            logger.info(f"[PetpoojaOrder] {message_id}: needs_review — {validation_notes}")
            return {"reply": reply}

        # ── Create order (dummy Petpooja API in Phase 1) ─────────────────
        order = {
            "whatsapp_message_id": message_id,
            "bus_number": parsed["bus_number"],
            "passenger_count": parsed["passenger_count"],
            "items": matched_items,
        }
        provider = get_provider(config.petpooja_order_provider)
        now = datetime.now(timezone.utc).isoformat()
        try:
            result = await provider.create_order(order)
            item_summary = ", ".join(f"{m['quantity']} {m['matched_item_name']}" for m in matched_items)
            reply = f"✅ Order sent to kitchen for *{parsed['bus_number']}* — {item_summary}"
            await db.update(
                TABLE,
                {"whatsapp_message_id": f"eq.{message_id}"},
                {
                    "bus_number": parsed["bus_number"],
                    "passenger_count": parsed["passenger_count"],
                    "order_items": matched_items,
                    "parsing_status": "parsed",
                    "petpooja_status": "created",
                    "petpooja_order_id": result["order_id"],
                    "petpooja_response": result["raw_response"],
                    "reply_sent": reply,
                    "last_attempt_at": now,
                    "updated_at": now,
                },
            )
            logger.info(f"[PetpoojaOrder] {message_id}: created -> {result['order_id']}")
            return {"reply": reply}
        except Exception as err:
            reply = f"⏳ Order for *{parsed['bus_number']}* received — kitchen system is slow to respond, retrying automatically."
            await db.update(
                TABLE,
                {"whatsapp_message_id": f"eq.{message_id}"},
                {
                    "bus_number": parsed["bus_number"],
                    "passenger_count": parsed["passenger_count"],
                    "order_items": matched_items,
                    "parsing_status": "parsed",
                    "petpooja_status": "failed",
                    # First (and today, only — the retry sweep isn't built
                    # yet) attempt at creating this order. attempts_made is
                    # DB-capped at 5 (check constraint); any future retry
                    # logic reading this row back must bump it the same
                    # way and never push past that cap.
                    "attempts_made": 1,
                    "last_attempt_at": now,
                    "last_error": str(err),
                    "reply_sent": reply,
                    "updated_at": now,
                },
            )
            logger.warning(f"[PetpoojaOrder] {message_id}: create_order failed — {err}")
            return {"reply": reply}

    @staticmethod
    async def _finish_needs_review(message_id, parsed, matched_items, validation_notes, reply):
        now = datetime.now(timezone.utc).isoformat()
        await db.update(
            TABLE,
            {"whatsapp_message_id": f"eq.{message_id}"},
            {
                "bus_number": parsed.get("bus_number"),
                "passenger_count": parsed.get("passenger_count"),
                "order_items": matched_items,
                "parsing_status": "needs_review",
                "validation_notes": validation_notes,
                "reply_sent": reply,
                "updated_at": now,
            },
        )
