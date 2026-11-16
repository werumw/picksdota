import time
import logging
import requests
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class LiveMatchTracker:
    OPENDOTA_LIVE_URL = "https://api.opendota.com/api/live"

    @classmethod
    def get_live_matches(cls, stratz_client=None) -> List[Dict[str, Any]]:
        """Возвращает список всех активных матчей (турнирные + pro паблики)."""
        matches = []
        seen_ids = set()

        # 1. Запрос в OpenDota /api/live
        try:
            resp = requests.get(cls.OPENDOTA_LIVE_URL, timeout=18)
            if resp.status_code == 200:
                raw_games = resp.json()
                for g in raw_games:
                    mid = g.get("match_id")
                    if not mid or mid in seen_ids:
                        continue

                    lid = g.get("league_id", 0) or 0
                    rad_name = (g.get("team_name_radiant") or "").strip()
                    dire_name = (g.get("team_name_dire") or "").strip()
                    avg_mmr = g.get("average_mmr", 0) or 0
                    spectators = g.get("spectators", 0) or 0

                    is_tournament = (lid > 0) or bool(rad_name and dire_name)
                    is_pro_pub = (avg_mmr >= 7000 or spectators >= 15)

                    if not (is_tournament or is_pro_pub):
                        continue

                    players = g.get("players", [])
                    picked_heroes = [p for p in players if p.get("hero_id")]
                    game_time = g.get("game_time", 0) or 0

                    # Формируем стандартизированный список игроков
                    formatted_players = []
                    for p in players:
                        is_rad = (p.get("team") == 0)
                        formatted_players.append({
                            "steamAccountId": p.get("account_id"),
                            "account_id": p.get("account_id"),
                            "heroId": p.get("hero_id"),
                            "hero_id": p.get("hero_id"),
                            "name": p.get("name") or f"Player {p.get('account_id')}",
                            "team": p.get("team"),
                            "isRadiant": is_rad,
                            "kills": p.get("kills", 0),
                            "deaths": p.get("deaths", 0),
                            "assists": p.get("assists", 0),
                        })

                    # Название команд
                    if not rad_name:
                        rad_name = f"Radiant (MMR {avg_mmr})" if avg_mmr else "Radiant"
                    if not dire_name:
                        dire_name = f"Dire (MMR {avg_mmr})" if avg_mmr else "Dire"

                    match_type = "tournament" if is_tournament else "high_mmr_pub"

                    matches.append({
                        "match_id": mid,
                        "id": mid,
                        "league_id": lid,
                        "radiant_name": rad_name,
                        "dire_name": dire_name,
                        "radiantTeam": {"name": rad_name},
                        "direTeam": {"name": dire_name},
                        "radiant_score": g.get("radiant_score", 0),
                        "dire_score": g.get("dire_score", 0),
                        "game_time": game_time,
                        "picked_count": len(picked_heroes),
                        "is_drafting": (len(picked_heroes) < 10 and game_time <= 60),
                        "draft_complete": (len(picked_heroes) == 10),
                        "players": formatted_players,
                        "match_type": match_type,
                        "spectators": spectators,
                        "avg_mmr": avg_mmr,
                        "source": "opendota"
                    })
                    seen_ids.add(mid)

        except Exception as e:
            logger.error(f"Ошибка получения live матчей из OpenDota: {e}")

        # 2. STRATZ fallback (если есть клиент и OpenDota пуста)
        if not matches and stratz_client:
            try:
                stratz_live = stratz_client.get_live_matches(50)
                for sm in stratz_live:
                    mid = sm.get("matchId")
                    if not mid or mid in seen_ids:
                        continue
                    rad_name = sm.get("radiantTeam", {}).get("name", "Radiant")
                    dire_name = sm.get("direTeam", {}).get("name", "Dire")
                    players = sm.get("players", [])
                    picked = [p for p in players if p.get("heroId")]
                    matches.append({
                        "match_id": mid,
                        "id": mid,
                        "league_id": sm.get("leagueId", 0),
                        "radiant_name": rad_name,
                        "dire_name": dire_name,
                        "radiantTeam": {"name": rad_name},
                        "direTeam": {"name": dire_name},
                        "radiant_score": 0,
                        "dire_score": 0,
                        "game_time": 0,
                        "picked_count": len(picked),
                        "is_drafting": (len(picked) < 10),
                        "draft_complete": (len(picked) == 10),
                        "players": players,
                        "match_type": "tournament",
                        "source": "stratz"
                    })
                    seen_ids.add(mid)
            except Exception as e:
                logger.error(f"STRATZ live fallback error: {e}")

        # Сортируем: сначала турнирные с завершенным драфтом, затем остальные
        matches.sort(key=lambda m: (
            1 if m["match_type"] == "tournament" else 0,
            1 if m["draft_complete"] else 0,
            m.get("spectators", 0)
        ), reverse=True)

        return matches

    @classmethod
    def match_teams(cls, scheduled_names: List[str], live_name: str) -> bool:
        """Нечеткое сопоставление названия команд."""
        live_norm = live_name.lower().replace(" ", "").replace("-", "").replace(".", "")
        for s in scheduled_names:
            if not s:
                continue
            s_norm = s.lower().replace(" ", "").replace("-", "").replace(".", "")
            if len(s_norm) >= 3 and (s_norm in live_norm or live_norm in s_norm):
                return True
            # Аббревиатуры (например "gl" -> "gaimingladiators")
            if s_norm == "gl" and "gladiator" in live_norm:
                return True
            if s_norm == "tspirit" and "spirit" in live_norm:
                return True
            if s_norm == "pari" and "pari" in live_norm:
                return True
            if s_norm == "dkonca" and "konca" in live_norm:
                return True
            if s_norm == "chero" and "cyber" in live_norm:
                return True
        return False

    @classmethod
    def find_match_by_teams(cls, team1_names: List[str], team2_names: List[str], live_matches: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Ищет live-матч среди запущенных по названиям команд."""
        for m in live_matches:
            r_name = m["radiant_name"]
            d_name = m["dire_name"]
            # Вариант 1: team1 -> radiant, team2 -> dire
            if cls.match_teams(team1_names, r_name) and cls.match_teams(team2_names, d_name):
                return m
            # Вариант 2: team2 -> radiant, team1 -> dire
            if cls.match_teams(team2_names, r_name) and cls.match_teams(team1_names, d_name):
                return m
        return None
