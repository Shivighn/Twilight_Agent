

---

## 2. Where This Plugs Into the Existing System

This repo is already split into two services (see `README.md`):

- **Gateway** (`src/`, Node + Baileys) — owns the WhatsApp connection, filters
  to monitored groups, forwards every message to the agent, relays the
  agent's reply back into the chat. Doesn't understand message content.
- **Agent** (`agent/`, Python + FastAPI) — owns understanding. `POST /process`
  receives `{ media_type, message_id, caption, chat_name, sender }` and
  `agent/agent/agent.py::run()` either calls one fixed tool directly (images
  always go to `extract_petty_cash`) or lets an LLM pick a tool from
  `agent/agent/tool_registry.py` (text messages). Each **tool**
  (`agent/tools/*.py`) is a self-contained `BaseTool` that parses, validates,
  writes to Supabase via `agent/db.py`, and returns a result dict. If that
  dict has a `reply` string, the gateway sends it straight back into the
  WhatsApp chat (`src/whatsapp/messageHandler.js`) — no other wiring needed.

This is precisely the extension point the brief asks to reuse. **Petpooja
Captain Order Automation is a new tool, not a new service or a new Node
module.** Concretely:

```
Driver's WhatsApp message
        │
        ▼
Node Gateway (src/) — UNCHANGED
  • isMonitored(chatName) already passes any group listed in
    WA_MONITORED_CHATS through to POST /process
  • message.type === 'chat' branch already forwards
    { message_id, caption, chat_name, sender } and already relays
    outcome.result.reply back into the chat — this is the EXACT
    mechanism set_opening_balance already uses for text replies
        │  HTTP POST /process
        ▼
agent/agent/agent.py :: run()  — ONE NEW BRANCH
  • TODAY: media_type == "image" skips LLM selection and calls
    extract_petty_cash directly (see run(), the first branch)
  • NEW: media_type == "text" AND chat_name == the configured
    Petpooja orders group skips LLM selection the same way and
    calls the new tool directly — deterministic, no LLM routing
    risk, no chance an order message gets mis-classified as a
    petty-cash or opening-balance command
        │
        ▼
agent/tools/petpooja_captain_order_tool.py  — NEW TOOL
  1. Idempotent insert keyed on whatsapp_message_id
  2. Rule-based parse (bus number, passenger count, items)
  3. Menu match against a configurable catalogue
  4. If anything is missing/ambiguous → needs_review, STOP
  5. Else → PetpoojaOrderProvider.create_order() (mock today)
  6. Persist result, return { reply: "..." }
        │
        ▼
Node Gateway sends result.reply back into the WhatsApp group — UNCHANGED
```

**Consequence: zero changes to `src/` are required.** The only Node-side
change is operational — adding the dedicated group name to
`WA_MONITORED_CHATS` (or, if it must never share a list with unrelated
groups, Phase 1 can give it its own env var and `isMonitored()`-equivalent
check; see [§7](#7-configuration--environment-variables)). This satisfies
requirement 1 ("reuse the existing WhatsApp agent and group-monitoring
infrastructure") about as literally as possible, and requirement 6
("isolated module... do not replace or restart unrelated services") because
nothing about the gateway, the scheduled-report modules
(`fleetIssues`/`terminal44`/etc.), or any other tool changes at all.

---

## 3. New Files (Phase 1 — not created by this document)

```
agent/
  tools/
    petpooja_captain_order_tool.py   # the BaseTool — parse/match/validate/persist/call-provider
  petpooja/
    order_parser.py                  # bus number / passenger count / item-line regex parsing
    menu_catalogue.py                # loads + queries the configurable menu catalogue
    menu_catalogue.json              # the catalogue itself — canonical name, aliases, Petpooja itemid
  providers/
    petpooja_order_provider.py       # PetpoojaOrderProvider ABC + MockPetpoojaOrderProvider +
                                      # RealPetpoojaOrderProvider (stub, raises NotImplementedError)
  agent/
    agent.py                         # +1 branch in run() — see §2
  main.py                            # +1 registry.register(...) line
migrations/
  2026-XX-XX_petpooja_captain_orders.sql   # given to the user to run — see standing rule below
```

No existing file's *behavior* changes; `agent.py`/`main.py` each gain a few
additive lines (new branch, new registration), same pattern every prior tool
addition (`set_opening_balance`) already followed.

**Standing project rule, unchanged by this feature:** I do not run SQL
against Supabase or shell commands on the VPS myself. The migration below is
handed to the user to run via the Supabase SQL editor; deployment is scp +
`pm2 restart --update-env`, exactly as every other feature in this repo is
shipped.

---

## 4. Database Design

### Why one table

Requirement 4 explicitly allows a single-table design "if it can be done
simply in 1 table." A message, its parsed order, its items, the Petpooja
response, and the processing/retry state are all **one lifecycle for one
WhatsApp message** — there's no independent entity here that outlives or is
shared across rows, so splitting them into `messages` + `orders` +
`order_items` + `attempts` tables would just be four tables joined back
together on every query, for no real benefit. `order_items` is small and
bounded (a handful of lines per order), so it lives as a `jsonb` array on the
same row — the same trade-off `fleet_issue_notifications` already makes by
folding "notification log" and "delivery state machine" into one table
instead of several (see `migrations/2026-08-12_fleet_issue_agent.sql`).

The **menu catalogue** is deliberately *not* a table in Phase 1. It's
reference data that changes rarely and is edited by a human, not written by
this pipeline — exactly the shape of `config/index.js`'s `escalationContacts`
or `fleetManagers` blocks, just too large to cram into `.env`. A JSON file
(`agent/petpooja/menu_catalogue.json`) is simpler to review in a PR, diff,
and edit than a Supabase table, and nothing here depends on it being queried
with SQL. If the future dashboard needs to let non-engineers edit the menu
without a deploy, promoting it to a `petpooja_menu_items` table is a
backwards-compatible Phase 3 change — the tool only needs its lookup function
changed, not its callers.

### Migration SQL

Run this against the target Supabase branch (stage first, then production),
via the SQL editor or `psql` — safe to re-run (`if not exists` throughout),
same convention as `migrations/2026-08-12_fleet_issue_agent.sql`.

```sql
-- Petpooja Captain Order Automation
-- See docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md for the full design.
-- Current shape, after migrations/2026-10-23_...sql and
-- 2026-10-24_..._schema_update.sql (chat_name dropped — this table is
-- scoped to exactly one configured WhatsApp group, so it was the same
-- constant on every row; vehicle_number renamed to bus_number;
-- parsing_status/petpooja_status converted to enums; provider_mode
-- dropped — written but never read/branched on; attempt_count+max_attempts
-- merged into attempts_made, capped at 5; next_attempt_at dropped since the
-- retry sweep it was for was never built).

create extension if not exists pgcrypto;

create type petpooja_parsing_status_enum as enum
  ('pending', 'parsed', 'needs_review', 'parse_failed');
create type petpooja_order_status_enum as enum
  ('not_submitted', 'pending', 'creating', 'created', 'failed', 'manual_review');

-- One row per WhatsApp message in the dedicated orders group. Doubles as:
--   1. the inbound message log (raw_text/sender/received_at)
--   2. the parsed order (bus_number/passenger_count/order_items)
--   3. the idempotency guard (unique on whatsapp_message_id — a redelivered
--      message, or a retry after a crash mid-flow, can never create a
--      second Petpooja order for the same message)
--   4. the outbox/job queue (petpooja_status + attempts_made below)
--   5. the Petpooja response/audit log (petpooja_order_id/petpooja_response)
create table if not exists petpooja_captain_orders (
  id uuid primary key default gen_random_uuid(),

  -- Idempotency anchor. Required: a message with no id can't be a real
  -- WhatsApp message in this pipeline.
  whatsapp_message_id text not null,
  -- WhatsApp sender JID (group participant, or the chat JID itself for a
  -- 1:1 message) — read from Baileys' raw.key.participant/remoteJid.
  sender text,
  raw_text text not null,
  received_at timestamptz not null default now(),

  -- Parsed order. All nullable — a partially-parsed message is still a
  -- valid row (it just ends up needs_review instead of parsed).
  bus_number text,
  passenger_count integer,

  -- [{ raw_name, quantity, matched_item_id, matched_item_name,
  --    match_status: 'matched'|'ambiguous'|'unmatched', match_confidence }]
  -- One element per item line in the message, in message order.
  order_items jsonb not null default '[]',

  -- 'pending' (just inserted, not parsed yet) | 'parsed' (bus number +
  -- passenger count + every item matched) | 'needs_review' (something's
  -- missing or ambiguous — a human must look at it) | 'parse_failed'
  -- (parser itself threw — message didn't look like an order at all)
  parsing_status petpooja_parsing_status_enum not null default 'pending',
  validation_notes text, -- human-readable reason when needs_review/parse_failed

  -- Petpooja side. 'not_submitted' is the resting state for anything that
  -- never got past parsing (needs_review/parse_failed never reach Petpooja —
  -- requirement 3: flag, never guess).
  petpooja_status petpooja_order_status_enum not null default 'not_submitted',
  petpooja_order_id text,
  petpooja_response jsonb,

  -- Bounded retry / outbox bookkeeping (requirement 5). Hard-capped at 5
  -- by the check constraint below; application code must never write past it.
  attempts_made integer not null default 0
    constraint petpooja_captain_orders_attempts_made_check check (attempts_made >= 0 and attempts_made <= 5),
  last_attempt_at timestamptz,
  last_error text,

  -- What was actually sent back into WhatsApp, for audit/dashboard —
  -- so "what did the driver see" never has to be reconstructed from logs.
  reply_sent text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint petpooja_captain_orders_message_id_key unique (whatsapp_message_id)
);

-- Needs-review queue for the future dashboard / manual follow-up.
create index if not exists petpooja_captain_orders_review_idx
  on petpooja_captain_orders (received_at)
  where parsing_status = 'needs_review';

-- Dashboard's main listing query: "today's orders", newest first — no
-- per-group column needed any more, the whole table is one group.
create index if not exists petpooja_captain_orders_received_idx
  on petpooja_captain_orders (received_at desc);
```

### Why these columns specifically answer requirement 4

- *Incoming messages:* `whatsapp_message_id`, `sender`, `raw_text`,
  `received_at`.
- *Parsed orders:* `bus_number`, `passenger_count`, `parsing_status`,
  `validation_notes`.
- *Order items:* `order_items` (jsonb array, one element per line item,
  including its match outcome).
- *Petpooja order IDs/responses:* `petpooja_order_id`, `petpooja_response`.
- *Processing attempts:* `attempts_made` (capped at 5), `last_attempt_at`,
  `last_error`.
- *Future dashboard/reconciliation:* every field above is queryable directly;
  the two indexes cover the two real query shapes (needs-review queue,
  chronological timeline) without needing a join anywhere.

---

## 5. Processing Flow

### 5.1 Synchronous path (one WhatsApp message)

1. Driver sends a message to the dedicated orders group.
2. Node gateway — `isMonitored()` passes it through, downloads nothing
   (it's `message.type === 'chat'`), `POST /process` with
   `{ media_type: "text", message_id, caption: text, chat_name, sender }`
   (`sender` is the Baileys group participant JID, or the chat JID itself
   for a 1:1 message — see `src/whatsapp/client.js`'s `adaptMessage()`).
3. `agent.py::run()` — chat_name matches the configured orders group →
   call `petpooja_captain_order` tool directly, skip LLM tool-selection
   entirely (same bypass shape the `image` branch already uses).
4. Tool, in order:
   1. **Idempotency insert.** `INSERT ... whatsapp_message_id=... ON CONFLICT
      (whatsapp_message_id) DO NOTHING`, then re-`SELECT` by
      `whatsapp_message_id` either way. If the row already existed (a
      WhatsApp redelivery after a reconnect — the gateway's own `seenIds` set
      in `src/index.js` already guards most of these, but a process restart
      between "received" and "replied" would lose that in-memory set, so the
      DB-level unique constraint is the real guarantee) — **return the
      already-computed `reply_sent` unchanged.** Never re-parse, never call
      Petpooja again for a message already handled. This is the literal
      "never blindly retry... reconcile first" from requirement 5, applied at
      the cheapest possible point: before any work happens at all.
   2. **Parse** (`order_parser.py`, pure regex/rules, no LLM call):
      - Bus number: Indian plate pattern (`[A-Z]{2}\s?\d{1,2}\s?[A-Z]{1,3}\s?\d{4}`),
        normalized the same way T44 bus numbers already are in this repo
        (uppercase, strip spaces — see `normalize_bus_number` in
        `scripts/t44_ac_sales_report.py`, same idea, same reason: "AP39UX7896"
        and "ap 39 ux 7896" must be the same vehicle).
      - Passenger count: looks for an explicit count phrase near "people" /
        "pax" / "driver" / "helper" (requirement 3 excludes onboard
        passengers — only driver + helper headcount counts here, since this
        is a Captain/kitchen order, not a manifest).
      - Item lines: splits the remainder on commas/newlines, each line →
        `{ quantity, raw_name }` via a leading-number pattern
        (`2 Roti` → qty 2; `Chicken Biryani` with no number → qty 1).
      - If the message doesn't parse into *any* bus number — it almost
        certainly isn't an order at all (e.g. chit-chat in the group) —
        `parsing_status = 'parse_failed'`, no reply sent (silently ignored,
        same as any message an existing tool doesn't recognize), done.
   3. **Menu match** (`menu_catalogue.py`), per item:
      - Normalize (lowercase, strip punctuation/plural "s").
      - Exact match against canonical name or any configured alias →
        `matched`.
      - Otherwise, deterministic token-overlap scoring against the
        catalogue; a single candidate clearing the confidence threshold →
        `matched`; more than one clearing it → `ambiguous`; none →
        `unmatched`.
      - Anything still `unmatched`/`ambiguous` after the rule-based pass
        goes to a second, LLM-based pass (`match_items_llm()`, same free
        NVIDIA/OpenRouter chain the petty-cash tool uses) that handles
        misspelled/phonetic item names ("chckn biryni" → Chicken Biryani)
        no fixed alias list could enumerate in advance. It's pinned to the
        catalogue's own ids (can never invent an item), and a failed/bad
        LLM response just keeps the rule-based `unmatched`/`ambiguous`
        result — it never silently guesses.
      - `ambiguous`/`unmatched` items are **never guessed** — requirement 3
        is explicit about this.
   4. **Validate.** If bus number is missing, OR passenger count is
      missing, OR any item is `ambiguous`/`unmatched` →
      `parsing_status = 'needs_review'`, build a specific reply (e.g. "⚠️
      Could not confirm: *Chiken Biryani* (did you mean Chicken Biryani or
      Chicken Biryani Family Pack?) — order NOT sent to kitchen, please
      resend with the exact item name"), persist, return `{ reply }`.
      **Stop — Petpooja is never called for an incomplete/ambiguous order.**
   5. **Create order.** `parsing_status = 'parsed'` →
      `petpooja_status = 'creating'` → call
      `provider.create_order(order)` inside try/except:
      - Success → `petpooja_status = 'created'`, store
        `petpooja_order_id`/`petpooja_response`, reply confirms
        ("✅ Order sent to kitchen for *AP39UX7896* — 1 Chicken Biryani, 2
        Roti").
      - Failure/timeout → `petpooja_status = 'failed'`, `attempts_made`
        incremented (capped at 5 by the DB check constraint — application
        code must mirror that cap, never write past it), `last_error` set.
        If `attempts_made` has reached 5 → `petpooja_status =
        'manual_review'` instead, and the reply says so plainly rather than
        implying it'll silently retry forever. Otherwise the reply says the
        order is queued and will be retried — **not** a bare error, since
        the background sweep genuinely will retry it.
   6. `UPDATE` the row with the final state and `reply_sent`, return
      `{ reply }`.
5. Node gateway (unchanged) sends `result.reply` back into the group.

### 5.2 Background retry sweep

An `asyncio` periodic task started from `agent/main.py`'s FastAPI startup
event (the agent already runs continuously under PM2 — confirmed via
`pm2 list` showing an `intern-agent` process already online — so this needs
no new infrastructure, just a task that's cancelled cleanly on shutdown,
satisfying requirement 6's "graceful startup/shutdown"). Every
`PETPOOJA_RETRY_INTERVAL_SECONDS` (default 120s):

```sql
select * from petpooja_captain_orders
where petpooja_status = 'failed'
  and attempts_made < 5
  and last_attempt_at <= now() - backoff_interval(attempts_made)
order by last_attempt_at
limit 20;
```

(`backoff_interval()` is whatever exponential/fixed backoff function the
sweep implementation picks — there's no `next_attempt_at` column to
pre-compute it into any more, so the sweep derives the "due" check from
`attempts_made`/`last_attempt_at` directly at query time instead.)

For each row: **reconcile before retrying** — call
`provider.get_order_status(row)` first if the provider supports it (the
interface declares this method explicitly for this reason; the mock
provider's version always returns "not found" since it never persisted
anything server-side, so Phase 1's sweep effectively always proceeds to a
plain retry — this becomes load-bearing the moment the real provider lands
in Phase 2, which is exactly why the interface has the method now rather
than being retrofitted later). If reconciliation finds the order already
exists, skip the retry and mark it `created` instead — this is what actually
prevents a duplicate ticket when the *first* attempt's response was lost to
a timeout even though Petpooja received it.

**Known Phase 1 limitation, stated plainly rather than glossed over:** the
agent process has no way to *proactively* push a delayed success/failure
back into WhatsApp today — it can only reply synchronously inside a
`/process` request. A retry that succeeds two minutes after the driver's
original message updates the database correctly, but the driver/kitchen
only finds out if someone checks the (future) dashboard, or the next message
in that chat happens to trigger another reply. Closing this gap cleanly
needs a small new capability — either a tiny HTTP endpoint on the Node
gateway for "push this text into this chat," or a Node-side poller — and is
explicitly **not** part of Phase 1; it's called out here so it isn't
forgotten, not solved.

---

## 6. Provider Interface

```python
# agent/providers/petpooja_order_provider.py
from abc import ABC, abstractmethod

class PetpoojaOrderProvider(ABC):
    @abstractmethod
    async def create_order(self, order: dict) -> dict:
        """Returns { 'order_id': str, 'raw_response': dict }. Raises on failure —
        callers decide retry/backoff, this method never retries internally."""

    @abstractmethod
    async def get_order_status(self, order_row: dict) -> dict | None:
        """Reconciliation hook: best-effort check for whether an order already
        exists server-side for this message, used by the retry sweep BEFORE
        retrying (requirement 5). Returns None if the provider can't answer
        this (e.g. the mock) or genuinely has no record."""


class MockPetpoojaOrderProvider(PetpoojaOrderProvider):
    """Dry-run: logs the would-be payload (mapped per ordersapidummydocs.md's
    shape — subtotal/tax/total arithmetic included, so payload-shape bugs
    surface in Phase 1 testing instead of on Petpooja's real validation),
    returns a fake order id, never calls any network. This is what every
    environment uses until Phase 2's real credentials/API docs are verified."""
    async def create_order(self, order: dict) -> dict:
        ...

    async def get_order_status(self, order_row: dict) -> dict | None:
        return None  # nothing was ever really created — nothing to find


class RealPetpoojaOrderProvider(PetpoojaOrderProvider):
    """Not implemented until the official Petpooja Orders API docs,
    app_key/app_secret/restID, and a verified staging test are all in hand —
    requirement 8. Raises NotImplementedError so selecting it by mistake
    fails loudly instead of silently falling back to mock."""
    async def create_order(self, order: dict) -> dict:
        raise NotImplementedError("Real Petpooja integration pending official API docs")

    async def get_order_status(self, order_row: dict) -> dict | None:
        raise NotImplementedError("Real Petpooja integration pending official API docs")
```

Selected via `PETPOOJA_ORDER_PROVIDER=mock|real` (default `mock`) — the tool
never branches on provider type itself, it only ever calls the interface.
This is what lets Phase 2 swap providers "without changing the business
logic or database schema," per requirement 2.

---

## 7. Configuration / Environment Variables

New `.env.example` block, following this repo's existing convention (header
comment, "off by default", real secrets never in `.env.example`):

```bash
# ─────────────────────────────────────────────
#  Petpooja Captain Order Automation
#  Reads driver order messages from a dedicated WhatsApp group, parses them
#  rule-based (no LLM — see docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md),
#  matches items against a configurable menu catalogue, and creates the
#  order in Petpooja. Runs as a new agent/ tool, not a new service.
# ─────────────────────────────────────────────
# Off by default — same reasoning as every other feature flag in this repo.
PETPOOJA_ORDERS_ENABLED=false

# Must ALSO be added to WA_MONITORED_CHATS so the gateway forwards it at all.
PETPOOJA_ORDERS_WHATSAPP_GROUP_NAME=Captain Orders

# 'mock' until the official API + credentials + a verified test are in hand.
PETPOOJA_ORDER_PROVIDER=mock

# Real credentials — NEVER put real values here, only in .env.
PETPOOJA_APP_KEY=
PETPOOJA_APP_SECRET=
PETPOOJA_REST_ID=
PETPOOJA_API_BASE_URL=https://pos.petpooja.com

# Retry sweep tuning (requirement 5).
PETPOOJA_RETRY_INTERVAL_SECONDS=120
PETPOOJA_ORDER_MAX_ATTEMPTS=5
```

`PETPOOJA_ORDERS_ENABLED=false` means: the tool is registered but its
dedicated-group bypass in `agent.py` checks this flag first — even if someone
accidentally adds the group name to `WA_MONITORED_CHATS` early, nothing fires
until the flag is deliberately flipped. This is the same "config present but
inert" pattern every other feature in this repo uses (e.g.
`MG_FUEL_SAVINGS_ENABLED`).

---

## 8. Failure Scenarios & Handling

| Scenario | Handling |
|---|---|
| Duplicate/redelivered WhatsApp message | Unique `whatsapp_message_id` — second insert finds the existing row, returns its stored `reply_sent` unchanged, never re-calls Petpooja. |
| Message isn't an order at all (chit-chat in the group) | No bus number parses → `parse_failed`, no reply sent — same "silently ignored" behavior as any unrecognized text today. |
| Item name typo / genuinely ambiguous (two menu items both plausible) | `needs_review`, specific reply naming the unclear item(s), Petpooja never called. |
| Menu item genuinely not on the catalogue | `unmatched` → `needs_review` — never created with a guessed item. |
| Petpooja API times out, request may have actually succeeded | Never retried blindly — `get_order_status()` reconciliation is called first on the next sweep pass; only creates if genuinely not found. |
| Petpooja API returns a hard validation error (e.g. unmapped POS item id) | Same bounded-retry path, but a validation error is unlikely to self-resolve on retry — Phase 2 should distinguish retryable (5xx/timeout) from terminal (4xx) failures and send terminal ones straight to `manual_review` instead of burning retry attempts; call out explicitly as a Phase 2 refinement, not assumed now since the real error shapes aren't documented yet. |
| Max retries exhausted | `manual_review`, reply says so plainly, surfaces in the needs-review index/future dashboard. |
| Agent process crashes mid-flow (after insert, before Petpooja call) | Row sits at `parsing_status='parsed'`, `petpooja_status='not_submitted'` — the retry sweep's query should also pick up this state (not only `'failed'`) so a crash never silently drops an order; noted here as a query-shape detail to get right in Phase 1 implementation, not deferred. |
| Supabase briefly unreachable | Tool's DB calls go through `agent/db.py`'s existing client (no new DB-access code) — a request-level failure there surfaces as an exception; the `/process` call fails, FastAPI's existing error handling returns `{"success": false}}`, gateway reacts ❌ on the message (existing behavior in `messageHandler.js`'s catch block) — the driver sees *something* went wrong rather than silence. |
| Menu catalogue file missing/malformed on deploy | Tool refuses to start matching and every order in that run goes to `needs_review` with a clear "catalogue unavailable" note, rather than matching against an empty catalogue (which would mark every single item `unmatched`) — fail loud, not quietly-wrong. |

---

## 9. Security Considerations

- `PETPOOJA_APP_KEY`/`PETPOOJA_APP_SECRET`/`PETPOOJA_REST_ID` are credentials
  — `.env` only, never `.env.example`, same rule as `MG_FUEL_SAVINGS_PASSWORD`
  and every other secret in this repo.
- `agent/db.py`'s existing guardrail (no `DELETE`, no `/rpc/`) applies
  unchanged — this tool only ever `INSERT`/`UPDATE`s one table via the same
  client, nothing new to audit there.
- `sender` (the driver's WhatsApp JID/phone number) is the one real PII field
  this table stores — it's needed to know who sent a given order, and is
  never forwarded to Petpooja (`petpooja_payload.py` sends a placeholder
  customer phone, not `sender`). No other customer names/phones/addresses
  are handled by this pipeline (that's the *inbound Petpooja order's*
  delivery-customer fields per `ordersapidummydocs.md`, and this flow is
  Dine-in/Captain-side, not delivery, so those fields don't apply).
- Once real webhooks are added (Phase 3, outbound status updates from
  Petpooja), they must be signature-verified before being trusted — Petpooja's
  real docs will specify the mechanism; nothing is assumed here.
- The dedicated orders group should be a *closed* group with only drivers
  and relevant staff — the parser has no sender-allowlist today, so anyone in
  that group can create a real kitchen order once Phase 2 is live; worth a
  one-line `PETPOOJA_ORDERS_ENABLED` sanity check before enabling in a shared
  or loosely-moderated group.

---

## 10. Implementation Phases

- **Phase 0 (this document):** architecture + database design only — no
  code, no behavior change. *(This is the current task.)*
- **Phase 1 — dry-run, mock provider only:**
  - Run the migration in §4.
  - Build `order_parser.py`, `menu_catalogue.py` (+ a starter catalogue JSON),
    `petpooja_captain_order_tool.py`, `MockPetpoojaOrderProvider`.
  - Add the `agent.py` dispatch branch + `main.py` registration (additive
    only).
  - `PETPOOJA_ORDERS_ENABLED=false` by default even after deploy; turn on in
    one test environment/group first, verify parsed rows + replies look
    right against real driver messages for a few days, with `PETPOOJA_ORDER_
    PROVIDER=mock` — **no real Petpooja order is ever created in this
    phase.**
- **Phase 2 — real provider:** only once the official Petpooja Orders API
  docs, `app_key`/`app_secret`/`restID`, and a verified staging test exist.
  Implement `RealPetpoojaOrderProvider` behind the same interface; switch
  `PETPOOJA_ORDER_PROVIDER=real` for one outlet/group first (canary), watch
  `petpooja_status`/`last_error` closely before wider rollout. Revisit the
  terminal-vs-retryable error split in [§8](#8-failure-scenarios--handling)
  once real error shapes are known.
- **Phase 3 — dashboard + proactive notifications:** read-only dashboard over
  this same table (no schema change needed — every column was chosen with
  this in mind); closes the "delayed retry result never reaches WhatsApp"
  gap noted in §5.2; webhook ingestion for Petpooja's own outbound status
  updates (Accepted/Food Ready/Dispatched) if the restaurant needs that
  visibility back in the group.

**Rollback at any phase:** set `PETPOOJA_ORDERS_ENABLED=false`, restart —
the table is purely additive (nothing else reads or depends on it), so no
data migration is needed to roll back. Reverting `PETPOOJA_ORDER_PROVIDER`
from `real` to `mock` is likewise a one-line env change + restart, no code
rollback required, since both implement the same interface.

---

## 11. Testing Strategy

This repo has no JS/Python test runner configured yet (`package.json` has no
test script; `agent/requirements.txt` has no `pytest`). Rather than pull in a
new framework for one feature, Phase 1 should add Python's built-in
`unittest` (zero new dependency) for:

- **Parser (`order_parser.py`):** bus-number formats (with/without
  spaces, lowercase), passenger-count phrasing variants, multi-item lines,
  missing-bus-number messages (→ `parse_failed`), trailing punctuation/emoji
  noise.
- **Menu matching (`menu_catalogue.py`):** exact match, alias match,
  deterministic token-overlap match, genuinely ambiguous (two items clear
  threshold) → `ambiguous`, nothing clears threshold → `unmatched`. Because
  the rule-based pass is deterministic (no LLM, no network call), it's fast
  to test exhaustively — every decision is explainable and reproducible.
  The LLM fallback (`match_items_llm()`) is the one place genuinely hard to
  unit-test deterministically (real network call, non-deterministic model
  output); test it by mocking `llm.llm_client.generate` to return both
  well-formed and malformed JSON, confirming the malformed case falls back
  to the rule-based `unmatched`/`ambiguous` result rather than raising past
  the caller.
- **Idempotency:** inserting the same `whatsapp_message_id` twice returns the
  first row's stored reply both times, never calls the provider twice —
  testable against a real Supabase test table or a mocked `db.py`.
- **Retry/backoff:** `attempts_made` incrementing up to its cap of 5, and the
  5th failure's transition to `manual_review`.
- **Provider failures:** `MockPetpoojaOrderProvider` configured to raise, to
  verify the tool's try/except path sets `failed`/bookkeeping correctly
  rather than crashing the whole `/process` request.
- **End-to-end dry run:** a handful of real example driver messages (typos
  and all) run all the way through parse → match → mock-create → reply, with
  the expected `reply` text asserted — this is the main artifact to show
  before enabling `PETPOOJA_ORDERS_ENABLED` against real traffic.

Only after `PETPOOJA_ORDER_PROVIDER=real` is implemented does requirement 8's
"enable real order creation only after the official API documentation,
credentials, and test results are verified" become checkable — that gate is
structural (the provider raises `NotImplementedError`), not just a
convention to remember.
