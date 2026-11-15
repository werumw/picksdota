import json
from pathlib import Path
from typing import Set

SUB_FILE = Path(__file__).resolve().parent / "subscribers.json"

def get_subscribers() -> Set[int]:
    if not SUB_FILE.exists():
        return set()
    try:
        with open(SUB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("subscribers", []))
    except Exception:
        return set()

def add_subscriber(chat_id: int):
    subs = get_subscribers()
    subs.add(chat_id)
    with open(SUB_FILE, "w", encoding="utf-8") as f:
        json.dump({"subscribers": list(subs)}, f, indent=2)

def remove_subscriber(chat_id: int):
    subs = get_subscribers()
    if chat_id in subs:
        subs.remove(chat_id)
        with open(SUB_FILE, "w", encoding="utf-8") as f:
            json.dump({"subscribers": list(subs)}, f, indent=2)

def is_subscribed(chat_id: int) -> bool:
    return chat_id in get_subscribers()
