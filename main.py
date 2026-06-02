import os
import logging
from datetime import datetime, timedelta, time

from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

async def send_due_reminders(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(ZoneInfo(TIMEZONE))
    app = context.application

    try:
        reminders = list_due_reminders(now)

        for reminder in reminders:
            telegram_chat_id = reminder["telegram_chat_id"]
            title = reminder["title"]
            event_date = reminder["event_date"]
            event_time = reminder["event_time"]

            message = (
                "🔔 Нагадування\n\n"
                f"Подія: {title}\n"
                f"Дата: {event_date or 'без дати'}\n"
                f"Час: {event_time or 'без часу'}"
            )

            await app.bot.send_message(
                chat_id=telegram_chat_id,
                text=message,
            )

            mark_reminder_sent(reminder["reminder_id"])

    except Exception:
        logging.exception("Error while sending due reminders")

from ai_parser import parse_event_from_text
from database import (
    init_db,
    save_event,
    get_event,
    list_events,
    set_conversation_state,
    get_conversation_state,
    clear_conversation_state,
    save_reminder,
    list_due_reminders,
    mark_reminder_sent,
    list_reminders,
    clear_all_user_data,
    clear_user_reminders,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TIMEZONE = "Europe/Warsaw"


def parse_reminder_choice(text: str) -> str | None:
    normalized = text.lower().strip()

    if normalized in ["1", "за день", "за 1 день", "день", "за добу"]:
        return "one_day_before"

    if normalized in [
        "2",
        "в той самий день",
        "в цей день",
        "зранку",
        "в день події",
        "того дня",
        "сьогодні зранку",
    ]:
        return "same_day_morning"

    if normalized in ["3", "за годину", "за 1 годину", "годину"]:
        return "one_hour_before"

    if normalized in ["4", "за 10 хвилин", "за 10 хв", "10 хв", "10 хвилин"]:
        return "ten_minutes_before"

    if normalized in ["5", "не нагадувати", "без нагадування", "не треба"]:
        return "no_reminder"

    return None


def build_event_datetime(event) -> datetime | None:
    event_date = event.get("event_date")
    event_time = event.get("event_time")

    if not event_date:
        return None

    if event_time:
        event_datetime = datetime.combine(event_date, event_time)
    else:
        event_datetime = datetime.combine(event_date, time(hour=9, minute=0))

    return event_datetime.replace(tzinfo=ZoneInfo(TIMEZONE))


def calculate_remind_at(event, reminder_type: str) -> datetime | None:
    event_datetime = build_event_datetime(event)

    if reminder_type == "no_reminder":
        return None

    if not event_datetime:
        return None

    if reminder_type == "one_day_before":
        return event_datetime - timedelta(days=1)

    if reminder_type == "same_day_morning":
        return datetime.combine(
            event_datetime.date(),
            time(hour=9, minute=0),
            tzinfo=ZoneInfo(TIMEZONE),
        )

    if reminder_type == "one_hour_before":
        return event_datetime - timedelta(hours=1)

    if reminder_type == "ten_minutes_before":
        return event_datetime - timedelta(minutes=10)

    return None


def reminder_type_to_text(reminder_type: str) -> str:
    mapping = {
        "one_day_before": "за день",
        "same_day_morning": "в той самий день зранку",
        "one_hour_before": "за годину",
        "ten_minutes_before": "за 10 хвилин",
        "no_reminder": "без нагадування",
    }

    return mapping.get(reminder_type, reminder_type)


def format_event_response(
    parsed: dict,
    event_id: int | None = None,
    reminder_created: bool = False,
    remind_at: datetime | None = None,
) -> str:
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
    time_text = parsed.get("time") or "Не вказано"

    is_recurring = parsed.get("is_recurring", False)
    recurrence_rule = parsed.get("recurrence_rule")

    response = "Я зрозумів і зберіг подію ✅\n\n"

    if event_id:
        response += f"ID: {event_id}\n"

    response += (
        f"Назва: {title}\n"
        f"Тип: {event_type}\n"
        f"Дата: {date}\n"
        f"Час: {time_text}\n"
    )

    if is_recurring:
        response += f"Повторення: {recurrence_rule or 'так'}\n"

    if reminder_created:
        response += (
            "\nНагадування створено автоматично ✅\n"
            "Тип: за годину до події\n"
            f"Час нагадування: {format_remind_at(remind_at)}"
        )
    else:
    has_event_time = bool(parsed.get("time"))
    response += build_reminder_question(has_event_time)

    return response
    if not remind_at:
        return "без нагадування"

    return remind_at.strftime("%Y-%m-%d %H:%M")


def build_reminder_question(has_event_time: bool = False) -> str:
    if has_event_time:
        return (
            "\nКоли нагадати?\n"
            "1. За день\n"
            "2. В той самий день зранку\n"
            "3. За годину\n"
            "4. За 10 хвилин\n"
            "5. Не нагадувати"
        )

    return (
        "\nЯ бачу дату, але не бачу конкретної години події.\n"
        "Тому можу нагадати тільки відносно дня:\n"
        "1. За день\n"
        "2. В той самий день зранку\n"
        "5. Не нагадувати"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! Я твій reminder-agent 🤖\n\n"
        "Я вже вмію розуміти події, зберігати їх у базу і створювати нагадування.\n\n"
        "Напиши мені подію, наприклад:\n"
        "«Я записався на стрижку наступного вівторка о 15:00»\n\n"
        "Команди:\n"
        "/events — показати збережені події\n"
        "/reminders — показати нагадування\n"
        "/help — допомога"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Приклади повідомлень:\n\n"
        "• Завтра о 12:00 купити корм\n"
        "• У пʼятницю о 18:30 стоматолог\n"
        "• 10 березня день народження Івана\n"
        "• Наступного вівторка о 15:00 стрижка\n\n"
        "Коли бот запитає, коли нагадати, можна відповісти:\n"
        "• за день\n"
        "• за годину\n"
        "• за 10 хвилин\n"
        "• не нагадувати\n\n"
        "Команди:\n"
        "/events — показати події\n"
        "/reminders — показати нагадування"
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
    time_text = parsed.get("time") or "Не вказано"

    is_recurring = parsed.get("is_recurring", False)
    recurrence_rule = parsed.get("recurrence_rule")

    response = "Я зрозумів подію ✅\n\n"

    if event_id:
        response += f"ID: {event_id}\n"

    response += (
        f"Назва: {title}\n"
        f"Тип: {event_type}\n"
        f"Дата: {date}\n"
        f"Час: {time_text}\n"
    )

    if is_recurring:
        response += f"Повторення: {recurrence_rule or 'так'}\n"

    response += build_reminder_question()

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


def format_reminders_list(reminders: list) -> str:
    if not reminders:
        return "У тебе поки немає нагадувань."

    lines = ["Твої нагадування:\n"]

    for reminder in reminders:
        remind_at = reminder["remind_at"]
        sent = reminder["sent"]
        title = reminder["title"]

        status = "надіслано" if sent else "очікує"

        if remind_at:
            remind_text = remind_at.strftime("%Y-%m-%d %H:%M")
        else:
            remind_text = "без часу"

        lines.append(
            f"{reminder['id']}. {title}\n"
            f"   Нагадати: {remind_text}\n"
            f"   Статус: {status}"
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


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_chat_id = update.effective_chat.id

    try:
        reminders = list_reminders(telegram_chat_id)
        answer = format_reminders_list(reminders)
    except Exception as error:
        logging.exception("Error while listing reminders")
        answer = (
            "Не зміг отримати список нагадувань 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )

    await update.message.reply_text(answer)
async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_chat_id = update.effective_chat.id

    try:
        clear_all_user_data(telegram_chat_id)
        await update.message.reply_text(
            "Готово ✅\n\n"
            "Я очистив усі твої події, нагадування і тимчасові стани."
        )
    except Exception as error:
        logging.exception("Error while clearing all user data")
        await update.message.reply_text(
            "Не зміг очистити дані 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )


async def clear_reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_chat_id = update.effective_chat.id

    try:
        clear_user_reminders(telegram_chat_id)
        await update.message.reply_text(
            "Готово ✅\n\n"
            "Я очистив усі твої нагадування, але події залишив."
        )
    except Exception as error:
        logging.exception("Error while clearing reminders")
        await update.message.reply_text(
            "Не зміг очистити нагадування 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )

async def handle_pending_reminder_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state,
):
    telegram_chat_id = update.effective_chat.id
    user_text = update.message.text

    reminder_type = parse_reminder_choice(user_text)

    if not reminder_type:
        await update.message.reply_text(
            "Не зрозумів, коли нагадати 😕\n"
            "Вибери один варіант:\n"
            "1. За день\n"
            "2. В той самий день зранку\n"
            "3. За годину\n"
            "4. За 10 хвилин\n"
            "5. Не нагадувати"
        )
        return

    event_id = state["pending_event_id"]
    event = get_event(event_id, telegram_chat_id)

    if not event:
        clear_conversation_state(telegram_chat_id)
        await update.message.reply_text(
            "Не знайшов подію, для якої треба створити нагадування 😕"
        )
        return

    has_event_time = bool(event.get("event_time"))

    if not has_event_time and reminder_type in ["one_hour_before", "ten_minutes_before"]:
        await update.message.reply_text(
            "Для цієї події не вказана година, тому я не можу нагадати "
            "«за годину» або «за 10 хвилин».\n\n"
            "Вибери:\n"
            "1. За день\n"
            "2. В той самий день зранку\n"
            "5. Не нагадувати"
        )
        return

    remind_at = calculate_remind_at(event, reminder_type)

    save_reminder(
        event_id=event_id,
        telegram_chat_id=telegram_chat_id,
        remind_at=remind_at,
        reminder_type=reminder_type,
    )

    clear_conversation_state(telegram_chat_id)

    await update.message.reply_text(
        "Готово ✅\n\n"
        f"Подія: {event['title']}\n"
        f"Нагадування: {reminder_type_to_text(reminder_type)}\n"
        f"Час нагадування: {format_remind_at(remind_at)}"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    telegram_chat_id = update.effective_chat.id

    try:
        state = get_conversation_state(telegram_chat_id)

        if state and state["pending_action"] == "choose_reminder_time":
            await handle_pending_reminder_choice(update, context, state)
            return

        parsed = parse_event_from_text(user_text)

        event_id = None
        reminder_created = False
        remind_at = None

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

            event = get_event(event_id, telegram_chat_id)

            if parsed.get("date") and parsed.get("time"):
                remind_at = calculate_remind_at(event, "one_hour_before")

                save_reminder(
                    event_id=event_id,
                    telegram_chat_id=telegram_chat_id,
                    remind_at=remind_at,
                    reminder_type="one_hour_before",
                )

                reminder_created = True
                clear_conversation_state(telegram_chat_id)

            else:
                set_conversation_state(
                    telegram_chat_id=telegram_chat_id,
                    pending_action="choose_reminder_time",
                    pending_event_id=event_id,
                )

        answer = format_event_response(
            parsed,
            event_id,
            reminder_created=reminder_created,
            remind_at=remind_at,
        )

    except Exception as error:
        logging.exception("Error while handling message")
        answer = (
            "Сталася помилка при обробці повідомлення 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )

    await update.message.reply_text(answer)

async def send_due_reminders(app):
    now = datetime.now(ZoneInfo(TIMEZONE))

    try:
        reminders = list_due_reminders(now)

        for reminder in reminders:
            telegram_chat_id = reminder["telegram_chat_id"]
            title = reminder["title"]
            event_date = reminder["event_date"]
            event_time = reminder["event_time"]

            message = (
                "🔔 Нагадування\n\n"
                f"Подія: {title}\n"
                f"Дата: {event_date or 'без дати'}\n"
                f"Час: {event_time or 'без часу'}"
            )

            await app.bot.send_message(
                chat_id=telegram_chat_id,
                text=message,
            )

            mark_reminder_sent(reminder["reminder_id"])

    except Exception:
        logging.exception("Error while sending due reminders")


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Не знайдено TELEGRAM_BOT_TOKEN у Railway Variables.")

    init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("events", events_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("clear_reminders", clear_reminders_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(
    send_due_reminders,
    interval=60,
    first=10,
)

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
