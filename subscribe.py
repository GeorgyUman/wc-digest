"""
Автоподписка: опрашивает getUpdates, обрабатывает /start и /stop в личках,
ведёт список подписчиков в subscribers.json (коммитится workflow-ом).
"""

import json
import os
import sys

import requests

SUBSCRIBERS_FILE = "subscribers.json"

WELCOME = (
    "⚽️ Готово, ты подписан!\n\n"
    "Каждое утро в 8:00 по Лиссабону буду присылать матчи ЧМ-2026 на день: "
    "время, где смотреть, коэффициенты и короткий обзор. Плюс результаты вчерашних игр.\n\n"
    "Отписаться: /stop"
)
GOODBYE = "Отписал. Вернуться: /start"


def load_state() -> dict:
    try:
        with open(SUBSCRIBERS_FILE) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("last_update_id", 0)
    state.setdefault("chat_ids", [])
    return state


def send(token: str, chat_id: int, text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30,
    )


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        sys.exit("Не задан TELEGRAM_BOT_TOKEN")

    state = load_state()
    r = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"offset": state["last_update_id"] + 1, "timeout": 0},
        timeout=30,
    )
    r.raise_for_status()
    updates = r.json().get("result", [])

    changed = False
    for upd in updates:
        state["last_update_id"] = max(state["last_update_id"], upd["update_id"])
        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        text = (msg.get("text") or "").strip().lower()

        if chat.get("type") != "private":
            continue  # группы/каналы добавляются вручную через секрет

        chat_id = chat["id"]
        if text.startswith("/start") and chat_id not in state["chat_ids"]:
            state["chat_ids"].append(chat_id)
            send(token, chat_id, WELCOME)
            changed = True
            print(f"+ подписан {chat_id}")
        elif text.startswith("/stop") and chat_id in state["chat_ids"]:
            state["chat_ids"].remove(chat_id)
            send(token, chat_id, GOODBYE)
            changed = True
            print(f"- отписан {chat_id}")

    if updates:
        changed = True  # last_update_id сдвинулся — сохраняем в любом случае

    if changed:
        with open(SUBSCRIBERS_FILE, "w") as f:
            json.dump(state, f, indent=2)
        print(f"Всего подписчиков: {len(state['chat_ids'])}")
    else:
        print("Новых событий нет")


if __name__ == "__main__":
    main()
