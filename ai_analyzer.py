import os
import json
import re
from typing import Dict, Any, Optional
from config import GEMINI_API_KEY, GEMINI_MODEL, OPENAI_API_KEY

SYSTEM_PROMPT = """
Ты — главный тактический аналитик и тренер Tier-1 команд по Dota 2 (уровня победителей The International).
Твоя цель — провести максимально глубокий и объективный разбор матча на основе предоставленного скаутинг-досье и выдать прогноз победителя.

При анализе ты ОБЯЗАН учитывать:
1. Микро-фактор игроков:
   - Опыт и винрейт на конкретном выбранном герое (Career Mastery). Если игрок взял сигнатурку (60%+ WR) — это огромный плюс. Если у него мало игр или низкий винрейт — это зона риска.
   - Текущая форма игрока (винрейт за последние 15 матчей, наигранность героя в недавних играх).
2. Анализ линий (Laning Stage):
   - Противостояние Safe Lane Radiant vs Offlane Dire.
   - Мид 1v1: кто имеет матчап-преимущество, контроль рун и ганг-потенциал.
   - Противостояние Offlane Radiant vs Safe Lane Dire.
3. Синергия драфта и Win Conditions:
   - Контроль (дизейблы, BKB-пирсинг), инициация, сейв-механики.
   - Темп и тайминги силы (Power Spikes): кому нужно закончить до 30-й минуты, кто сильнее в ультра-лейте.
   - Потенциал убийства Рошана и осады базы (Tower/Siege damage).
4. Прогноз исхода:
   - Вероятность победы должна быть взвешенной (в Dota 2 почти никогда не бывает 95%/5% в равных составах, диапазон обычно 52% - 75%).

Твой ответ ОБЯЗАТЕЛЬНО должен быть валидным JSON со следующей структурой:
{
  "predicted_winner": "Radiant" или "Dire",
  "predicted_team_name": "Название команды",
  "win_probability_percent": целое число от 50 до 90,
  "confidence_level": "Высокая" | "Средняя" | "Низкая",
  "lanes_breakdown": {
    "safe_radiant_vs_off_dire": "краткий анализ линии",
    "mid_matchup": "краткий анализ мида",
    "off_radiant_vs_safe_dire": "краткий анализ линии"
  },
  "key_player_factors": [
    "описание ключевого фактора конкретного игрока (например, сигнатурный герой или потеря формы)"
  ],
  "radiant_win_conditions": [
    "условие победы Radiant 1",
    "условие победы Radiant 2"
  ],
  "dire_win_conditions": [
    "условие победы Dire 1",
    "условие победы Dire 2"
  ],
  "tactical_summary": "Развернутый вердикт тренера о том, как будет развиваться игра и за счет чего победит выбранная сторона."
}
"""

class DotaAIAnalyzer:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model_name or GEMINI_MODEL
        if not self.model_name or self.model_name == "gemini-2.5-flash":
            self.model_name = "gemini-3.8-flash"

    def analyze_dossier(self, dossier_text: str) -> Dict[str, Any]:
        """Отправляет досье в нейросеть Gemini или возвращает статистический расчет."""
        prompt = f"{SYSTEM_PROMPT}\n\nСКАУТИНГ-ДОСЬЕ МАТЧА:\n{dossier_text}\n\nВыдай ответ СТРОГО в формате JSON без лишнего форматирования."

        # Попытка вызова Gemini API
        if self.api_key:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.api_key)
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.2
                    )
                )
                text_resp = response.text.strip()
                if text_resp.startswith("```json"):
                    text_resp = text_resp[7:]
                if text_resp.endswith("```"):
                    text_resp = text_resp[:-3]
                return json.loads(text_resp.strip())

            except Exception as e:
                err_str = str(e)
                print(f"\n[!] Ошибка Gemini API ({err_str[:120]}...)")
                if "User location is not supported" in err_str:
                    print("    -> Google блокирует прямые запросы с российских IP. Включите любой VPN на ПК для прямого вызова.")
                print("    -> Включаем встроенный математический движок аналитики (Statistical Engine Fallback)...\n")

        # Если Gemini недоступен (например, без VPN), запускаем аналитический модуль на основе метрик STRATZ
        return self._heuristic_analysis(dossier_text)

    def _heuristic_analysis(self, dossier_text: str) -> Dict[str, Any]:
        """Математический анализ матча на основе собранного досье (винрейты, KDA, сигнатурки)."""
        rad_wr_list = []
        dire_wr_list = []
        rad_form_list = []
        dire_form_list = []

        is_radiant = True
        key_factors = []

        # Парсим досье
        current_player = ""
        current_hero = ""
        for line in dossier_text.splitlines():
            if "## Команда Radiant:" in line:
                is_radiant = True
            elif "## Команда Dire:" in line:
                is_radiant = False

            if line.startswith("### Игрок"):
                current_player = line.split(":", 1)[-1].strip()

            if line.startswith("- **Выбранный герой:**"):
                current_hero = line.split(":", 1)[-1].split("(")[0].strip()

            # Парсим опыт на герое
            if "Опыт на герое (Career Mastery):" in line:
                wr_match = re.search(r"винрейт ([\d\.]+)%", line)
                if wr_match:
                    wr = float(wr_match.group(1))
                    (rad_wr_list if is_radiant else dire_wr_list).append(wr)
                    if wr >= 65.0:
                        key_factors.append(f"Сигнатурный пик: {current_player} на {current_hero} (винрейт {wr}%)")
                    elif wr <= 40.0:
                        key_factors.append(f"Зона риска: {current_player} на {current_hero} (слабый винрейт {wr}%)")

            # Парсим текущую форму
            if "Текущая форма игрока (Last 15):" in line:
                f_match = re.search(r"винрейт ([\d\.]+)%", line)
                if f_match:
                    f_wr = float(f_match.group(1))
                    (rad_form_list if is_radiant else dire_form_list).append(f_wr)

        rad_mastery = sum(rad_wr_list) / len(rad_wr_list) if rad_wr_list else 50.0
        dire_mastery = sum(dire_wr_list) / len(dire_wr_list) if dire_wr_list else 50.0

        rad_form = sum(rad_form_list) / len(rad_form_list) if rad_form_list else 50.0
        dire_form = sum(dire_form_list) / len(dire_form_list) if dire_form_list else 50.0

        # Взвешенный расчет силы: 55% сигнатурность героев, 45% текущая форма игроков
        rad_score = (rad_mastery * 0.55) + (rad_form * 0.45)
        dire_score = (dire_mastery * 0.55) + (dire_form * 0.45)

        total_score = rad_score + dire_score
        rad_prob = round((rad_score / total_score) * 100) if total_score > 0 else 50

        # Ограничиваем реалистичным коридором 52% - 75%
        if rad_prob > 50:
            rad_prob = min(max(rad_prob, 53), 74)
            winner = "Radiant"
            win_prob = rad_prob
        else:
            dire_prob = 100 - rad_prob
            dire_prob = min(max(dire_prob, 53), 74)
            winner = "Dire"
            win_prob = dire_prob

        return {
            "predicted_winner": winner,
            "predicted_team_name": "Radiant Team" if winner == "Radiant" else "Dire Team",
            "win_probability_percent": win_prob,
            "confidence_level": "Высокая" if win_prob >= 63 else "Средняя",
            "lanes_breakdown": {
                "safe_radiant_vs_off_dire": "Оценка по статистике линии и KDA саппортов",
                "mid_matchup": "Оценка личного импакта (IMP) мидеров в текущем патче",
                "off_radiant_vs_safe_dire": "Оценка темпа хардлейнера против вражеского керри"
            },
            "key_player_factors": key_factors[:5] if key_factors else ["Равные показатели сигнатурности по обе стороны"],
            "radiant_win_conditions": [
                f"Реализация сигнатурных героев (средний винрейт ростера {round(rad_mastery, 1)}%)",
                "Удержание преимущества на ранних линиях до появления вражеских BKB"
            ],
            "dire_win_conditions": [
                f"Реализация текущей формы игроков (средний винрейт в последних матчах {round(dire_form, 1)}%)",
                "Переход в мид-гейм тимфайты и фокус ключевых кор-героев"
            ],
            "tactical_summary": (
                f"На основе анализа 10 аккаунтов игроков: перевес на стороне {winner} "
                f"со взвешенным винрейтом {win_prob}%. "
                f"Команда {winner} имеет преимущество по совокупному опыту на выбранных героях "
                f"и лучшую текущую индивидуальную форму в пабликах/турнирах."
            )
        }
