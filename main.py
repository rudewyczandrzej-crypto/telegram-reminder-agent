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


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! Я твій reminder-agent 🤖\n\n"
        "Напиши мені подію, наприклад:\n"
        "«Я записався на стрижку наступного вівторка о 15:00»"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я вчуся розуміти події з тексту.\n\n"
        "Приклади:\n"
        "• Завтра о 12:00 купити корм\n"
        "• У пʼятницю о 18:30 стоматолог\n"
        "• 10 березня день народження Івана\n"
    )


def format_event_response(parsed: dict) -> str:
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

    response = (
        "Я зрозумів подію ✅\n\n"
        f"Назва: {title}\n"
        f"Тип: {event_type}\n"
        f"Дата: {date}\n"
        f"Час: {time}\n"
    )

    if is_recurring:
        response += f"Повторення: {recurrence_rule or 'так'}\n"

    if parsed.get("needs_clarification"):
        question = parsed.get("clarification_question")
        if question:
            response += f"\nПитання: {question}"
            return response

    if parsed.get("reminder_missing"):
        response += (
            "\nКоли нагадати?\n"
            "1. За день\n"
            "2. В той самий день зранку\n"
            "3. За годину\n"
            "4. За 10 хвилин"
        )

    return response


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    try:
        parsed = parse_event_from_text(user_text)
        answer = format_event_response(parsed)
    except Exception as error:
        logging.exception("Error while parsing message")
        answer = (
            "Сталася помилка при розборі повідомлення 😕\n\n"
            "Перевір, чи доданий OPENAI_API_KEY у Railway Variables."
        )

    await update.message.reply_text(answer)


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Не знайдено TELEGRAM_BOT_TOKEN у змінних середовища.")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
