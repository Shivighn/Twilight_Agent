"""
One-off: send a single real order straight to Petpooja (bypassing WhatsApp
parsing/matching entirely) to confirm the updated payload shape
(AddonItem/description/contact_information/email/latitude/longitude) is
accepted. Uses a known real catalogue item (id 721, Chicken Dum Biryani
Plate, price 245) so there's nothing to mismatch — this isolates the
payload fix from the parsing/matching pipeline, which was already proven
working separately.
"""
import asyncio
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from providers.petpooja_order_provider import get_provider
from config import config


async def main():
    order = {
        "whatsapp_message_id": "3A25F6V6SDF666VS51",
        "bus_number": "TEST8401",
        "passenger_count": 6,
        "items": [
            {"matched_item_id": "821", "matched_item_name": "Chicken Dum Biryani Plate", "price": 245, "quantity": 2},
        ],
    }
    provider = get_provider(config.petpooja_order_provider)
    result = await provider.create_order(order)
    print(f"\n=== create_order result (provider={config.petpooja_order_provider}) ===")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
