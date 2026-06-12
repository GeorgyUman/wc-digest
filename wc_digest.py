"""
Ежедневный дайджест матчей ЧМ-2026 в Telegram.

Логика:
1. Берём матчи и коэффициенты из The Odds API (окно: сегодня 06:00 — завтра 06:00 по Лиссабону).
2. Просим Claude (с web search) написать по каждому матчу: где смотреть в Португалии
   (бесплатный канал, если есть) + 2 предложения обзора с фан-фактами и положением в группе.
3. Отправляем форматированное сообщение в Telegram.

Нужные переменные окружения (в GitHub — Secrets):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ODDS_API_KEY, ANTHROPIC_API_KEY
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

LISBON = ZoneInfo("Europe/Lisbon")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ANTHROPIC_MODEL = "claude-sonnet-4-6"

PREFERRED_BOOKMAKERS = ["betclic", "bwin", "unibet", "pinnacle", "williamhill"]


# ---------------------------------------------------------------- helpers

def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Не задана переменная окружения {name}")
    return value


def esc(text: str) -> str:
    """Экранирование для Telegram HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- odds api

def find_world_cup_sport_key(api_key: str) -> str:
    """Находим ключ турнира динамически, чтобы не хардкодить."""
    r = requests.get(
        f"{ODDS_API_BASE}/sports/",
        params={"apiKey": api_key, "all": "true"},
        timeout=30,
    )
    r.raise_for_status()
    candidates = [
        s["key"]
        for s in r.json()
        if "fifa_world_cup" in s["key"]
        and "winner" not in s["key"]
        and "qualifier" not in s["key"]
        and s.get("group", "").lower() == "soccer"
    ]
    if not candidates:
        sys.exit("Не нашёл ЧМ в списке турниров The Odds API")
    return candidates[0]


def fetch_todays_matches(api_key: str) -> list[dict]:
    sport_key = find_world_cup_sport_key(api_key)
    r = requests.get(
        f"{ODDS_API_BASE}/sports/{sport_key}/odds/",
        params={
            "apiKey": api_key,
            "regions": "eu",
            "markets": "h2h",
            "dateFormat": "iso",
            "oddsFormat": "decimal",
        },
        timeout=30,
    )
    r.raise_for_status()
    events = r.json()

    now_lisbon = datetime.now(LISBON)
    window_start = now_lisbon.replace(hour=6, minute=0, second=0, microsecond=0)
    if now_lisbon < window_start:  # запуск до 6 утра — берём предыдущий день
        window_start -= timedelta(days=1)
    window_end = window_start + timedelta(days=1)

    matches = []
    for ev in events:
        kickoff_utc = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        kickoff = kickoff_utc.astimezone(LISBON)
        if not (window_start <= kickoff < window_end):
            continue
        matches.append(
            {
                "home": ev["home_team"],
                "away": ev["away_team"],
                "kickoff": kickoff,
                "odds": extract_odds(ev),
            }
        )

    matches.sort(key=lambda m: m["kickoff"])
    return matches


def extract_odds(event: dict) -> dict | None:
    bookmakers = event.get("bookmakers", [])
    if not bookmakers:
        return None
    chosen = None
    for pref in PREFERRED_BOOKMAKERS:
        chosen = next((b for b in bookmakers if b["key"] == pref), None)
        if chosen:
            break
    chosen = chosen or bookmakers[0]

    market = next((m for m in chosen.get("markets", []) if m["key"] == "h2h"), None)
    if not market:
        return None
    prices = {o["name"]: o["price"] for o in market["outcomes"]}
    return {
        "bookmaker": chosen["title"],
        "home": prices.get(event["home_team"]),
        "draw": prices.get("Draw"),
        "away": prices.get(event["away_team"]),
    }


# ---------------------------------------------------------------- claude

def build_claude_prompt(matches: list[dict]) -> str:
    today = datetime.now(LISBON).strftime("%d.%m.%Y")
    lines = [
        f"{i+1}. {m['home']} — {m['away']}, начало {m['kickoff'].strftime('%H:%M %d.%m')} по Лиссабону"
        for i, m in enumerate(matches)
    ]
    match_list = "\n".join(lines)

    return f"""Сегодня {today}. Вот матчи ЧМ-2026 по футболу на ближайшие сутки:

{match_list}

Для КАЖДОГО матча мне нужно:

1. "tv" — где смотреть в Португалии. Все матчи показывает Sport TV (платный).
   Бесплатно: ~20 матчей в открытом эфире на RTP / SIC / TVI (все матчи Португалии,
   матч открытия, полуфиналы, финал и ряд топ-матчей), плюс LiveModeTV бесплатно
   стримит ~34 матча на YouTube. Проверь через поиск, какой канал показывает каждый
   из этих матчей, и укажи самый доступный бесплатный вариант. Если бесплатного нет —
   напиши "Sport TV (платный)". Формат: короткая строка, например
   "RTP1 (бесплатно)" или "LiveModeTV на YouTube (бесплатно)" или "Sport TV (платный)".

2. "preview" — ровно 2 предложения на русском: текущее положение команд в группе
   (очки, что на кону), интересный фан-факт, форма, ключевые игроки — что-то живое,
   не сухая сводка. Используй поиск для актуальных данных (результаты прошлых туров,
   турнирное положение).

Ответь ТОЛЬКО валидным JSON-массивом без markdown-обёртки и без текста до/после:
[{{"match": 1, "tv": "...", "preview": "..."}}, ...]"""


def ask_claude(api_key: str, matches: list[dict]) -> list[dict]:
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 4000,
            "messages": [{"role": "user", "content": build_claude_prompt(matches)}],
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 8,
                }
            ],
        },
        timeout=300,
    )
    r.raise_for_status()
    data = r.json()

    text = "\n".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )

    # Вырезаем JSON-массив даже если модель что-то добавила вокруг
    cleaned = re.sub(r"```(json)?", "", text).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1:
        print("Не смог распарсить ответ Claude, использую заглушки. Ответ был:\n", text)
        return []
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        print("JSON невалиден, использую заглушки. Ответ был:\n", text)
        return []


# ---------------------------------------------------------------- format

def format_message(matches: list[dict], previews: list[dict]) -> str:
    today = datetime.now(LISBON).strftime("%d.%m.%Y")
    preview_by_idx = {p.get("match"): p for p in previews}

    parts = [f"⚽️ <b>ЧМ-2026 · матчи на {today}</b>\n(время — Лиссабон, вкл. ночные игры)"]

    for i, m in enumerate(matches):
        p = preview_by_idx.get(i + 1, {})
        block = [f"\n<b>{esc(m['home'])} — {esc(m['away'])}</b>"]
        block.append(f"🕗 {m['kickoff'].strftime('%H:%M')} ({m['kickoff'].strftime('%a %d.%m')})")
        block.append(f"📺 {esc(p.get('tv', 'Sport TV (платный)'))}")

        odds = m["odds"]
        if odds and odds["home"] and odds["away"]:
            draw = f" · X {odds['draw']}" if odds.get("draw") else ""
            block.append(
                f"📊 П1 {odds['home']}{draw} · П2 {odds['away']} <i>({esc(odds['bookmaker'])})</i>"
            )

        if p.get("preview"):
            block.append(f"📝 {esc(p['preview'])}")

        parts.append("\n".join(block))

    return "\n".join(parts)


# ---------------------------------------------------------------- telegram

def send_telegram(token: str, chat_id: str, text: str) -> None:
    """Шлём, разбивая на куски < 4096 символов по границам матчей."""
    chunks, current = [], ""
    for block in text.split("\n\n"):
        candidate = (current + "\n\n" + block) if current else block
        if len(candidate) > 3900:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)

    for chunk in chunks:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        if not r.ok:
            print("Telegram error:", r.text)
        r.raise_for_status()


# ---------------------------------------------------------------- main

def main() -> None:
    tg_token = env("TELEGRAM_BOT_TOKEN")
    tg_chat = env("TELEGRAM_CHAT_ID")
    odds_key = env("ODDS_API_KEY")
    anthropic_key = env("ANTHROPIC_API_KEY")

    matches = fetch_todays_matches(odds_key)
    today = datetime.now(LISBON).strftime("%d.%m.%Y")

    if not matches:
        send_telegram(tg_token, tg_chat, f"⚽️ ЧМ-2026: на {today} матчей нет. Выходной 🙂")
        return

    previews = ask_claude(anthropic_key, matches)
    message = format_message(matches, previews)
    send_telegram(tg_token, tg_chat, message)
    print(f"Отправлено: {len(matches)} матч(ей)")


if __name__ == "__main__":
    main()
