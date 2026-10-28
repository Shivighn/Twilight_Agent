# Petpooja Captain Order — Code Flow, File by File

What actually happens, in order, from a driver's WhatsApp message to an order landing
in Petpooja. Each step names the real file and function — read this alongside the code,
not instead of it.

```
Driver's WhatsApp message
        │
        ▼
src/whatsapp/client.js            (Baileys → our own Message shape)
        │
        ▼
src/whatsapp/messageHandler.js    (filter + forward to agent)
        │  HTTP POST /process
        ▼
agent/main.py                     (FastAPI endpoint)
        │
        ▼
agent/agent/agent.py              (routes to the Petpooja tool, no LLM tool-pick)
        │
        ▼
agent/tools/petpooja_captain_order_tool.py   (the whole pipeline)
        │
        ├─► agent/petpooja/db.py              (idempotency + Supabase reads/writes)
        ├─► agent/petpooja/menu_catalogue.py  (loads menu_catalogue.json)
        ├─► agent/petpooja/llm_order_parser.py (LLM parses + matches items)
        │       └─► agent/llm/llm_client.py   (NVIDIA → OpenRouter fallback)
        └─► agent/providers/petpooja_order_provider.py (creates the order)
                └─► agent/providers/petpooja_payload.py (builds the real request body)
        │
        ▼
Reply bubbles back up through the same chain to WhatsApp
```

## Step 1 — Baileys receives the raw message

**`src/whatsapp/client.js`** — `adaptMessage(raw)`

Baileys hands us a raw, deeply-nested WhatsApp protocol object. This function unwraps it
into a simple shape the rest of the code actually works with: `type`, `body` (the text),
`fromMe`, `id`, and critically `sender` — read from `raw.key.participant` (who actually
sent it, inside a group) or `raw.key.remoteJid` (for a 1:1 chat, where there's no
participant field because the chat JID *is* the sender).

## Step 2 — Filter and forward

**`src/whatsapp/messageHandler.js`** — `handleMessage(message)`

- Skips the bot's own replies (`ownReplyIds` set / zero-width-space marker).
- `isMonitored(chatName)` — only groups listed in `WA_MONITORED_CHATS` get through at
  all. If "Agent Test" (or whatever `PETPOOJA_ORDERS_WHATSAPP_GROUP_NAME` is set to)
  isn't in that list, the message is silently dropped **before it ever reaches the
  agent** — this is the single most common "why isn't anything happening" cause.
- For `message.type === 'chat'` (plain text), it does:
  ```js
  axios.post(`${config.agentService.url}/process`, {
    media_type: 'text', message_id, caption: text, chat_name, sender,
  })
  ```
- Once the agent responds, if `outcome.result.reply` exists, `sendReply(message, reply)`
  sends it straight back into the WhatsApp chat as a quoted reply.

## Step 3 — FastAPI receives it

**`agent/main.py`** — `process(req: ProcessRequest)`

Just unpacks the HTTP body into `agent_run(file_path, media_type, message_id, caption,
chat_name, sender)` and returns whatever comes back. No Petpooja-specific logic lives
here at all — this file doesn't know what Petpooja is.

## Step 4 — Deterministic routing (no LLM involved)

**`agent/agent/agent.py`** — `run(...)`

For `media_type == "text"`, before letting an LLM pick a tool at all, it checks:
```python
if config.petpooja_orders_enabled and chat_name == config.petpooja_orders_whatsapp_group_name:
    tool = registry.get("petpooja_captain_order")
    result = await tool.execute({}, context)
```
This is deliberate — an order message in the configured group can never be
mis-classified as a petty-cash entry or anything else, because the LLM never even sees
it. `context` here is `{file_path, media_type, message_id, caption, chat_name, sender,
text}` — this is the dict every function downstream receives.

## Step 5 — The actual pipeline

**`agent/tools/petpooja_captain_order_tool.py`** — `PetpoojaCaptainOrderTool.execute(params, context)`

This is where almost everything happens, in this exact order:

1. **Idempotency claim** — `db.insert_ignore(TABLE, {whatsapp_message_id, sender,
   raw_text, received_at}, on_conflict="whatsapp_message_id")`
   (`agent/petpooja/db.py`). If a row for this `message_id` already exists, this
   insert is a no-op — the function immediately fetches that existing row and returns
   its already-decided `reply_sent`, **without reparsing or recalling Petpooja**. This
   is what makes a redelivered/duplicate WhatsApp message safe.
2. **Load the menu** — `load_catalogue()` (`agent/petpooja/menu_catalogue.py`) reads
   `menu_catalogue.json` fresh off disk every call (no caching — edit the file, no
   restart needed). If the file is missing/broken, this raises
   `CatalogueUnavailableError` and the row goes straight to `needs_review`.
3. **Parse + match, in one LLM call** — `parse_order_message(text, catalogue)`
   (`agent/petpooja/llm_order_parser.py`). This builds one prompt containing the raw
   driver text *and* the full menu (all 35 items + their ~50 aliases each), and calls
   `generate(prompt)` (`agent/llm/llm_client.py`, which tries NVIDIA's free endpoint
   first, then OpenRouter's free models on failure). The LLM returns one JSON object:
   `{parse_failed, bus_number, passenger_count, items: [{raw_name, quantity,
   matched_item_id, match_status, ...}]}`. There's no regex and no separate
   rule-based matching step any more — this one call does both structuring and
   menu-matching together.
4. **Validate** — if `bus_number` is missing, or any item's `match_status` isn't
   `"matched"`, the row becomes `needs_review` (via `_finish_needs_review`) and a
   specific "⚠️ ... is not on the menu" reply is built. **Petpooja is never called**
   for an incomplete/unmatched order.
5. **Create the order** — `get_provider(config.petpooja_order_provider)`
   (`agent/providers/petpooja_order_provider.py`) returns whichever provider is
   configured (`real`, `dummy_api`, or `mock`), then `provider.create_order(order)`
   is called. For `real` (`RealPetpoojaOrderProvider`):
   - `build_save_order_payload(order, rest_id, callback_url)`
     (`agent/providers/petpooja_payload.py`) turns our internal order dict into the
     exact nested `orderinfo.OrderInfo.{Restaurant,Customer,Order,OrderItem,Tax,
     Discount}` JSON body Petpooja's API expects.
   - `app_key`/`app_secret`/`access_token` get attached on top (these are
     credentials, not order data, so they're added by the provider, not baked into
     the payload builder — this is exactly what makes swapping staging→production
     later just a `.env` change).
   - `httpx.AsyncClient().post(self.base_url, json=payload)` — the real HTTP call to
     Petpooja's `save_order` endpoint.
   - If `body["success"] != "1"`, this raises `RuntimeError` with Petpooja's own
     error message/code — caught by the `try/except` in `execute()`, which marks the
     row `failed` and replies "⏳ ... retrying automatically" (no actual retry sweep
     exists yet — that's a documented future-phase gap, not a bug).
6. **Persist the final state** — `db.update(TABLE, {whatsapp_message_id: ...}, {...})`
   writes `parsing_status`, `petpooja_status`, `petpooja_order_id`,
   `petpooja_response`, `reply_sent`, etc. back to the `petpooja_captain_orders` table
   (its own dedicated Supabase project — see `agent/petpooja/db.py`'s docstring for why).
7. Returns `{"reply": "..."}` (or `{}` for silently-ignored non-order chit-chat).

## Step 6 — Reply goes back out

The `{"reply": "..."}` dict bubbles back up through `agent/agent/agent.py` →
`agent/main.py`'s HTTP response → `src/whatsapp/messageHandler.js`'s `sendReply()` →
the actual WhatsApp message the driver sees.

## The one config flag that controls staging vs. dummy vs. mock

`PETPOOJA_ORDER_PROVIDER` in `.env` — read in `agent/config.py`, consumed by
`get_provider()` at the bottom of `agent/providers/petpooja_order_provider.py`:
- `real` → `RealPetpoojaOrderProvider` (what we're using now — hits Petpooja's actual
  staging server; swapping to production later is just updating the credential values
  in `.env`, this code path doesn't change).
- `dummy_api` (old default) → `DummyApiPetpoojaOrderProvider` — our own local FastAPI
  simulation of Petpooja's API shape (`agent/providers/dummy_petpooja_api.py`), for
  testing without hitting any real server.
- `mock` → `MockPetpoojaOrderProvider` — no network call at all, logs the payload and
  returns a fake order ID. Used for fast unit tests.

## Where the data lives

One Supabase table, `petpooja_captain_orders` (its own dedicated project, not the one
every other feature in this repo shares — see `agent/petpooja/db.py`). One row per
WhatsApp message: the raw text, who sent it, the parsed bus number/passenger
count/items, the validation outcome, and (if it got that far) Petpooja's own order ID
and full response. `docs/PETPOOJA_CAPTAIN_ORDER_AUTOMATION.md` has the full schema and
the original design rationale if you want more depth than this file covers.
