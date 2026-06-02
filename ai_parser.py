import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

TIMEZONE = "Europe/Warsaw"


def parse_event_from_text(user_text: str) -> dict:
    now = datetime.now(ZoneInfo(TIMEZONE))

    system_prompt = f"""
Ти AI-парсер для Telegram reminder-agent.

Твоє завдання — перетворити повідомлення користувача в JSON.

Поточна дата і час:
{now.isoformat()}

Часовий пояс користувача:
{TIMEZONE}

Правила:
1. Відповідай тільки валідним JSON.
2. Не додавай пояснень поза JSON.
3. Якщо повідомлення містить подію, поверни intent = "create_event".
4. Якщо повідомлення не містить події, поверни intent = "unknown".
5. Якщо дата або час неясні — постав needs_clarification = true.
6. Якщо подія має повторюватися щороку, наприклад день народження, постав is_recurring = true і recurrence_rule = "FREQ=YEARLY".
7. Якщо користувач не сказав, коли нагадати, постав reminder_missing = true.
8. Для дат використовуй формат YYYY-MM-DD.
9. Для часу використовуй формат HH:MM.
10. Назву події зроби короткою і зрозумілою українською.

Формат JSON:
{{
  "intent": "create_event або unknown",
  "title": "назва події або null",
  "event_type": "appointment | birthday | task | reminder | other | null",
  "date": "YYYY-MM-DD або null",
  "time": "HH:MM або null",
  "is_recurring": true або false,
  "recurrence_rule": "FREQ=YEARLY або null",
  "reminder_missing": true або false,
  "needs_clarification": true або false,
  "clarification_question": "питання до користувача або null"
}}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_text,
            },
        ],
    )

    raw_text = response.output_text.strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {
            "intent": "unknown",
            "title": None,
            "event_type": None,
            "date": None,
            "time": None,
            "is_recurring": False,
            "recurrence_rule": None,
            "reminder_missing": False,
            "needs_clarification": True,
            "clarification_question": "Не зміг нормально розібрати повідомлення. Напиши, будь ласка, простіше.",
        }
