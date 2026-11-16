import json
import logging
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional
from hero_helper import get_hero_name

logger = logging.getLogger(__name__)

ACTIVE_MATCHES_FILE = Path(__file__).resolve().parent / "active_matches.json"

class PostMatchTracker:
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_file = storage_path or ACTIVE_MATCHES_FILE

    def _load_active(self) -> Dict[str, Any]:
        if not self.storage_file.exists():
            return {}
        try:
            with open(self.storage_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_active(self, data: Dict[str, Any]):
        try:
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save active matches: {e}")

    def track_match(self, match_id: int, radiant_name: str, dire_name: str, predicted_winner: str, predicted_side: str, prob: int, chat_ids: List[int]):
        """Регистрирует матч для последующего отслеживания результата."""
        active = self._load_active()
        active[str(match_id)] = {
            "match_id": match_id,
            "radiant_name": radiant_name,
            "dire_name": dire_name,
            "predicted_winner": predicted_winner,
            "predicted_side": predicted_side,
            "probability": prob,
            "chat_ids": list(set(chat_ids)),
            "status": "in_progress"
        }
        self._save_active(active)
        logger.info(f"Матч {match_id} ({radiant_name} vs {dire_name}) поставлен на трекинг результата.")

    def check_finished_matches(self, stratz_client, ai_analyzer) -> List[Dict[str, Any]]:
        """Проверяет все активные матчи. Если матч завершен — генерирует отчет об исходе."""
        active = self._load_active()
        if not active:
            return []

        finished_reports = []
        remaining = {}

        for match_id_str, meta in active.items():
            match_id = int(match_id_str)
            try:
                duration = 0
                did_rad_win = None
                rad_kills = 0
                dire_kills = 0
                top_name = "MVP Игрок"
                top_hero = "Герой"
                top_kda = "10/2/15"
                top_imp = 0

                # 1. Проверяем через STRATZ
                try:
                    m = stratz_client.get_match(match_id)
                    duration = m.get("durationSeconds", 0) or 0
                    did_rad_win = m.get("didRadiantWin")
                    rad_kills = m.get("radiantKills", 0) or 0
                    dire_kills = m.get("direKills", 0) or 0

                    players = m.get("players", [])
                    winner_players = [p for p in players if p.get("isRadiant") == did_rad_win]
                    winner_players.sort(key=lambda p: (p.get("imp", 0) or 0, p.get("kills", 0) or 0), reverse=True)
                    if winner_players:
                        tp = winner_players[0]
                        top_name = (tp.get("steamAccount", {}).get("proSteamAccount", {}).get("name") or 
                                    tp.get("steamAccount", {}).get("name") or "Player")
                        top_hero = get_hero_name(tp.get("heroId", 0))
                        top_kda = f"{tp.get('kills', 0)}/{tp.get('deaths', 0)}/{tp.get('assists', 0)}"
                        top_imp = tp.get("imp", 0) or 0
                except Exception as stratz_err:
                    logger.debug(f"STRATZ get_match({match_id}) exception: {stratz_err}")

                # 2. Если STRATZ еще не обновил матч, проверяем OpenDota
                if not duration or did_rad_win is None:
                    try:
                        r = requests.get(f"https://api.opendota.com/api/matches/{match_id}", timeout=6)
                        if r.status_code == 200:
                            od = r.json()
                            duration = od.get("duration", 0) or 0
                            did_rad_win = od.get("radiant_win")
                            rad_kills = od.get("radiant_score", 0) or 0
                            dire_kills = od.get("dire_score", 0) or 0
                            od_players = od.get("players", [])
                            w_players = [p for p in od_players if p.get("isRadiant") == did_rad_win]
                            w_players.sort(key=lambda p: (p.get("kills", 0) or 0), reverse=True)
                            if w_players:
                                tp = w_players[0]
                                top_name = tp.get("personaname") or tp.get("name") or "MVP"
                                top_hero = get_hero_name(tp.get("hero_id", 0))
                                top_kda = f"{tp.get('kills', 0)}/{tp.get('deaths', 0)}/{tp.get('assists', 0)}"
                    except Exception:
                        pass

                # Матч завершен, если известна длительность > 600 сек (10 мин) и определен победитель
                if duration and duration > 600 and did_rad_win is not None:
                    rad_name = meta["radiant_name"]
                    dire_name = meta["dire_name"]
                    actual_winner_side = "Radiant" if did_rad_win else "Dire"
                    actual_winner_name = rad_name if did_rad_win else dire_name

                    predicted_side = meta["predicted_side"]
                    is_correct = (predicted_side.lower() == actual_winner_side.lower())

                    mins = duration // 60
                    secs = duration % 60
                    time_str = f"{mins}:{secs:02d}"

                    # Тактическое объяснение исхода
                    if is_correct:
                        why_text = (
                            f"Команда <b>{actual_winner_name}</b> уверенно реализовала преимущество драфта и тайминги силы. "
                            f"Ключевой вклад внес <b>{top_name}</b> на <b>{top_hero}</b> (KDA: {top_kda}, рейтинг IMP: +{top_imp}), "
                            f"захватив карту и выиграв ключевые командные сражения."
                        )
                    else:
                        why_text = (
                            f"Сенсационный исход: <b>{actual_winner_name}</b> смогли сломать прогноз фаворита. "
                            f"За счет агрессивных действий <b>{top_name}</b> на <b>{top_hero}</b> (KDA: {top_kda}) "
                            f"они перехватили инициативу в мид-гейме и закрыли карту за {time_str}."
                        )

                    report_card = self._format_result_card(
                        match_id=match_id,
                        rad_name=rad_name,
                        dire_name=dire_name,
                        actual_winner=actual_winner_name,
                        predicted_winner=meta["predicted_winner"],
                        is_correct=is_correct,
                        time_str=time_str,
                        score_str=f"{rad_kills} - {dire_kills}",
                        why_text=why_text
                    )

                    finished_reports.append({
                        "match_id": match_id,
                        "chat_ids": meta.get("chat_ids", []),
                        "message_text": report_card
                    })
                else:
                    # Матч еще идет
                    remaining[match_id_str] = meta

            except Exception as e:
                logger.error(f"Ошибка проверки завершения матча {match_id}: {e}")
                remaining[match_id_str] = meta

        self._save_active(remaining)
        return finished_reports

    def _format_result_card(self, match_id: int, rad_name: str, dire_name: str, actual_winner: str, predicted_winner: str, is_correct: bool, time_str: str, score_str: str, why_text: str) -> str:
        status_badge = "✅ <b>ПРОГНОЗ ЗАШЕЛ! (ПОБЕДА)</b>" if is_correct else "❌ <b>ПРОГНОЗ НЕ ЗАШЕЛ (ПОРАЖЕНИЕ)</b>"

        card = f"""🏁 <b>МАТЧ ЗАВЕРШЕН: РЕЗУЛЬТАТ</b>
🆔 <b>Match ID:</b> <code>{match_id}</code>

⚔️ <b>{rad_name}</b> vs <b>{dire_name}</b>
⏱ <b>Длительность:</b> {time_str} | <b>Итоговый счет:</b> {score_str}

🎯 <b>Наш прогноз был:</b> {predicted_winner}
🏆 <b>Победитель матча:</b> <b>{actual_winner}</b>
📊 <b>Итог:</b> {status_badge}

🔍 <b>Почему так произошло (Post-Match разбор):</b>
{why_text}
"""
        return card
