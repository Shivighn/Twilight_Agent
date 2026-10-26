import asyncio
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.petpooja_captain_order_tool import PetpoojaCaptainOrderTool
from petpooja import db

TABLE = "petpooja_captain_orders"


async def main():
    tool = PetpoojaCaptainOrderTool()

    cases = [
        ("test-msg-601", "919876500001@s.whatsapp.net", "AP39UX7896, 3 people, 1 Chicken Biryani, 2 Roti"),
        ("test-msg-602", "919876500002@s.whatsapp.net", "KA01AT9053, 2 pax, chickn bryani, 1 water"),  # misspelling -> must resolve via LLM
        ("test-msg-603", "919876500003@s.whatsapp.net", "just chatting, nothing to do with an order here"),  # no bus number -> parse_failed
        ("test-msg-604", "919876500004@s.whatsapp.net", "TN09BZ4521, 2 pax, 1 xyzrandomfood123"),  # genuinely not on menu -> must stay unmatched
        ("test-msg-601", "919876500001@s.whatsapp.net", "AP39UX7896, 3 people, 1 Chicken Biryani, 2 Roti"),  # duplicate of #1
    ]

    for message_id, sender, text in cases:
        result = await tool.execute({}, {"message_id": message_id, "chat_name": "Agent Test", "sender": sender, "text": text})
        print(f"\n--- {message_id} ---\ntext: {text!r}\nresult: {result}")

    print("\n=== Rows now in petpooja_captain_orders for these test ids ===")
    seen = set()
    for message_id, _, _ in cases:
        if message_id in seen:
            continue
        seen.add(message_id)
        res = await db.query(TABLE, filters={"whatsapp_message_id": message_id})
        if res.data:
            row = res.data[0]
            print(f"{message_id}: parsing_status={row['parsing_status']} petpooja_status={row['petpooja_status']} "
                  f"sender={row['sender']} bus={row['bus_number']} attempts_made={row['attempts_made']} "
                  f"items={row['order_items']} reply={row['reply_sent']!r}")
        else:
            print(f"{message_id}: NO ROW (expected for parse_failed case)")


if __name__ == "__main__":
    asyncio.run(main())
