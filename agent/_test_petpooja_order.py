import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.petpooja_captain_order_tool import PetpoojaCaptainOrderTool
import db

TABLE = "petpooja_captain_orders"


async def main():
    tool = PetpoojaCaptainOrderTool()

    cases = [
        ("test-msg-001", "AP39UX7896, 3 people, 1 Chicken Biryani, 2 Roti"),
        ("test-msg-002", "KA01AT9053, 2 pax, 1 Chiken Biryani, water bottle"),  # typo + ambiguous-ish
        ("test-msg-003", "just chatting, nothing to do with an order here"),  # no vehicle -> parse_failed
        ("test-msg-001", "AP39UX7896, 3 people, 1 Chicken Biryani, 2 Roti"),  # duplicate of #1
    ]

    for message_id, text in cases:
        result = await tool.execute({}, {"message_id": message_id, "chat_name": "Agent Test", "text": text})
        print(f"\n--- {message_id} ---\ntext: {text!r}\nresult: {result}")

    print("\n=== Rows now in petpooja_captain_orders for these test ids ===")
    for message_id, _ in cases:
        res = await db.query(TABLE, filters={"whatsapp_message_id": message_id})
        if res.data:
            row = res.data[0]
            print(f"{message_id}: parsing_status={row['parsing_status']} petpooja_status={row['petpooja_status']} "
                  f"vehicle={row['vehicle_number']} items={row['order_items']} reply={row['reply_sent']!r}")
        else:
            print(f"{message_id}: NO ROW (expected for parse_failed case)")


if __name__ == "__main__":
    asyncio.run(main())
