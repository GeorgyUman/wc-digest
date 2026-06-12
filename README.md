# ЧМ-2026 → Telegram дайджест

Каждое утро в 08:00 по Лиссабону присылает в Telegram матчи на сегодня (вкл. ночные):
время по Лиссабону, где смотреть в Португалии (бесплатный канал, если есть),
коэффициенты букмекеров и 2 предложения обзора на каждый матч.

## Секреты (Settings → Secrets and variables → Actions)

| Secret | Откуда |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather → /newbot |
| `TELEGRAM_CHAT_ID` | @userinfobot → Your ID |
| `ODDS_API_KEY` | the-odds-api.com (бесплатный тариф) |
| `ANTHROPIC_API_KEY` | console.anthropic.com (web search должен быть включён в настройках организации) |

## Тест

Actions → "WC 2026 Daily Digest" → Run workflow.

## Стоимость

GitHub Actions и Odds API — бесплатно. Anthropic API: 1 запрос Sonnet
с web search в день ≈ $0.10–0.15/день на время турнира.
