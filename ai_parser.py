import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from groq import Groq


TIMEZONE = "Europe/Warsaw"


def get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError("GROQ_API_KEY не знайдено у Railway Variables")

    return Groq(api_key=api_key)


def clean_json_text(text: str) -> str:
    text = text.strip()

    if text.startswith("```json"):
        text = text.replace("```json", "", 1).strip()

    if text.startswith("```"):
        text = text.replace("```", "", 1).strip()

    if text.endswith("```"):
        text = text[:-3].strip()

    return text


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
11. Якщо це день народження і рік не вказано — використовуй найближчу майбутню дату цього дня народження.
12. Якщо користувач пише дію типу "купити ковбасу", "купити корм", "подзвонити мамі", використовуй цю дію як title. Не називай такі події просто "Нагадування".

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

    client = get_groq_client()

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_text,
            },
        ],
        temperature=0,
    )

    raw_text = response.choices[0].message.content
    raw_text = clean_json_text(raw_text)

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
            "clarification_question": f"Не зміг нормально розібрати відповідь AI. Отримав: {raw_text[:300]}",
        }
