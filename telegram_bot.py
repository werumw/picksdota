import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery
)
from aiogram.client.session.aiohttp import AiohttpSession

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PROXY, STRATZ_API_KEY
from subscriber_manager import add_subscriber, remove_subscriber, is_subscribed, get_subscribers
from stratz_client import StratzClient
from schedule_fetcher import LiquipediaScheduleFetcher
from live_tracker import LiveMatchTracker
from dossier_builder import MatchDossierBuilder
from ai_analyzer import DotaAIAnalyzer
from odds_calculator import OddsCalculator
from post_match_tracker import PostMatchTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("DotaTelegramBot")

post_tracker = PostMatchTracker()

# In-memory stores
HANDLED_MATCH_IDS = set()
PENDING_DRAFT_MATCHES: Dict[int, Dict[str, Any]] = {}
ACTIVE_LIVE_MATCHES: Dict[int, Dict[str, Any]] = {}

SAMPLE_PRO_MATCH = {
    "id": 9088923051,
    "radiantTeam": {"name": "Team Spirit"},
    "direTeam": {"name": "Team Liquid"},
    "radiantScore": 34,
    "direScore": 21,
    "durationSeconds": 2480,
    "players": [
        {"steamAccountId": 172099728, "heroId": 53, "role": 1, "lane": 1, "kills": 9, "deaths": 2, "assists": 14, "isRadiant": True, "steamAccount": {"name": "Kiritych~", "proSteamAccount": {"name": "Kiritych"}}},
        {"steamAccountId": 858106446, "heroId": 107, "role": 2, "lane": 2, "kills": 12, "deaths": 4, "assists": 11, "isRadiant": True, "steamAccount": {"name": "kiyotaka", "proSteamAccount": {"name": "kiyotaka"}}},
        {"steamAccountId": 165564598, "heroId": 78, "role": 3, "lane": 3, "kills": 5, "deaths": 3, "assists": 18, "isRadiant": True, "steamAccount": {"name": "MieRo", "proSteamAccount": {"name": "MieRo"}}},
        {"steamAccountId": 317880638, "heroId": 86, "role": 4, "lane": 3, "kills": 4, "deaths": 6, "assists": 22, "isRadiant": True, "steamAccount": {"name": "Save-", "proSteamAccount": {"name": "Save-"}}},
        {"steamAccountId": 196878136, "heroId": 50, "role": 5, "lane": 1, "kills": 4, "deaths": 6, "assists": 20, "isRadiant": True, "steamAccount": {"name": "Kataomi`", "proSteamAccount": {"name": "Kataomi`"}}},
        {"steamAccountId": 124801757, "heroId": 1, "role": 1, "lane": 1, "kills": 6, "deaths": 6, "assists": 7, "isRadiant": False, "steamAccount": {"name": "miCKe", "proSteamAccount": {"name": "miCKe"}}},
        {"steamAccountId": 152962063, "heroId": 22, "role": 2, "lane": 2, "kills": 7, "deaths": 7, "assists": 9, "isRadiant": False, "steamAccount": {"name": "Nisha", "proSteamAccount": {"name": "Nisha"}}},
        {"steamAccountId": 86799324, "heroId": 98, "role": 3, "lane": 3, "kills": 3, "deaths": 8, "assists": 10, "isRadiant": False, "steamAccount": {"name": "33", "proSteamAccount": {"name": "33"}}},
        {"steamAccountId": 89117038, "heroId": 87, "role": 4, "lane": 3, "kills": 2, "deaths": 7, "assists": 12, "isRadiant": False, "steamAccount": {"name": "Boxi", "proSteamAccount": {"name": "Boxi"}}},
        {"steamAccountId": 10366616, "heroId": 64, "role": 5, "lane": 1, "kills": 3, "deaths": 6, "assists": 11, "isRadiant": False, "steamAccount": {"name": "Insania", "proSteamAccount": {"name": "Insania"}}}
    ]
}

async def health_check_handler(request):
    return web.Response(text="OK - Dota 2 AI Bot Active (Paris / Alwaysdata)")

async def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/healthz", health_check_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    try:
        await site.start()
        logger.info(f"Health-check HTTP сервер слушает порт {port}")
    except Exception as e:
        logger.warning(f"Не удалось запустить HTTP сервер на {port}: {e}")

def get_main_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    is_sub = is_subscribed(chat_id)
    btn_auto_text = "🔔 Авто-уведомления: ВКЛ" if is_sub else "🔕 Авто-уведомления: ВЫКЛ"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Расписание турниров", callback_data="btn_schedule"),
            InlineKeyboardButton(text="⚡ Тестовый анализ", callback_data="btn_test")
        ],
        [
            InlineKeyboardButton(text="🔴 Проверить Live сейчас", callback_data="btn_live"),
            InlineKeyboardButton(text=btn_auto_text, callback_data="btn_toggle_auto")
        ]
    ])
    return kb

def format_analysis_card(match_id: Any, res: Dict[str, Any], is_live: bool = False, rad_name: str = "Radiant", dire_name: str = "Dire", tier: int = 1) -> str:
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

    tier_badge = "🏆 [Tier 1]" if tier == 1 else ("🥈 [Tier 2]" if tier == 2 else "🥉 [Tier 3]")
    header = f"🔴 <b>LIVE-ДРАФТ ЗАВЕРШЕН {tier_badge}!</b>" if is_live else "📊 <b>АНАЛИЗ МАТЧА DOTA 2</b>"

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
        "👋 <b>Привет! Я бот глубокого AI-анализа матчей Dota 2.</b>\n\n"
        "✅ <b>Вы успешно подписаны на уведомления!</b>\n\n"
        "<b>Как работает система:</b>\n"
        "1. 🏆 <b>Турниры Tier-1:</b> анализируются <b>полностью автоматически</b> сразу после стадии драфта.\n"
        "2. 🥈🥉 <b>Турниры Tier-2 и Tier-3:</b> когда начнется их драфт, бот пришлет вам запрос с кнопкой <code>[🎯 Анализировать]</code> — вы сами решаете, разбирать матч или пропустить.\n"
        "3. 💰 <b>Коэффициенты букмекеров:</b> расчет вероятностей, справедливого кэфа и +EV ставок.\n"
        "4. 🏁 <b>Результат после игры:</b> по окончании матча бот пришлет отчет (зашел ли прогноз и тактический разбор, почему).\n\n"
        "<b>Команды:</b>\n"
        "• Отправьте <b>ID любого матча</b> (например: <code>9088923051</code>) для мгновенного разбора.\n"
        "• <code>/schedule</code> — расписание матчей с разбивкой по Tier.\n"
        "• <code>/live</code> — проверить текущие живые игры.\n"
        "• <code>/test</code> — демонстрационный пример отчета."
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
            rad_name="Team Spirit", dire_name="Team Liquid", tier=1
        )

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
    matches = await asyncio.to_thread(LiquipediaScheduleFetcher.get_upcoming_matches, 8)

    if not matches:
        await wait_msg.edit_text("😴 На ближайшее время матчей в расписании не найдено.", reply_markup=get_main_keyboard(msg.chat.id))
        return

    text = "📅 <b>БЛИЖАЙШИЕ МАТЧИ ПО РАСПИСАНИЮ:</b>\n\n"
    for idx, m in enumerate(matches, 1):
        mins = m["starts_in_minutes"]
        time_hint = f"через {int(mins)} мин" if mins > 0 else "прямо сейчас!"
        tier_num = m.get("tier", 2)
        tier_icon = "🏆 [Tier 1]" if tier_num == 1 else ("🥈 [Tier 2]" if tier_num == 2 else "🥉 [Tier 3]")

        text += (
            f"<b>{idx}. {tier_icon} {m['team1']} vs {m['team2']}</b>\n"
            f"🏆 Турнир: <i>{m['tournament']}</i>\n"
            f"🕒 Начало: <code>{m['datetime_utc']}</code> ({time_hint})\n\n"
        )
    text += (
        "ℹ️ <i>Матчи <b>Tier 1</b> анализируются автоматически сразу при старте драфта.\n"
        "Для матчей <b>Tier 2 и 3</b> бот пришлет интерактивный запрос, когда начнется их драфт.</i>"
    )
    await wait_msg.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyboard(msg.chat.id))

@dp.message(Command("live"))
@dp.callback_query(F.data == "btn_live")
async def handle_live(event: types.TelegramObject):
    msg = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer("Проверяю live матчи...")

    add_subscriber(msg.chat.id)
    wait_msg = await msg.answer("🔎 Сканирую live-серверы Dota 2...")

    try:
        stratz = StratzClient()
        live = await asyncio.to_thread(LiveMatchTracker.get_live_matches, stratz)

        if not live:
            await wait_msg.edit_text("😴 Сейчас нет активных официальных матчей на стадии драфта.", reply_markup=get_main_keyboard(msg.chat.id))
            return

        # Сохраняем в кэш
        for m in live:
            ACTIVE_LIVE_MATCHES[m["match_id"]] = m

        tour_matches = [m for m in live if m["match_type"] == "tournament"]
        pub_matches = [m for m in live if m["match_type"] != "tournament"]

        text = f"🔴 <b>НАЙДЕНО LIVE-МАТЧЕЙ: {len(live)}</b>\n\n"
        buttons = []

        if tour_matches:
            text += "🏆 <b>Официальные турнирные матчи:</b>\n"
            for m in tour_matches[:5]:
                mid = m["match_id"]
                rad = m["radiant_name"]
                dire = m["dire_name"]
                p_cnt = m["picked_count"]
                status = "✅ Драфт завершен" if m["draft_complete"] else f"⏳ Драфт ({p_cnt}/10)"
                text += f"• <b>{rad}</b> vs <b>{dire}</b> (ID: <code>{mid}</code> | {status})\n"
                buttons.append([InlineKeyboardButton(text=f"🎯 Анализ: {rad} vs {dire}", callback_data=f"analyze_{mid}")])
            text += "\n"

        if pub_matches and len(buttons) < 5:
            text += "🔥 <b>Матчи Pro / High-MMR (Immortal):</b>\n"
            for m in pub_matches[:(5 - len(buttons))]:
                mid = m["match_id"]
                rad = m["radiant_name"]
                dire = m["dire_name"]
                mmr = m.get("avg_mmr", 0)
                text += f"• <b>{rad}</b> vs <b>{dire}</b> (ID: <code>{mid}</code>, MMR: ~{mmr})\n"
                buttons.append([InlineKeyboardButton(text=f"🎯 Анализ: {rad} vs {dire}", callback_data=f"analyze_{mid}")])

        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await wait_msg.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.error(f"Ошибка в handle_live: {e}")
        await wait_msg.edit_text(f"❌ Ошибка получения Live: {e}")

@dp.callback_query(F.data.startswith("confirm_draft_"))
async def cb_confirm_draft(query: CallbackQuery):
    match_id = int(query.data.split("_")[2])
    await query.answer("Запускаю анализ драфта...")
    wait_msg = await query.message.answer(f"⏳ Сбор данных и расчет коэффициентов для матча <code>{match_id}</code>...")

    try:
        # Проверяем кэш драфта
        match_data = PENDING_DRAFT_MATCHES.get(match_id) or ACTIVE_LIVE_MATCHES.get(match_id)
        stratz = StratzClient()

        if not match_data:
            match_data = await asyncio.to_thread(stratz.get_match, match_id)

        rad_name = match_data.get("radiant_name") or match_data.get("radiantTeam", {}).get("name", "Radiant")
        dire_name = match_data.get("dire_name") or match_data.get("direTeam", {}).get("name", "Dire")

        builder = MatchDossierBuilder(stratz_client=stratz)
        dossier = await asyncio.to_thread(builder.build_match_dossier, match_data)
        analyzer = DotaAIAnalyzer()
        res = await asyncio.to_thread(analyzer.analyze_dossier, dossier)
        card = format_analysis_card(match_id, res, is_live=True, rad_name=rad_name, dire_name=dire_name, tier=2)

        post_tracker.track_match(
            match_id, rad_name, dire_name,
            res.get("predicted_team_name", rad_name), res.get("predicted_winner", "Radiant"),
            res.get("win_probability_percent", 50), [query.message.chat.id]
        )

        await wait_msg.edit_text(card, parse_mode="HTML")
        # Удаляем клавиатуру из сообщения с запросом
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Ошибка в cb_confirm_draft: {e}")
        await wait_msg.edit_text(f"❌ Ошибка анализа: {e}")

@dp.callback_query(F.data.startswith("skip_draft_"))
async def cb_skip_draft(query: CallbackQuery):
    match_id = query.data.split("_")[2]
    await query.answer("Матч пропущен.")
    try:
        await query.message.edit_text(f"❌ <i>Анализ матча ID <code>{match_id}</code> пропущен пользователем.</i>", parse_mode="HTML")
    except Exception:
        pass

@dp.callback_query(F.data.startswith("analyze_"))
async def cb_analyze_live(query: CallbackQuery):
    match_id = int(query.data.split("_")[1])
    await query.answer("Анализирую...")
    wait_msg = await query.message.answer(f"⏳ Сбор данных и расчет коэффициентов для матча <code>{match_id}</code>...")

    try:
        match_data = ACTIVE_LIVE_MATCHES.get(match_id)
        stratz = StratzClient()
        if not match_data:
            match_data = await asyncio.to_thread(stratz.get_match, match_id)

        rad_name = match_data.get("radiant_name") or match_data.get("radiantTeam", {}).get("name", "Radiant")
        dire_name = match_data.get("dire_name") or match_data.get("direTeam", {}).get("name", "Dire")

        builder = MatchDossierBuilder(stratz_client=stratz)
        dossier = await asyncio.to_thread(builder.build_match_dossier, match_data)
        analyzer = DotaAIAnalyzer()
        res = await asyncio.to_thread(analyzer.analyze_dossier, dossier)
        card = format_analysis_card(match_id, res, is_live=True, rad_name=rad_name, dire_name=dire_name, tier=2)

        post_tracker.track_match(
            match_id, rad_name, dire_name,
            res.get("predicted_team_name", rad_name), res.get("predicted_winner", "Radiant"),
            res.get("win_probability_percent", 50), [query.message.chat.id]
        )

        await wait_msg.edit_text(card, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка в cb_analyze_live: {e}")
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

@dp.message(F.text.regexp(r"^\d{9,11}$"))
async def handle_direct_match_id(message: Message):
    match_id = int(message.text.strip())
    add_subscriber(message.chat.id)
    wait_msg = await message.answer(f"⏳ Сбор данных для матча <code>{match_id}</code>...")

    try:
        match_data = ACTIVE_LIVE_MATCHES.get(match_id)
        stratz = StratzClient()
        if not match_data:
            match_data = await asyncio.to_thread(stratz.get_match, match_id)

        rad_name = match_data.get("radiant_name") or match_data.get("radiantTeam", {}).get("name", "Radiant")
        dire_name = match_data.get("dire_name") or match_data.get("direTeam", {}).get("name", "Dire")

        builder = MatchDossierBuilder(stratz_client=stratz)
        dossier = await asyncio.to_thread(builder.build_match_dossier, match_data)
        analyzer = DotaAIAnalyzer()
        res = await asyncio.to_thread(analyzer.analyze_dossier, dossier)
        card = format_analysis_card(match_id, res, is_live=False, rad_name=rad_name, dire_name=dire_name, tier=2)

        post_tracker.track_match(
            match_id, rad_name, dire_name,
            res.get("predicted_team_name", rad_name), res.get("predicted_winner", "Radiant"),
            res.get("win_probability_percent", 50), [message.chat.id]
        )

        await wait_msg.edit_text(card, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка в handle_direct_match_id: {e}")
        await wait_msg.edit_text(f"❌ Ошибка анализа матча: {e}")

async def background_post_match_monitor(bot: Bot):
    """Фоновый воркер: проверяет завершение отслеживаемых матчей и рассылает результаты."""
    logger.info("Запущен фоновый мониторинг результатов завершенных матчей...")
    stratz = StratzClient()
    ai = DotaAIAnalyzer()

    while True:
        try:
            finished = await asyncio.to_thread(post_tracker.check_finished_matches, stratz, ai)
            for item in finished:
                card = item["message_text"]
                cids = item["chat_ids"]
                logger.info(f"Матч {item['match_id']} завершен! Рассылаем результаты {len(cids)} подписчикам.")
                for cid in cids:
                    try:
                        await bot.send_message(cid, card, parse_mode="HTML")
                    except Exception as send_err:
                        logger.error(f"Не удалось отправить результат матча {cid}: {send_err}")
        except Exception as e:
            logger.error(f"Ошибка в post_match_monitor: {e}")
        await asyncio.sleep(45)

async def smart_schedule_scheduler(bot: Bot):
    """
    Фоновый планировщик расписания:
    - Tier-1: автоматический анализ драфта и отправка полной сводки.
    - Tier-2 / Tier-3: интерактивный запрос подписчикам с кнопками [🎯 Анализировать] [❌ Пропустить].
    """
    logger.info("Фоновый планировщик расписания активен.")
    stratz = StratzClient()

    while True:
        try:
            # 1. Получаем расписание предстоящих игр
            upcoming = await asyncio.to_thread(LiquipediaScheduleFetcher.get_upcoming_matches, 8)

            # 2. Получаем текущие live матчи
            live_matches = await asyncio.to_thread(LiveMatchTracker.get_live_matches, stratz)

            # Обновляем кэш live матчей
            for m in live_matches:
                ACTIVE_LIVE_MATCHES[m["match_id"]] = m

            tournament_live = [m for m in live_matches if m["match_type"] == "tournament"]

            for lm in tournament_live:
                mid = lm["match_id"]
                if mid in HANDLED_MATCH_IDS:
                    continue

                # Проверяем, завершился ли драфт (все 10 героев выбраны)
                if not lm["draft_complete"]:
                    continue

                rad_name = lm["radiant_name"]
                dire_name = lm["dire_name"]

                # Ищем соответствие в расписании Liquipedia для определения Tier
                matched_scheduled = LiveMatchTracker.find_match_by_teams(
                    [rad_name], [dire_name],
                    [{"radiant_name": u["team1"], "dire_name": u["team2"], "tier": u["tier"], "tournament": u["tournament"]} for u in upcoming]
                )

                if matched_scheduled:
                    tier = matched_scheduled.get("tier", 2)
                    tour_name = matched_scheduled.get("tournament", "Pro Tournament")
                else:
                    # Эвристика по ключевым словам турнира / команд
                    tier = LiquipediaScheduleFetcher.get_tournament_tier(rad_name + " " + dire_name, rad_name + " " + dire_name)
                    tour_name = "Tournament Match"

                HANDLED_MATCH_IDS.add(mid)

                subscribers = list(get_subscribers())
                if not subscribers:
                    continue

                if tier == 1:
                    # TIER-1: ПОЛНОСТЬЮ АВТОМАТИЧЕСКИЙ АНАЛИЗ
                    logger.info(f"🏆 Tier-1 матч {mid} ({rad_name} vs {dire_name}) обнаружен! Запуск авто-анализа...")
                    builder = MatchDossierBuilder(stratz_client=stratz)
                    dossier = await asyncio.to_thread(builder.build_match_dossier, lm)
                    analyzer = DotaAIAnalyzer()
                    res = await asyncio.to_thread(analyzer.analyze_dossier, dossier)
                    card = format_analysis_card(mid, res, is_live=True, rad_name=rad_name, dire_name=dire_name, tier=1)

                    for chat_id in subscribers:
                        try:
                            await bot.send_message(chat_id, card, parse_mode="HTML")
                        except Exception as send_err:
                            logger.error(f"Не удалось отправить уведомление {chat_id}: {send_err}")

                    post_tracker.track_match(
                        mid, rad_name, dire_name,
                        res.get("predicted_team_name", rad_name), res.get("predicted_winner", "Radiant"),
                        res.get("win_probability_percent", 50), subscribers
                    )

                else:
                    # TIER-2 / TIER-3: ИНТЕРАКТИВНЫЙ ЗАПРОС С КНОПКАМИ ПОДТВЕРЖДЕНИЯ
                    logger.info(f"🥈🥉 Tier-{tier} матч {mid} ({rad_name} vs {dire_name}) на стадии драфта. Отправляем запрос...")
                    PENDING_DRAFT_MATCHES[mid] = lm

                    tier_badge = "🥈 [Tier 2]" if tier == 2 else "🥉 [Tier 3]"
                    prompt_text = (
                        f"⚔️ <b>Начался драфт матча!</b> {tier_badge}\n\n"
                        f"🏆 Турнир: <b>{tour_name}</b>\n"
                        f"🆚 <b>{rad_name}</b> vs <b>{dire_name}</b>\n"
                        f"🆔 Match ID: <code>{mid}</code>\n\n"
                        f"<i>Желаете запустить глубокий AI-анализ драфта и расчет коэффициентов?</i>"
                    )

                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="🎯 Анализировать драфт", callback_data=f"confirm_draft_{mid}"),
                            InlineKeyboardButton(text="❌ Пропустить", callback_data=f"skip_draft_{mid}")
                        ]
                    ])

                    for chat_id in subscribers:
                        try:
                            await bot.send_message(chat_id, prompt_text, parse_mode="HTML", reply_markup=kb)
                        except Exception as send_err:
                            logger.error(f"Не удалось отправить запрос {chat_id}: {send_err}")

        except Exception as e:
            logger.error(f"Ошибка в smart_schedule_scheduler: {e}")

        # Проверяем каждые 35 секунд
        await asyncio.sleep(35)

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
    asyncio.create_task(smart_schedule_scheduler(bot))
    asyncio.create_task(background_post_match_monitor(bot))

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
