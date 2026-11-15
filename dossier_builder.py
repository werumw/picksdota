from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from hero_helper import get_hero_name, get_hero_info

class MatchDossierBuilder:
    def __init__(self, stratz_client=None):
        self.stratz = stratz_client

    def build_player_summary(self, player_data: Dict[str, Any], is_pro_enrichment: bool = True) -> Dict[str, Any]:
        """Собирает глубокую карточку игрока: герой, комфорт, недавняя форма."""
        steam_id = player_data.get("steamAccountId") or player_data.get("account_id")
        hero_id = player_data.get("heroId") or player_data.get("hero_id")
        hero_name = get_hero_name(hero_id) if hero_id else "Unknown Hero"
        hero_info = get_hero_info(hero_id) if hero_id else {}

        # Имя игрока
        steam_acc = player_data.get("steamAccount") or {}
        pro_acc = steam_acc.get("proSteamAccount") or {}
        player_name = pro_acc.get("name") or steam_acc.get("name") or player_data.get("name") or player_data.get("personaname") or f"Player {steam_id}"
        real_name = pro_acc.get("realName")

        kills = player_data.get("kills", 0)
        deaths = player_data.get("deaths", 0)
        assists = player_data.get("assists", 0)
        imp = player_data.get("imp")
        role = player_data.get("role")
        lane = player_data.get("lane")

        summary = {
            "steam_id": steam_id,
            "player_name": player_name,
            "real_name": real_name,
            "hero_name": hero_name,
            "hero_roles": hero_info.get("roles", []),
            "primary_attr": hero_info.get("primary_attr"),
            "role": role,
            "lane": lane,
            "kda": f"{kills}/{deaths}/{assists}" if (kills or deaths or assists) else None,
            "imp": imp,
            "hero_mastery": {
                "match_count": "N/A",
                "winrate": "N/A",
                "avg_kda": "N/A",
                "avg_imp": "N/A"
            },
            "recent_form": {
                "matches_analyzed": 0,
                "winrate": "N/A",
                "is_active_hero": False,
                "recent_kda": "N/A"
            }
        }

        # Обогащение через STRATZ (глубокий анализ истории аккаунта)
        if is_pro_enrichment and self.stratz and steam_id and hero_id:
            try:
                # 1. Сигнатурность героя
                hero_perf = self.stratz.get_player_hero_performance(steam_id, hero_id)
                if hero_perf and hero_perf.get("matchCount"):
                    mc = hero_perf["matchCount"]
                    wc = hero_perf.get("winCount", 0)
                    wr = round((wc / mc) * 100, 1) if mc > 0 else 0
                    kda = round(hero_perf.get("kDA", 0), 2)
                    summary["hero_mastery"] = {
                        "match_count": mc,
                        "winrate": f"{wr}%",
                        "avg_kda": kda,
                        "avg_imp": hero_perf.get("imp")
                    }

                # 2. Недавняя форма (последние игры)
                recent = self.stratz.get_player_recent_matches(steam_id, take=15)
                if recent:
                    rec_wins = sum(1 for m in recent if m.get("is_victory"))
                    rec_total = len(recent)
                    recent_hero_ids = [m.get("hero_id") for m in recent]
                    tot_k = sum(m.get("kills", 0) for m in recent)
                    tot_d = sum(m.get("deaths", 0) for m in recent)
                    tot_a = sum(m.get("assists", 0) for m in recent)
                    avg_k = round(tot_k / rec_total, 1)
                    avg_d = round(tot_d / rec_total, 1)
                    avg_a = round(tot_a / rec_total, 1)
                    summary["recent_form"] = {
                        "matches_analyzed": rec_total,
                        "winrate": f"{round((rec_wins / rec_total) * 100, 1)}%",
                        "is_active_hero": hero_id in recent_hero_ids,
                        "recent_kda": f"{avg_k}/{avg_d}/{avg_a}"
                    }
            except Exception as e:
                summary["api_note"] = f"Could not enrich stats: {str(e)}"

        return summary

    def build_match_dossier(self, match_data: Dict[str, Any]) -> str:
        """Собирает структурированное досье в формате Markdown для LLM параллельно."""
        match_id = match_data.get("id") or match_data.get("match_id", "Unknown")
        radiant_team = match_data.get("radiantTeam") or {}
        dire_team = match_data.get("direTeam") or {}

        rad_name = radiant_team.get("name") or match_data.get("radiant_name") or "Radiant"
        dire_name = dire_team.get("name") or match_data.get("dire_name") or "Dire"

        players = match_data.get("players", [])
        radiant_players_raw = [p for p in players if p.get("isRadiant", True)]
        dire_players_raw = [p for p in players if not p.get("isRadiant", True)]

        if not dire_players_raw and len(players) == 10:
            radiant_players_raw = players[:5]
            dire_players_raw = players[5:]

        # Параллельный сбор статистики по всем игрокам через ThreadPoolExecutor
        all_players_raw = radiant_players_raw + dire_players_raw
        with ThreadPoolExecutor(max_workers=6) as executor:
            enriched_players = list(executor.map(self.build_player_summary, all_players_raw))

        radiant_summaries = enriched_players[:len(radiant_players_raw)]
        dire_summaries = enriched_players[len(radiant_players_raw):]

        dossier = []
        dossier.append(f"# СКАУТИНГ-ДОСЬЕ МАТЧА DOTA 2 (ID: {match_id})")
        dossier.append(f"**Противостояние:** {rad_name} (Radiant) vs {dire_name} (Dire)\n")

        # Radiant
        dossier.append(f"## Команда Radiant: {rad_name}")
        for idx, s in enumerate(radiant_summaries, 1):
            dossier.append(f"### Игрок {idx}: {s['player_name']} (ID: {s['steam_id']})")
            dossier.append(f"- **Выбранный герой:** {s['hero_name']} (Атрибут: {s['primary_attr']}, Роли: {', '.join(s['hero_roles'])})")
            if s.get("role"):
                dossier.append(f"- **Позиция/Линия:** Роль {s['role']}, Линия {s['lane']}")
            dossier.append(f"- **Опыт на герое (Career Mastery):** {s['hero_mastery']['match_count']} матчей, винрейт {s['hero_mastery']['winrate']}, средний KDA {s['hero_mastery']['avg_kda']}, IMP {s['hero_mastery']['avg_imp']}")
            dossier.append(f"- **Текущая форма игрока (Last 15):** винрейт {s['recent_form']['winrate']}, средний KDA {s['recent_form']['recent_kda']}. Играл ли на герое недавно: {'Да' if s['recent_form']['is_active_hero'] else 'Нет'}")
            if s.get("kda"):
                dossier.append(f"- **KDA в игре:** {s['kda']}")
            dossier.append("")

        # Dire
        dossier.append(f"## Команда Dire: {dire_name}")
        for idx, s in enumerate(dire_summaries, 1):
            dossier.append(f"### Игрок {idx}: {s['player_name']} (ID: {s['steam_id']})")
            dossier.append(f"- **Выбранный герой:** {s['hero_name']} (Атрибут: {s['primary_attr']}, Роли: {', '.join(s['hero_roles'])})")
            if s.get("role"):
                dossier.append(f"- **Позиция/Линия:** Роль {s['role']}, Линия {s['lane']}")
            dossier.append(f"- **Опыт на герое (Career Mastery):** {s['hero_mastery']['match_count']} матчей, винрейт {s['hero_mastery']['winrate']}, средний KDA {s['hero_mastery']['avg_kda']}, IMP {s['hero_mastery']['avg_imp']}")
            dossier.append(f"- **Текущая форма игрока (Last 15):** винрейт {s['recent_form']['winrate']}, средний KDA {s['recent_form']['recent_kda']}. Играл ли на герое недавно: {'Да' if s['recent_form']['is_active_hero'] else 'Нет'}")
            if s.get("kda"):
                dossier.append(f"- **KDA в игре:** {s['kda']}")
            dossier.append("")

        return "\n".join(dossier)
