The **Petpooja Orders API** (part of Petpooja’s open developer platform / POS integration ecosystem) allows third-party platforms—such as food aggregators, custom mobile apps, QR code ordering solutions, websites, and ERPs—to push customer orders directly into the Petpooja POS system and track their status in real time.


---

### Core Architecture & Flow

Petpooja's order integration typically operates as a bidirectional system:

1. **Inbound Orders (Third-Party to Petpooja):** The ordering platform sends a structured JSON payload over HTTPS POST containing order line items, customer details, tax breakdowns, discounts, and payment methods.
2. **Order Relay (Cloud to Desktop POS):** Petpooja’s cloud relay server immediately pushes the ticket to the restaurant’s on-premise local POS client and kitchen display system (KDS) / Kitchen Order Ticket (KOT) printer.
3. **Outbound Status Updates (Webhooks):** As the restaurant accepts, prepares, dispatches, or cancels the order on the POS, Petpooja emits status updates to registered callback/webhook URLs.

---

### Key Capabilities

* **Pushing New Orders:** Direct creation of orders categorized by order type:
* Delivery
* Dine-In
* Takeaway / Pick-up


* **Status Tracking & Updates:**
* Order status changes: *Placed*, *Accepted*, *Food Ready*, *Dispatched*, *Delivered*, *Cancelled*.
* Rider tracking details (rider assigned, phone number, live tracking link).


* **Taxation & Discounts:** Handles multi-tier taxes (CGST, SGST, VAT), packaging charges, delivery fees, and line-item or order-level discounts.
* **Menu Item Mapping:** Matches third-party catalog items to Petpooja using POS Item IDs (`itemid`), variation/addon IDs (`attributeid`), and tax structure IDs.

---

### Authentication & Headers

Petpooja requires specific credentials for each store/restaurant integration:

* **`app_key`** / **`app_secret`**: API application credentials generated via the Petpooja developer portal.
* **`restID`** (Restaurant ID): The unique alphanumeric identifier for the outlet.
* **Content-Type:** `application/json` (or `application/x-www-form-urlencoded` depending on the gateway version).

---

### Typical Payload Structure (`Save Order`)

The payload generally requires the following main blocks:

#### 1. Header & Outlet Information

* `restID`: The Petpooja outlet identifier.
* `order_type`: `1` for Dine-in, `2` for Delivery, `3` for Takeaway (exact codes depend on API version).
* `client_order_id`: The third-party platform’s unique order reference number.

#### 2. Customer & Delivery Information

* `customer_name`: Full name of the diner/customer.
* `customer_phone`: Primary mobile number.
* `customer_address`: Complete delivery address, landmark, and latitude/longitude.

#### 3. Item List (`order_items`)

Array of ordered items containing:

* `itemid`: POS ID corresponding to the menu item.
* `item_name`: Name of the item.
* `price`: Unit base price.
* `quantity`: Number of units ordered.
* `add_on` / `customisations`: Sub-array of selected add-ons/variations with their respective prices and IDs.

#### 4. Pricing, Taxes & Discounts

* `subtotal`: Sum of item prices before taxes and packaging.
* `tax`: Breakdown of taxes (CGST, SGST, service charges).
* `delivery_charges`: Fee for delivery.
* `packing_charges`: Packaging fees.
* `discount`: Discount amount.
* `total`: Final payable amount.

#### 5. Payment Details

* `payment_type`: `Prepaid` or `COD` (Cash on Delivery).
* `payment_mode`: e.g., UPI, Card, Cash, Wallet.

---

### Webhooks & Callbacks

To keep your external app in sync with kitchen operations, Petpooja sends events to your webhook endpoint:

* **Order Accepted:** Kitchen confirms they can fulfill the order.
* **Order Rejected / Cancelled:** Includes reason codes (out of stock, kitchen closed, high rush).
* **Food Ready:** Kitchen has printed KOT and marked food as prepared.
* **Rider Assigned / Dispatched:** Delivery partner update.

---

### Best Practices for Implementation

1. **Menu Synchronization:** Always map menu items using Petpooja’s Menu Fetch API before routing orders; sending unmapped item IDs will lead to order placement failures or POS sync rejections.
2. **Rounding & Decimal Handling:** Ensure currency calculations match Petpooja's required 2-decimal format to prevent payload validation rejections where the sum of items + taxes does not match `total`.
3. **Idempotency:** Always include a persistent `client_order_id` to prevent duplicate ticket generation in the kitchen during network retries.
4. **Offline POS Handling:** Petpooja operates primarily on an offline-first architecture for local store stability; if a store is temporarily offline, orders are queued on the Petpooja cloud and pushed when the desktop client reconnects.