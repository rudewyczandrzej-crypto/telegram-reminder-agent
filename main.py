import os
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from ai_parser import parse_event_from_text
from database import init_db, save_event, list_events


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! Я твій reminder-agent 🤖\n\n"
        "Я вже вмію розуміти події і зберігати їх у базу.\n\n"
        "Напиши мені подію, наприклад:\n"
        "«Я записався на стрижку наступного вівторка о 15:00»\n\n"
        "Команди:\n"
        "/events — показати збережені події\n"
        "/help — допомога"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Приклади повідомлень:\n\n"
        "• Завтра о 12:00 купити корм\n"
        "• У пʼятницю о 18:30 стоматолог\n"
        "• 10 березня день народження Івана\n"
        "• Наступного вівторка о 15:00 стрижка\n\n"
        "Команди:\n"
        "/events — показати найближчі збережені події"
    )


def format_event_response(parsed: dict, event_id: int | None = None) -> str:
    if parsed.get("intent") != "create_event":
        question = parsed.get("clarification_question")
        if question:
            return question

        return (
            "Я поки не бачу тут конкретної події 🤔\n\n"
            "Напиши, наприклад:\n"
            "«Завтра о 12:00 купити корм»"
        )

    title = parsed.get("title") or "Не вказано"
    event_type = parsed.get("event_type") or "Не вказано"
    date = parsed.get("date") or "Не вказано"
    time = parsed.get("time") or "Не вказано"

    is_recurring = parsed.get("is_recurring", False)
    recurrence_rule = parsed.get("recurrence_rule")

    response = "Я зрозумів і зберіг подію ✅\n\n"

    if event_id:
        response += f"ID: {event_id}\n"

    response += (
        f"Назва: {title}\n"
        f"Тип: {event_type}\n"
        f"Дата: {date}\n"
        f"Час: {time}\n"
    )

    if is_recurring:
        response += f"Повторення: {recurrence_rule or 'так'}\n"

    if parsed.get("reminder_missing"):
        response += (
            "\nНаступним кроком ми навчимо бота питати і зберігати час нагадування.\n"
            "Поки що подія просто збережена в базу."
        )

    return response


def format_events_list(events: list) -> str:
    if not events:
        return (
            "У тебе поки немає збережених подій.\n\n"
            "Напиши, наприклад:\n"
            "«Завтра о 12:00 купити корм»"
        )

    lines = ["Твої збережені події:\n"]

    for event in events:
        event_id = event["id"]
        title = event["title"]
        event_date = event["event_date"] or "без дати"
        event_time = event["event_time"] or "без часу"

        recurring_text = ""
        if event["is_recurring"]:
            recurring_text = " 🔁"

        lines.append(
            f"{event_id}. {title}{recurring_text}\n"
            f"   Дата: {event_date}, час: {event_time}"
        )

    return "\n\n".join(lines)


async def events_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_chat_id = update.effective_chat.id

    try:
        events = list_events(telegram_chat_id)
        answer = format_events_list(events)
    except Exception as error:
        logging.exception("Error while listing events")
        answer = (
            "Не зміг отримати список подій 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )

    await update.message.reply_text(answer)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    telegram_chat_id = update.effective_chat.id

    try:
        parsed = parse_event_from_text(user_text)

        event_id = None

        if parsed.get("intent") == "create_event":
            event_id = save_event(
                telegram_chat_id=telegram_chat_id,
                title=parsed.get("title") or "Без назви",
                event_type=parsed.get("event_type"),
                event_date=parsed.get("date"),
                event_time=parsed.get("time"),
                is_recurring=parsed.get("is_recurring", False),
                recurrence_rule=parsed.get("recurrence_rule"),
                reminder_missing=parsed.get("reminder_missing", True),
            )

        answer = format_event_response(parsed, event_id)

    except Exception as error:
        logging.exception("Error while handling message")
        answer = (
            "Сталася помилка при обробці повідомлення 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )

    await update.message.reply_text(answer)


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Не знайдено TELEGRAM_BOT_TOKEN у Railway Variables.")

    init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("events", events_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
