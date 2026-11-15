import json
from pathlib import Path
from typing import Optional, Dict, Any

HEROES_FILE = Path(__file__).resolve().parent / "heroes.json"

_HEROES_DATA: Dict[int, Dict[str, Any]] = {}
_NAME_TO_ID: Dict[str, int] = {}

def load_heroes():
    global _HEROES_DATA, _NAME_TO_ID
    if HEROES_FILE.exists():
        with open(HEROES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            _HEROES_DATA = {int(k): v for k, v in raw.items()}
            _NAME_TO_ID = {
                v["localized_name"].lower(): int(k) for k, v in _HEROES_DATA.items()
            }
            # Also add shortened / internal names without "npc_dota_hero_"
            for k, v in _HEROES_DATA.items():
                clean_name = v.get("name", "").replace("npc_dota_hero_", "").lower()
                _NAME_TO_ID[clean_name] = int(k)

load_heroes()

def get_hero_name(hero_id: int) -> str:
    if not _HEROES_DATA:
        load_heroes()
    hero = _HEROES_DATA.get(hero_id)
    return hero["localized_name"] if hero else f"Hero #{hero_id}"

def get_hero_info(hero_id: int) -> Dict[str, Any]:
    if not _HEROES_DATA:
        load_heroes()
    return _HEROES_DATA.get(hero_id, {})

def get_hero_id_by_name(name: str) -> Optional[int]:
    if not _NAME_TO_ID:
        load_heroes()
    return _NAME_TO_ID.get(name.strip().lower())
