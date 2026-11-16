from typing import Dict, Any

class OddsCalculator:
    """
    Калькулятор букмекерских коэффициентов и математического ожидания (+EV)
    на основе вероятностей победы, рассчитанных нейросетью.
    """

    @staticmethod
    def calculate_odds(prob_team1: float, prob_team2: float, margin_percent: float = 5.0) -> Dict[str, Any]:
        """
        prob_team1, prob_team2 в процентах (например, 58.0 и 42.0).
        margin_percent - стандартная маржа букмекера (обычно 5-6%).
        """
        # Защита от деления на 0
        p1 = max(min(prob_team1, 99.0), 1.0)
        p2 = max(min(prob_team2, 99.0), 1.0)

        # Справедливый чистый коэффициент (Fair Odds без маржи)
        fair_odd1 = round(100.0 / p1, 2)
        fair_odd2 = round(100.0 / p2, 2)

        # Ориентировочный коэффициент в линии БК (с учетом маржи)
        margin_mult = 1.0 - (margin_percent / 100.0)
        bk_odd1 = round(fair_odd1 * margin_mult, 2)
        bk_odd2 = round(fair_odd2 * margin_mult, 2)

        return {
            "fair_odds": {
                "team1": fair_odd1,
                "team2": fair_odd2
            },
            "estimated_bookmaker_odds": {
                "team1": bk_odd1,
                "team2": bk_odd2
            },
            "value_bet_guidance": {
                "team1_rule": f"Коэффициент в БК выше {fair_odd1} имеет положительное мат. ожидание (+EV)",
                "team2_rule": f"Коэффициент в БК выше {fair_odd2} имеет положительное мат. ожидание (+EV)"
            }
        }
