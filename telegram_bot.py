import os
import asyncio
import logging
import time
from typing import Dict, Any, List
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.client.session.aiohttp import AiohttpSession

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PROXY, STRATZ_API_KEY
from stratz_client import StratzClient
from dossier_builder import MatchDossierBuilder
from ai_analyzer import DotaAIAnalyzer
from test_runner import SAMPLE_PRO_MATCH
from subscriber_manager import get_subscribers, add_subscriber, remove_subscriber, is_subscribed
from schedule_fetcher import LiquipediaScheduleFetcher
from odds_calculator import OddsCalculator
from post_match_tracker import PostMatchTracker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

post_tracker = PostMatchTracker()

# Веб-сервер для поддержки активности на облачных хостингах
async def health_check_handler(request):
    return web.Response(text="🟢 Dota 2 AI Bot with Live Odds & Post-Match Tracker is running 24/7!", content_type="text/plain")

async def start_health_server():
    port = int(os.getenv("PORT", 7860))
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Вспомогательный веб-сервер запущен на порту {port}")

def get_main_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    auto_active = is_subscribed(chat_id)
    btn_auto_text = "🟢 Авто-уведомления: ВКЛ" if auto_active else "⚪ Авто-уведомления: ВЫКЛ"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎮 Тестовый анализ (Spirit vs Liquid)", callback_data="btn_test"),
            InlineKeyboardButton(text="📅 Расписание турниров", callback_data="btn_schedule")
        ],
        [
            InlineKeyboardButton(text="🔴 Проверить Live сейчас", callback_data="btn_live"),
            InlineKeyboardButton(text=btn_auto_text, callback_data="btn_toggle_auto")
        ]
    ])
    return kb

def format_analysis_card(match_id: Any, res: Dict[str, Any], is_live: bool = False, rad_name: str = "Radiant", dire_name: str = "Dire") -> str:
    winner = res.get("predicted_winner", "Unknown")
    winner_name = res.get("predicted_team_name", winner)
    prob = res.get("win_probability_percent", 50)
    conf = res.get("confidence_level", "Средняя")

    # Расчет коэффициентов букмекеров и Value Bet
    odds_data = OddsCalculator.calculate_odds(prob, 100 - prob)
    fair_w = odds_data["fair_odds"]["team1"]
    fair_l = odds_data["fair_odds"]["team2"]
    bk_w = odds_data["estimated_bookmaker_odds"]["team1"]
    bk_l = odds_data["estimated_bookmaker_odds"]["team2"]

    loser_name = dire_name if winner == "Radiant" else rad_name

    header = "🔴 <b>LIVE-ДРАФТ ЗАВЕРШЕН! АНАЛИЗ МАТЧА</b>" if is_live else "📊 <b>АНАЛИЗ МАТЧА DOTA 2</b>"

    lanes = res.get("lanes_breakdown", {})
    safe_lane = lanes.get("safe_radiant_vs_off_dire", "Равный матчап")
    mid_lane = lanes.get("mid_matchup", "Равный матчап")
    off_lane = lanes.get("off_radiant_vs_safe_dire", "Равный матчап")

    factors = res.get("key_player_factors", [])
    factors_text = "\n".join([f"• {f}" for f in factors[:4]]) if factors else "• Без явных аномалий в ростерах"

    verdict = res.get("tactical_summary", "")

    card = f"""{header}
🆔 <b>Match ID:</b> <code>{match_id}</code>

⚔️ <b>{rad_name}</b> vs <b>{dire_name}</b>
🏆 <b>ПРОГНОЗ ПОБЕДИТЕЛЯ:</b> <b>{winner_name} ({winner})</b>
📈 <b>Вероятность победы:</b> <b>{prob}%</b> | <b>Уверенность:</b> {conf}

💰 <b>Коэффициенты и оценка линии (БК):</b>
• <b>На победу {winner_name}:</b> <code>{fair_w}</code> <i>(линия БК: ~{bk_w})</i>
• <b>На победу {loser_name}:</b> <code>{fair_l}</code> <i>(линия БК: ~{bk_l})</i>
💡 <i>Валуйная ставка (+EV): выгодно ставить на {winner_name}, если букмекер предлагает кэф выше {fair_w}!</i>

⚔️ <b>Оценка линий:</b>
• <b>Легкая Radiant vs Сложная Dire:</b> {safe_lane}
• <b>Мид 1v1:</b> {mid_lane}
• <b>Сложная Radiant vs Легкая Dire:</b> {off_lane}

🎯 <b>Ключевые факторы игроков:</b>
{factors_text}

🧠 <b>Тактический вердикт:</b>
<i>{verdict}</i>

⏱ <i>После окончания матча бот автоматически пришлет отчет с результатом (сыграл ли прогноз и почему).</i>
"""
    return card

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    add_subscriber(message.chat.id)
    text = (
        "👋 <b>Привет! Я бот глубокого анализа матчей Dota 2.</b>\n\n"
        "✅ <b>Вы успешно подписаны на уведомления!</b>\n\n"
        "<b>Что делает бот:</b>\n"
        "1. <b>До игры (в момент драфта):</b> присылает детальный скаутинг 10 игроков, вероятность победы и <b>коэффициенты букмекеров (+EV)</b>.\n"
        "2. <b>После игры:</b> автоматически присылает <b>отчет с результатом (зашел прогноз или нет, и почему)</b>.\n\n"
        "<b>Команды:</b>\n"
        "• Отправьте <b>номер любого матча</b> (например: <code>9088923051</code>) для разбора.\n"
        "• <code>/schedule</code> — ближайшие турнирные игры по расписанию.\n"
        "• <code>/test</code> — посмотреть пример отчета (Spirit vs Liquid)."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard(message.chat.id))

@dp.message(Command("test"))
@dp.callback_query(F.data == "btn_test")
async def handle_test(event: types.TelegramObject):
    msg = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer("Запускаю тестовый анализ...")

    add_subscriber(msg.chat.id)
    wait_msg = await msg.answer("⏳ Собираю скаутинг-досье Spirit vs Liquid, рассчитываю вероятность и коэффициенты...")
    try:
        builder = MatchDossierBuilder(stratz_client=StratzClient() if STRATZ_API_KEY else None)
        dossier = await asyncio.to_thread(builder.build_match_dossier, SAMPLE_PRO_MATCH)
        analyzer = DotaAIAnalyzer()
        res = await asyncio.to_thread(analyzer.analyze_dossier, dossier)
        card = format_analysis_card(
            SAMPLE_PRO_MATCH["id"], res, is_live=False,
            rad_name="Team Spirit", dire_name="Team Liquid"
        )

        # Ставим на трекинг результата
        post_tracker.track_match(
            SAMPLE_PRO_MATCH["id"], "Team Spirit", "Team Liquid",
            res.get("predicted_team_name", "Team Spirit"), res.get("predicted_winner", "Radiant"),
            res.get("win_probability_percent", 54), [msg.chat.id]
        )

        await wait_msg.edit_text(card, parse_mode="HTML", reply_markup=get_main_keyboard(msg.chat.id))
    except Exception as e:
        await wait_msg.edit_text(f"❌ Ошибка анализа: {e}")

@dp.message(Command("schedule"))
@dp.callback_query(F.data == "btn_schedule")
async def handle_schedule(event: types.TelegramObject):
    msg = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer("Загружаю расписание Liquipedia...")

    add_subscriber(msg.chat.id)
    wait_msg = await msg.answer("📅 Загружаю официальное расписание Liquipedia...")
    matches = await asyncio.to_thread(LiquipediaScheduleFetcher.get_upcoming_matches, 6)

    if not matches:
        await wait_msg.edit_text("😴 На ближайшее время матчей в расписании не найдено.", reply_markup=get_main_keyboard(msg.chat.id))
        return

    text = "📅 <b>БЛИЖАЙШИЕ МАТЧИ ПО РАСПИСАНИЮ (Liquipedia):</b>\n\n"
    for idx, m in enumerate(matches, 1):
        mins = m["starts_in_minutes"]
        time_hint = f"через {int(mins)} мин" if mins > 0 else "прямо сейчас!"
        text += (
            f"<b>{idx}. {m['team1']} vs {m['team2']}</b>\n"
            f"🏆 Турнир: <i>{m['tournament']}</i>\n"
            f"🕒 Начало: <code>{m['datetime_utc']}</code> ({time_hint})\n\n"
        )
    text += "💡 <i>Перед началом матча бот автоматически пришлет вам расклад драфта и коэффициенты, а после игры — результат!</i>"
    await wait_msg.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyboard(msg.chat.id))

@dp.message(Command("live"))
@dp.callback_query(F.data == "btn_live")
async def handle_live(event: types.TelegramObject):
    msg = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer("Проверяю live матчи...")

    add_subscriber(msg.chat.id)
    try:
        stratz = StratzClient()
        live = await asyncio.to_thread(stratz.get_live_matches, 50)
        if not live:
            await msg.answer("😴 Сейчас нет активных официальных матчей на стадии драфта.", reply_markup=get_main_keyboard(msg.chat.id))
            return

        text = f"🔴 <b>Найдено Live-матчей: {len(live)}</b>\n\n"
        buttons = []
        for m in live[:6]:
            mid = m.get("matchId")
            rad = m.get("radiantTeam", {}).get("name", "Radiant")
            dire = m.get("direTeam", {}).get("name", "Dire")
            state = m.get("gameState", "LIVE")
            text += f"• <b>{rad}</b> vs <b>{dire}</b> (ID: <code>{mid}</code>, Статус: {state})\n"
            buttons.append([InlineKeyboardButton(text=f"Анализ {rad} vs {dire}", callback_data=f"analyze_{mid}")])

        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await msg.answer(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        await msg.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data.startswith("analyze_"))
async def cb_analyze_live(query: CallbackQuery):
    match_id = int(query.data.split("_")[1])
    await query.answer("Анализирую...")
    wait_msg = await query.message.answer(f"⏳ Сбор данных для матча {match_id}...")
    try:
        stratz = StratzClient()
        match_data = await asyncio.to_thread(stratz.get_match, match_id)
        rad_name = match_data.get("radiantTeam", {}).get("name", "Radiant")
        dire_name = match_data.get("direTeam", {}).get("name", "Dire")

        builder = MatchDossierBuilder(stratz_client=stratz)
        dossier = await asyncio.to_thread(builder.build_match_dossier, match_data)
        analyzer = DotaAIAnalyzer()
        res = await asyncio.to_thread(analyzer.analyze_dossier, dossier)
        card = format_analysis_card(match_id, res, is_live=True, rad_name=rad_name, dire_name=dire_name)

        post_tracker.track_match(
            match_id, rad_name, dire_name,
            res.get("predicted_team_name", rad_name), res.get("predicted_winner", "Radiant"),
            res.get("win_probability_percent", 50), [query.message.chat.id]
        )

        await wait_msg.edit_text(card, parse_mode="HTML")
    except Exception as e:
        await wait_msg.edit_text(f"❌ Ошибка: {e}")

@dp.message(Command("auto"))
@dp.callback_query(F.data == "btn_toggle_auto")
async def toggle_auto(event: types.TelegramObject):
    msg = event.message if isinstance(event, CallbackQuery) else event
    cid = msg.chat.id
    if is_subscribed(cid):
        remove_subscriber(cid)
        status = "ВЫКЛЮЧЕНЫ ⚪"
    else:
        add_subscriber(cid)
        status = "ВКЛЮЧЕНЫ 🟢"

    if isinstance(event, CallbackQuery):
        await event.answer(f"Авто-уведомления: {status}")
        await event.message.edit_reply_markup(reply_markup=get_main_keyboard(cid))
    else:
        await msg.answer(f"🔔 Авто-уведомления по расписанию теперь {status}.", reply_markup=get_main_keyboard(cid))

@dp.message(F.text)
async def handle_any_text(message: Message):
    add_subscriber(message.chat.id)
    text = message.text.strip()
    if text.isdigit() and len(text) >= 8:
        match_id = int(text)
        wait_msg = await message.answer(f"🔍 Загружаю матч <code>{match_id}</code> из STRATZ API...", parse_mode="HTML")
        try:
            stratz = StratzClient()
            match_data = await asyncio.to_thread(stratz.get_match, match_id)
            if not match_data:
                await wait_msg.edit_text("❌ Матч с таким ID не найден в STRATZ.")
                return

            rad_name = match_data.get("radiantTeam", {}).get("name", "Radiant")
            dire_name = match_data.get("direTeam", {}).get("name", "Dire")

            await wait_msg.edit_text(f"📊 Анализирую игроков и драфт матча {match_id}...")
            builder = MatchDossierBuilder(stratz_client=stratz)
            dossier = await asyncio.to_thread(builder.build_match_dossier, match_data)
            analyzer = DotaAIAnalyzer()
            res = await asyncio.to_thread(analyzer.analyze_dossier, dossier)
            card = format_analysis_card(match_id, res, is_live=False, rad_name=rad_name, dire_name=dire_name)

            post_tracker.track_match(
                match_id, rad_name, dire_name,
                res.get("predicted_team_name", rad_name), res.get("predicted_winner", "Radiant"),
                res.get("win_probability_percent", 50), [message.chat.id]
            )

            await wait_msg.edit_text(card, parse_mode="HTML")
        except Exception as e:
            await wait_msg.edit_text(f"❌ Ошибка: {e}")
        return

    await message.answer(
        f"Я получил ваше сообщение: <i>\"{text}\"</i>\n\n"
        "💡 <b>Чтобы разобрать матч:</b> просто отправьте мне его <b>Match ID</b> (например, <code>9088923051</code>) "
        "или выберите действие на кнопках ниже.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard(message.chat.id)
    )

async def background_post_match_monitor(bot: Bot):
    """Фоновый цикл проверки результатов матчей (проверяет каждые 45 секунд)."""
    logger.info("Запущен фоновый мониторинг результатов завершенных матчей...")
    stratz = StratzClient()
    analyzer = DotaAIAnalyzer()

    while True:
        try:
            reports = await asyncio.to_thread(post_tracker.check_finished_matches, stratz, analyzer)
            for r in reports:
                card_text = r["message_text"]
                chat_ids = r.get("chat_ids") or list(get_subscribers())
                for cid in chat_ids:
                    try:
                        await bot.send_message(cid, card_text, parse_mode="HTML")
                        logger.info(f"Отчет об исходе матча {r['match_id']} успешно доставлен {cid}!")
                    except Exception as send_err:
                        logger.error(f"Не удалось отправить результат матча {cid}: {send_err}")
        except Exception as e:
            logger.error(f"Ошибка в post_match_monitor: {e}")
        await asyncio.sleep(45)

async def smart_schedule_scheduler(bot: Bot):
    logger.info("Фоновый планировщик расписания активен.")
    notified_match_ids = set()

    while True:
        try:
            upcoming = await asyncio.to_thread(LiquipediaScheduleFetcher.get_upcoming_matches, 3)
            if not upcoming:
                await asyncio.sleep(600)
                continue

            next_match = upcoming[0]
            starts_in_sec = next_match["starts_in_seconds"]

            # Если до матча больше 5 минут, ждем
            if starts_in_sec > 300:
                sleep_duration = starts_in_sec - 300
                logger.info(
                    f"Следующий матч по расписанию: {next_match['team1']} vs {next_match['team2']} "
                    f"через {round(starts_in_sec / 60, 1)} мин."
                )
                while sleep_duration > 0:
                    chunk = min(sleep_duration, 180)
                    await asyncio.sleep(chunk)
                    sleep_duration -= chunk

            logger.info(f"Матч {next_match['team1']} vs {next_match['team2']} ожидается! Начинаем отслеживать драфт...")
            stratz = StratzClient()
            draft_found = False
            # Проверяем лобби в течение 45 минут (на случай задержек матча)
            check_attempts = 90  # 90 * 30 сек = 45 мин

            while check_attempts > 0 and not draft_found:
                check_attempts -= 1
                live_matches = await asyncio.to_thread(stratz.get_live_matches, 50)

                for m in live_matches:
                    match_id = m.get("matchId")
                    if not match_id or match_id in notified_match_ids:
                        continue

                    players = m.get("players", [])
                    picked_heroes = [p for p in players if p.get("heroId")]

                    if len(picked_heroes) == 10:
                        rad_name = m.get("radiantTeam", {}).get("name", "Radiant")
                        dire_name = m.get("direTeam", {}).get("name", "Dire")
                        logger.info(f"Драфт матча {match_id} ({rad_name} vs {dire_name}) завершен! Запуск анализа...")
                        notified_match_ids.add(match_id)
                        draft_found = True

                        builder = MatchDossierBuilder(stratz_client=stratz)
                        dossier = await asyncio.to_thread(builder.build_match_dossier, m)
                        analyzer = DotaAIAnalyzer()
                        res = await asyncio.to_thread(analyzer.analyze_dossier, dossier)
                        card = format_analysis_card(match_id, res, is_live=True, rad_name=rad_name, dire_name=dire_name)

                        subscribers = list(get_subscribers())
                        for chat_id in subscribers:
                            try:
                                await bot.send_message(chat_id, card, parse_mode="HTML")
                            except Exception as send_err:
                                logger.error(f"Не удалось отправить уведомление {chat_id}: {send_err}")

                        # Регистрируем в трекер исходов матча
                        post_tracker.track_match(
                            match_id, rad_name, dire_name,
                            res.get("predicted_team_name", rad_name), res.get("predicted_winner", "Radiant"),
                            res.get("win_probability_percent", 50), subscribers
                        )
                        break

                if not draft_found:
                    await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")
            await asyncio.sleep(60)

async def main():
    await start_health_server()

    session = None
    if TELEGRAM_PROXY:
        session = AiohttpSession(proxy=TELEGRAM_PROXY)

    bot = Bot(token=TELEGRAM_BOT_TOKEN, session=session)

    try:
        me = await bot.get_me()
        logger.info(f"Успешное подключение к Telegram! Бот: @{me.username} ({me.first_name})")
    except Exception as e:
        logger.error(f"ОШИБКА ПОДКЛЮЧЕНИЯ К TELEGRAM: {e}")
        return

    # Запускаем фоновые задачи:
    # 1. Отслеживание расписания и драфтов до игры
    asyncio.create_task(smart_schedule_scheduler(bot))
    # 2. Отслеживание результатов завершенных матчей после игры
    asyncio.create_task(background_post_match_monitor(bot))

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
