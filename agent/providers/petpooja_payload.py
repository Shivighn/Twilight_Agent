"""
Maps our internal `order` dict to the EXACT /saveorder request body from
petpooja-api-docs.pdf ("PetpoojaOnlineOrdering APIs", v2.1.0) — the real
official docs, not the earlier unofficial ordersapidummydocs.md guess.
Shared by the dummy-API provider now and the real provider in Phase 2, so
switching providers later only changes WHERE this payload is sent and what
credentials go with it — never how it's built.

Fields chosen as required are exactly the ones the docs mark `required` in
/saveorder's keys table (page 15-18): orderID, preorder_date, preorder_time,
service_charge, sc_tax_amount, dc_tax_percentage, dc_tax_amount,
pc_tax_amount, pc_tax_percentage, order_type, payment_type, created_on,
device_type at the order/top level; id, name, item_tax, item_discount,
price, final_price, quantity per OrderItem.
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
                    }
                },
                "Order": {
                    "details": {
                        "orderID": order["whatsapp_message_id"],
                        "preorder_date": now.strftime("%Y-%m-%d"),
                        "preorder_time": now.strftime("%H:%M:%S"),
                        "service_charge": "0",
                        "sc_tax_amount": "0",
                        "dc_tax_percentage": "0",
                        "dc_tax_amount": "0",
                        "pc_tax_amount": "0",
                        "pc_tax_percentage": "0",
                        "order_type": ORDER_TYPE_DINE_IN,
                        "payment_type": PAYMENT_TYPE_COD,
                        "no_of_persons": str(order.get("passenger_count") or ""),
                        "discount_total": "0",
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
