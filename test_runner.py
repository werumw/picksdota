import json
from config import STRATZ_API_KEY, GEMINI_API_KEY
from hero_helper import get_hero_name
from dossier_builder import MatchDossierBuilder
from ai_analyzer import DotaAIAnalyzer, SYSTEM_PROMPT

# Реалистичный тестовый кейс матча уровня The International / Tier-1:
# Team Spirit (Radiant) vs Team Liquid (Dire)
SAMPLE_PRO_MATCH = {
    "id": 7945001122,
    "radiantTeam": {"name": "Team Spirit", "tag": "Spirit"},
    "direTeam": {"name": "Team Liquid", "tag": "Liquid"},
    "players": [
        # Radiant (Team Spirit)
        {
            "steamAccountId": 321580797,
            "isRadiant": True,
            "role": "Carry (Pos 1)",
            "lane": "Safe Lane",
            "heroId": 10, # Morphling
            "name": "Yatoro",
            "steamAccount": {"proSteamAccount": {"name": "Yatoro", "realName": "Illya Mulyarchuk"}}
        },
        {
            "steamAccountId": 242305095,
            "isRadiant": True,
            "role": "Mid (Pos 2)",
            "lane": "Mid Lane",
            "heroId": 13, # Puck
            "name": "Larl",
            "steamAccount": {"proSteamAccount": {"name": "Larl", "realName": "Denis Sigitov"}}
        },
        {
            "steamAccountId": 256155154,
            "isRadiant": True,
            "role": "Offlane (Pos 3)",
            "lane": "Offlane",
            "heroId": 98, # Timbersaw
            "name": "Collapse",
            "steamAccount": {"proSteamAccount": {"name": "Collapse", "realName": "Magomed Khalilov"}}
        },
        {
            "steamAccountId": 177419702,
            "isRadiant": True,
            "role": "Soft Support (Pos 4)",
            "lane": "Offlane",
            "heroId": 86, # Rubick
            "name": "Mira",
            "steamAccount": {"proSteamAccount": {"name": "Mira", "realName": "Myroslav Kolpakov"}}
        },
        {
            "steamAccountId": 91730177,
            "isRadiant": True,
            "role": "Hard Support (Pos 5)",
            "lane": "Safe Lane",
            "heroId": 111, # Oracle
            "name": "Miposhka",
            "steamAccount": {"proSteamAccount": {"name": "Miposhka", "realName": "Yaroslav Naidenov"}}
        },
        # Dire (Team Liquid)
        {
            "steamAccountId": 152962063,
            "isRadiant": False,
            "role": "Carry (Pos 1)",
            "lane": "Safe Lane",
            "heroId": 48, # Luna
            "name": "miCKe",
            "steamAccount": {"proSteamAccount": {"name": "miCKe", "realName": "Michael Vu"}}
        },
        {
            "steamAccountId": 101695162,
            "isRadiant": False,
            "role": "Mid (Pos 2)",
            "lane": "Mid Lane",
            "heroId": 17, # Storm Spirit
            "name": "Nisha",
            "steamAccount": {"proSteamAccount": {"name": "Nisha", "realName": "Michał Jankowski"}}
        },
        {
            "steamAccountId": 86799324,
            "isRadiant": False,
            "role": "Offlane (Pos 3)",
            "lane": "Offlane",
            "heroId": 7, # Earthshaker
            "name": "33",
            "steamAccount": {"proSteamAccount": {"name": "33", "realName": "Neta Shapira"}}
        },
        {
            "steamAccountId": 94054712,
            "isRadiant": False,
            "role": "Soft Support (Pos 4)",
            "lane": "Offlane",
            "heroId": 102, # Abaddon
            "name": "Boxi",
            "steamAccount": {"proSteamAccount": {"name": "Boxi", "realName": "Samuel Svahn"}}
        },
        {
            "steamAccountId": 103735789,
            "isRadiant": False,
            "role": "Hard Support (Pos 5)",
            "lane": "Safe Lane",
            "heroId": 83, # Treant Protector
            "name": "Insania",
            "steamAccount": {"proSteamAccount": {"name": "Insania", "realName": "Aydin Sarkohi"}}
        }
    ]
}

def run_test():
    print("=" * 60)
    print(" ТЕСТИРОВАНИЕ СИСТЕМЫ АНАЛИЗА МАТЧЕЙ DOTA 2 ")
    print("=" * 60)

    # 1. Проверка API ключей
    print("\n1. Проверка окружения:")
    has_stratz = bool(STRATZ_API_KEY)
    has_gemini = bool(GEMINI_API_KEY)

    print(f"   - STRATZ_API_KEY: {'[+] Найдено' if has_stratz else '[-] Не задан (нужен для автосбора пабликов)'}")
    print(f"   - GEMINI_API_KEY: {'[+] Найдено' if has_gemini else '[-] Не задан (нужен для генерации прогноза AI)'}")

    # 2. Инициализация клиента STRATZ (если есть)
    stratz_client = None
    if has_stratz:
        from stratz_client import StratzClient
        stratz_client = StratzClient()
        print("\n2. Тестирование связи со STRATZ GraphQL...")
        try:
            live = stratz_client.get_live_matches()
            print(f"   [OK] Связь успешна! Доступно live матчей: {len(live)}")
        except Exception as e:
            print(f"   [!] Ошибка запроса STRATZ: {e}")

    # 3. Построение досье
    print("\n3. Генерация глубокого скаутинг-досье матча...")
    builder = MatchDossierBuilder(stratz_client=stratz_client)
    dossier = builder.build_match_dossier(SAMPLE_PRO_MATCH)
    print("   [OK] Досье успешно сгенерировано! Фрагмент досье:")
    print("-" * 50)
    lines = dossier.split("\n")
    print("\n".join(lines[:25]))
    print("   ... (всего строк досье: " + str(len(lines)) + ")")
    print("-" * 50)

    # 4. Анализ нейросетью
    if has_gemini:
        print("\n4. Отправка досье в нейросеть Gemini...")
        analyzer = DotaAIAnalyzer()
        try:
            result = analyzer.analyze_dossier(dossier)
            print("\n" + "=" * 60)
            print(f"ИТОГОВЫЙ ПРОГНОЗ НЕЙРОСЕТИ: ПОБЕДИТЕЛЬ {result.get('predicted_team_name')} ({result.get('predicted_winner')})")
            print(f"Вероятность победы: {result.get('win_probability_percent')}% (Уверенность: {result.get('confidence_level')})")
            print("=" * 60)
            print("\nРазбор линий:")
            for k, v in result.get("lanes_breakdown", {}).items():
                print(f"  * {k}: {v}")
            print("\nКлючевые факторы игроков:")
            for f in result.get("key_player_factors", []):
                print(f"  * {f}")
            print("\nУсловия победы победителя:")
            conds = result.get("radiant_win_conditions", []) if result.get("predicted_winner") == "Radiant" else result.get("dire_win_conditions", [])
            for c in conds:
                print(f"  * {c}")
            print(f"\nТактический вердикт:\n{result.get('tactical_summary')}")
        except Exception as e:
            print(f"   [!] Ошибка при вызове AI: {e}")
    else:
        print("\n[!] Для запуска шага 4 (AI-прогнозирование) вставьте ваш GEMINI_API_KEY в файл .env")

if __name__ == "__main__":
    run_test()
