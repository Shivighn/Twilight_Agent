"""
Maps our internal `order` dict to the Save Order API request body — built
from two official Petpooja docs: petpooja-api-docs.pdf ("PetpoojaOnlineOrdering
APIs", v2.1.0, the full nested orderinfo.OrderInfo wire structure with
device_type/udid) and "API Guide for Placing Orders on Petpooja POS" (the
later field-reference guide covering the SAME save_order endpoint, which
confirmed several required fields the first draft of this file didn't yet
have: advanced_order, enable_delivery, discount_type, Customer.address,
and per-item tax_inclusive/gst_liability/variation_id/variation_name).
Nesting follows the first (detailed) doc; field completeness follows the
second (the later guide never shows a full combined payload, just field
tables, so it doesn't contradict the nesting — only adds fields the first
draft was missing). Shared by the dummy-API provider and the real
staging/production provider, so switching providers only changes WHERE
this payload is sent and which credentials go with it — never how it's
built.
"""
from datetime import datetime, timezone

# This Captain-order flow is always a restaurant-floor order, not an
# aggregator delivery — Dine In ("D") and Cash on Delivery are the only
# sensible defaults until there's a real reason to vary them per message.
ORDER_TYPE_DINE_IN = "D"
PAYMENT_TYPE_COD = "COD"
DEVICE_TYPE = "Web"  # docs: "Default: Web (case sensitive)"


def build_save_order_payload(order: dict, rest_id: str, callback_url: str = "") -> dict:
    """
    order: { whatsapp_message_id, bus_number, passenger_count,
             items: [{quantity, matched_item_id, matched_item_name, price}] }
    Returns the full /saveorder JSON body (minus app_key/app_secret/
    access_token, which the caller attaches — those are credentials, not
    order data, and differ between the dummy and real providers).
    """
    now = datetime.now(timezone.utc)

    order_items = []
    for item in order["items"]:
        unit_price = float(item.get("price") or 0)
        quantity = int(item["quantity"])
        order_items.append({
            "id": str(item["matched_item_id"]),
            "name": item["matched_item_name"],
            "item_tax": [],  # no tax master configured for this starter catalogue (see menu_catalogue.json)
            "item_discount": "0",
            "price": f"{unit_price:.2f}",
            "final_price": f"{unit_price * quantity:.2f}",
            "quantity": str(quantity),
            # Required per the later field-reference guide, missing from
            # the first draft: prices here exclude tax (tax_total is "0"
            # below — no tax master configured), and this is an internal
            # crew-meal order the restaurant itself absorbs, not a vendor.
            "tax_inclusive": False,
            "gst_liability": "restaurant",
            "variation_name": "",
            "variation_id": "",
        })

    order_total = sum(float(i["final_price"]) for i in order_items)

    return {
        "orderinfo": {
            "OrderInfo": {
                "Restaurant": {
                    "details": {
                        "res_name": "Twilight T44 Captain Orders",
                        "restID": rest_id,
                    }
                },
                "Customer": {
                    "details": {
                        "name": f"Vehicle {order['bus_number']}",
                        "phone": "0000000000",  # no real customer phone in a Captain-order message
                        # Required per the later field-reference guide, missing from
                        # the first draft — this is a Dine-in/pickup order at the
                        # restaurant itself, not a delivery, so the restaurant's own
                        # location stands in for a real customer address.
                        "address": "Terminal 44, Hyderabad",
                    }
                },
                "Order": {
                    "details": {
                        "orderID": order["whatsapp_message_id"],
                        "preorder_date": now.strftime("%Y-%m-%d"),
                        "preorder_time": now.strftime("%H:%M:%S"),
                        # "N": this is an immediate order, not booked ahead of time.
                        "advanced_order": "N",
                        "service_charge": "0",
                        "sc_tax_amount": "0",
                        "dc_tax_percentage": "0",
                        "dc_tax_amount": "0",
                        "pc_tax_amount": "0",
                        "pc_tax_percentage": "0",
                        "order_type": ORDER_TYPE_DINE_IN,
                        "payment_type": PAYMENT_TYPE_COD,
                        # 0 = third-party rider — doesn't really apply to a Dine-in
                        # order, but the field is marked required either way.
                        "enable_delivery": "0",
                        "no_of_persons": str(order.get("passenger_count") or ""),
                        "discount_total": "0",
                        "discount_type": "F",
                        "tax_total": "0",
                        "total": f"{order_total:.2f}",
                        "description": f"Captain order via WhatsApp — message {order['whatsapp_message_id']}",
                        "created_on": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "callback_url": callback_url,
                    },
                },
                "OrderItem": {"details": order_items},
                "Tax": {"details": []},
                "Discount": {"details": []},
            }
        },
        "udid": "",
        "device_type": DEVICE_TYPE,
    }
