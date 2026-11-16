import os
import requests
import json
from typing import Dict, Any, Optional, List
from config import STRATZ_API_KEY

STRATZ_GRAPHQL_URL = "https://api.stratz.com/graphql"

class StratzClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or STRATZ_API_KEY
        self.headers = {
            "User-Agent": "STRATZ_API",
            "Content-Type": "application/json"
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    def set_token(self, token: str):
        self.token = token
        self.headers["Authorization"] = f"Bearer {self.token}"

    def query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.token:
            raise ValueError(
                "STRATZ_API_KEY отсутствует! Укажите токен в файле .env или передайте в конструктор.\n"
                "Получить бесплатный токен можно на https://stratz.com/api -> Create Token."
            )

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        response = requests.post(
            STRATZ_GRAPHQL_URL,
            headers=self.headers,
            json=payload,
            timeout=20
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Ошибка запроса STRATZ API ({response.status_code}): {response.text}"
            )

        res_json = response.json()
        if "errors" in res_json:
            raise RuntimeError(f"GraphQL ошибки: {res_json['errors']}")

        return res_json.get("data", {})

    def get_match(self, match_id: int) -> Dict[str, Any]:
        """Получает полные данные по сыгранному или текущему матчу."""
        gql = """
        query GetMatch($id: Long!) {
          match(id: $id) {
            id
            didRadiantWin
            durationSeconds
            startDateTime
            radiantKills
            direKills
            radiantTeam {
              id
              name
              tag
            }
            direTeam {
              id
              name
              tag
            }
            players {
              steamAccountId
              heroId
              isRadiant
              kills
              deaths
              assists
              goldPerMinute
              experiencePerMinute
              networth
              heroDamage
              towerDamage
              imp
              lane
              role
              award
              steamAccount {
                name
                proSteamAccount {
                  name
                  realName
                }
              }
            }
          }
        }
        """
        data = self.query(gql, {"id": match_id})
        return data.get("match", {})

    def get_player_profile(self, steam_account_id: int) -> Dict[str, Any]:
        """Получает профиль игрока и его общую статистику."""
        gql = """
        query GetPlayer($id: Long!) {
          player(steamAccountId: $id) {
            steamAccount {
              id
              name
              proSteamAccount {
                name
                realName
                team {
                  name
                  tag
                }
              }
            }
            matchCount
            winCount
            imp
          }
        }
        """
        data = self.query(gql, {"id": steam_account_id})
        return data.get("player", {})

    def get_player_hero_performance(self, steam_account_id: int, hero_id: int) -> Dict[str, Any]:
        """Получает статистику игрока на конкретном герое (винрейт, матчи, KDA, IMP)."""
        gql = """
        query GetPlayerHero($id: Long!, $heroIds: [Short]) {
          player(steamAccountId: $id) {
            heroesPerformance(request: { heroIds: $heroIds }, take: 1) {
              heroId
              matchCount
              winCount
              kDA
              avgKills
              avgDeaths
              avgAssists
              imp
            }
          }
        }
        """
        data = self.query(gql, {"id": steam_account_id, "heroIds": [hero_id]})
        player = data.get("player") or {}
        perfs = player.get("heroesPerformance") or []
        return perfs[0] if perfs else {}

    def get_player_recent_matches(self, steam_account_id: int, take: int = 15) -> List[Dict[str, Any]]:
        """Получает последние N матчей игрока (включая паблики)."""
        gql = """
        query GetRecentMatches($id: Long!, $take: Int!) {
          player(steamAccountId: $id) {
            matches(request: { take: $take, skip: 0 }) {
              id
              didRadiantWin
              players {
                steamAccountId
                heroId
                isRadiant
                kills
                deaths
                assists
                imp
              }
            }
          }
        }
        """
        data = self.query(gql, {"id": steam_account_id, "take": take})
        player = data.get("player") or {}
        raw_matches = player.get("matches") or []

        results = []
        for m in raw_matches:
            p = next((x for x in m.get("players", []) if x.get("steamAccountId") == steam_account_id), None)
            if p:
                results.append({
                    "match_id": m.get("id"),
                    "hero_id": p.get("heroId"),
                    "is_victory": (m.get("didRadiantWin") == p.get("isRadiant")),
                    "kills": p.get("kills", 0),
                    "deaths": p.get("deaths", 0),
                    "assists": p.get("assists", 0),
                    "imp": p.get("imp", 0)
                })
        return results

    def get_live_matches(self, take: int = 50) -> List[Dict[str, Any]]:
        """Получает расширенный список текущих live матчей (до 50 матчей)."""
        gql = """
        query GetLiveMatches($take: Int!) {
          live {
            matches(request: { take: $take }) {
              matchId
              gameState
              radiantTeam {
                name
                tag
              }
              direTeam {
                name
                tag
              }
              gameTime
              players {
                steamAccountId
                heroId
                isRadiant
                networth
              }
            }
          }
        }
        """
        try:
            data = self.query(gql, {"take": take})
            live = data.get("live") or {}
            return live.get("matches") or []
        except Exception:
            # Fallback к базовому запросу, если аргумент take не поддерживается
            gql_base = """
            query GetLiveMatches {
              live {
                matches {
                  matchId
                  gameState
                  radiantTeam { name tag }
                  direTeam { name tag }
                  gameTime
                  players { steamAccountId heroId isRadiant networth }
                }
              }
            }
            """
            try:
                data = self.query(gql_base)
                live = data.get("live") or {}
                return live.get("matches") or []
            except Exception:
                return []
