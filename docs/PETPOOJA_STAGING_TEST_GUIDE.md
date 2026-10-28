# Testing Real Petpooja Orders on Staging — Step by Step

This is for you (Adarsh) to follow yourself, first time doing this kind of testing. No
prior Petpooja/API experience assumed. Follow the steps in order.

## What I changed in the code

- The order payload we build now includes a few fields Petpooja's official guide marks
  as **required** that were missing before: `advanced_order`, `enable_delivery`,
  `discount_type`, a customer `address`, and per-item `tax_inclusive`/`gst_liability`.
- A real provider (`RealPetpoojaOrderProvider`) now actually calls Petpooja's real
  `save_order` endpoint — until now, only the local dummy simulation existed.
- Staging and production are meant to be **the same code path** — only the credentials
  in `.env` differ. That's the "just a variable change" you mentioned.

## Step 0 — Confirm the menu actually matches (do this first)

Important thing I found in Petpooja's own sandbox guide: **Petpooja pushes your
restaurant's menu to you**, not the other way around. That means the 35-item menu
(`agent/petpooja/menu_catalogue.json`) with short codes 701–735 that we've been using
is only correct if your Petpooja sandbox restaurant is actually configured with those
exact same items and the exact same IDs.

Before testing orders:
1. Log into the sandbox dashboard (the page in your screenshot).
2. Go to **Menu Management → Menu List**, pick your restaurant, click **Show Menu**.
3. Compare what you see there against `agent/petpooja/menu_catalogue.json`. If the item
   names/IDs don't match, tell me what's actually there and I'll update our catalogue
   to match — sending an order with an item ID Petpooja doesn't recognize will fail.

## Step 1 — `restID` (already have it)

From Ajay's email: **`js51a42pb3`** — the email says this explicitly: *"Map this code on
your end and pass it with the restID object in the order relay."* That's your `restID`.

Don't confuse it with "457540" (the "SIVAPURNA MOBILITY SERVICES LLP" number from
Petpooja's AI assistant) — that's a different field, Petpooja's own internal numeric
restaurant ID (shows up as `restaurantid` elsewhere in their docs), not the `restID` the
order API expects.

## Step 1.5 — Whitelist your IP

Ajay's email asked for your network IP to whitelist it. That's needed for logging into
the dashboard, and likely also for the actual `save_order` API calls from whichever
machine makes them — if you test locally, that's your home/office IP; once this moves to
the VPS later, Petpooja will need the VPS's IP whitelisted too (a separate ask, later).
Go to [whatismyip.com](https://www.whatismyip.com) (or similar) and reply to Ajay's email
with that address before testing, otherwise requests may just time out or get rejected.

## Step 2 & 3 — done already

`.env` (gitignored — never committed, this was safe to do directly) already has the real
`restID`, `app_key`, `app_secret`, `access_token`, and `PETPOOJA_ORDER_PROVIDER=real` set.
`PETPOOJA_SAVE_ORDER_URL`/`5` are left unset on purpose — the code
defaults the first to Petpooja's real staging endpoint, and the second doesn't need a
real value yet (see "What won't work yet" below).

When Petpooja later gives you production credentials: update the three `PETPOOJA_APP_*`
values in `.env` (and `PETPOOJA_REST_ID` if production uses a different one) — that's
the entire staging→production change, nothing else.

## Step 4 — Restart the local agent

Whatever terminal is running `python main.py` inside the `agent/` folder, stop it
(Ctrl+C) and start it again:
```
cd agent
python main.py
```
This is required every time `.env` or the code changes — the running process doesn't
pick up edits on its own.

## Step 5 — Send a real test order to staging

Use the same curl approach we used before (no WhatsApp needed to test this part) — open
`cmd.exe` and run, changing `message_id` each time you retest:

```cmd
curl -X POST http://127.0.0.1:8000/process -H "Content-Type: application/json" -d "{\"media_type\":\"text\",\"message_id\":\"staging-test-1\",\"caption\":\"AP39UX7896, 2 people, 1 Chicken Curry\",\"chat_name\":\"Agent Test\",\"sender\":\"919876500000@s.whatsapp.net\"}"
```

## Step 6 — Check if it actually worked

Three places to look, in order of usefulness:

1. **The curl response itself** — if you get back `{"reply": "✅ Order sent to kitchen..."}`,
   the order was accepted by Petpooja's real staging server. If you instead see a
   `⏳ ... retrying automatically` reply, Petpooja rejected it — see "If it fails" below.
2. **Petpooja's own dashboard → Order Listing page** — search for your restaurant, and
   the order should appear there with the vehicle name as the customer and the items
   you sent. **This is the real proof it worked end-to-end**, not just that our code ran.
3. **Our own Supabase table** (`petpooja_captain_orders`) — `petpooja_status` should say
   `created`, and `petpooja_response` will have Petpooja's real response saved, including
   their own order ID.

## If it fails

The reply/log will say something like `Petpooja save_order rejected: <message> (<code>)`.
Common reasons, cheapest-to-check first:
- **Missing/wrong `restID`** — double check Step 1's value is pasted correctly.
- **Item ID not recognized** — means Step 0's menu check was skipped or something doesn't
  match; tell me the exact error and I'll fix the catalogue.
- **Auth error** (wrong app_key/app_secret/access_token) — re-copy the three values from
  the dashboard screenshot exactly, no extra spaces.

Paste me the exact error text and I'll tell you what it means and fix whatever's on our
side.

## Before going live — Petpooja's 5 required test cases

Ajay's email said Petpooja needs **fulfilled order IDs** for 5 scenarios before they'll
share production credentials:
1. Items + Tax
2. Item with Addons + Tax
3. Item with Variation + Tax
4. Item with Discount + Tax
5. Item with Addon and Variation + Tax

Our current payload sends tax/addons/variations/discounts as empty (no tax master is
configured in our menu, and drivers don't choose addons/variations or get discounts on a
crew-meal order) — so scenarios 2–5 don't happen naturally from a real WhatsApp message.
Once scenario 1 (plain items, which *is* what our normal flow produces) is confirmed
working, come back and we'll figure out how to exercise 2–5 — likely by hand-crafting a
few one-off test payloads rather than changing the real driver-order flow, since those
features don't actually apply to how drivers order. Don't block on this now; it's a
later step for going live, not today's test.

## What won't work yet (expected, not a bug)

Petpooja also calls **us** back for order status updates (accepted/ready/rejected) via
the `callback_url` field, and separately can push menu changes to a "Menu Sharing
Endpoint" we'd configure on their dashboard. Both of those require a **public, internet-
reachable address** for our server — which only exists once this is deployed somewhere
with a real domain (your VPS, later). Until then: the order going out and showing up in
Petpooja's Order Listing page is the correct, complete signal that this piece works.
Status callbacks coming back to us is a separate, later step — not part of today's test.
