import time
import datetime
import requests
from lxml import html as lxml_html
from typing import List, Dict, Any

class LiquipediaScheduleFetcher:
    URL = "https://liquipedia.net/dota2/api.php?action=parse&page=Liquipedia:Matches&format=json"
    HEADERS = {
        "User-Agent": "DotaPicksBot/1.0 (contact: info@dotapicks.internal)",
        "Accept-Encoding": "gzip"
    }

    @classmethod
    def get_upcoming_matches(cls, limit: int = 20) -> List[Dict[str, Any]]:
        """Парсит официальное расписание предстоящих матчей из Liquipedia."""
        try:
            resp = requests.get(cls.URL, headers=cls.HEADERS, timeout=12)
            if resp.status_code != 200:
                return []

            data = resp.json()
            raw_html = data.get("parse", {}).get("text", {}).get("*", "")
            if not raw_html:
                return []

            tree = lxml_html.fromstring(raw_html)
            match_divs = tree.xpath('//div[contains(@class, "match-info")]')

            now_ts = int(time.time())
            upcoming = []

            for m in match_divs:
                # Временная метка
                timer_elem = m.xpath('.//*[@data-timestamp]')
                if not timer_elem:
                    continue

                ts_str = timer_elem[0].get("data-timestamp")
                if not ts_str or not ts_str.isdigit():
                    continue

                timestamp = int(ts_str)

                # Команды
                left_team = m.xpath('.//div[contains(@class, "match-info-header-opponent-left")]//text()')
                right_team = m.xpath('.//div[contains(@class, "match-info-header-opponent") and not(contains(@class, "opponent-left"))]//text()')

                # Турнир
                tour_elem = m.xpath('.//div[contains(@class, "match-info-tournament")]//text()')

                t1 = " ".join("".join(left_team).split()).strip() or "TBD"
                t2 = " ".join("".join(right_team).split()).strip() or "TBD"
                tournament = " ".join("".join(tour_elem).split()).strip() or "Tier Tournament"

                dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
                diff_seconds = timestamp - now_ts

                # Только предстоящие матчи (или те, что начались не более 15 минут назад)
                if diff_seconds > -900:
                    upcoming.append({
                        "team1": t1,
                        "team2": t2,
                        "tournament": tournament,
                        "timestamp": timestamp,
                        "datetime_utc": dt.strftime('%Y-%m-%d %H:%M UTC'),
                        "starts_in_seconds": diff_seconds,
                        "starts_in_minutes": round(diff_seconds / 60, 1)
                    })

            # Сортируем по времени начала
            upcoming.sort(key=lambda x: x["timestamp"])
            return upcoming[:limit]

        except Exception as e:
            print(f"Ошибка получения расписания с Liquipedia: {e}")
            return []

if __name__ == "__main__":
    matches = LiquipediaScheduleFetcher.get_upcoming_matches(limit=10)
    print(f"Предстоящих матчей найдено: {len(matches)}")
    for m in matches:
        print(f"• [{m['datetime_utc']}] {m['team1']} vs {m['team2']} ({m['tournament']}) -> через {m['starts_in_minutes']} мин")
