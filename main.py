import os
import logging
from datetime import datetime, timedelta, time, date

from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from ai_parser import parse_event_from_text
from database import (
    init_db,
    save_event,
    get_event,
    list_events,
    list_events_between,
    delete_event,
    set_conversation_state,
    get_conversation_state,
    clear_conversation_state,
    save_reminder,
    list_due_reminders,
    mark_reminder_sent,
    list_reminders,
    get_reminder,
    delete_reminder,
    update_event_next_year,
    snooze_reminder,
    clear_all_user_data,
    clear_user_reminders,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TIMEZONE = "Europe/Warsaw"
ALLOWED_CHAT_IDS_RAW = os.getenv("ALLOWED_CHAT_IDS", "")


def get_allowed_chat_ids() -> set[int]:
    allowed_ids = set()

    for item in ALLOWED_CHAT_IDS_RAW.split(","):
        item = item.strip()

        if not item:
            continue

        try:
            allowed_ids.add(int(item))
        except ValueError:
            continue

    return allowed_ids


def is_allowed_chat(telegram_chat_id: int) -> bool:
    allowed_ids = get_allowed_chat_ids()

    if not allowed_ids:
        return True

    return telegram_chat_id in allowed_ids


async def deny_if_not_allowed(update: Update) -> bool:
    telegram_chat_id = update.effective_chat.id

    if is_allowed_chat(telegram_chat_id):
        return False

    if update.message:
        await update.message.reply_text(
            "Доступ закритий 🔒\n\n"
            "Цей бот приватний."
        )
    elif update.callback_query:
        await update.callback_query.answer("Доступ закритий", show_alert=True)

    return True


def normalize_event_datetime_parts(
    event_date: str | None,
    event_time: str | None,
) -> tuple[str | None, str | None]:
    if not event_time:
        return event_date, event_time

    try:
        hour_text, minute_text = event_time.split(":")
        hours = int(hour_text)
        minutes = int(minute_text)
    except Exception:
        return event_date, event_time

    if not event_date:
        event_date = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()

    try:
        base_date = datetime.strptime(event_date, "%Y-%m-%d").date()
    except Exception:
        return event_date, event_time

    normalized_datetime = datetime.combine(
        base_date,
        time(hour=0, minute=0),
        tzinfo=ZoneInfo(TIMEZONE),
    ) + timedelta(hours=hours, minutes=minutes)

    return (
        normalized_datetime.date().isoformat(),
        normalized_datetime.strftime("%H:%M"),
    )


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

    if reminder_type == "at_event_time":
        return event_datetime

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
        "at_event_time": "у момент події",
        "quick_reminder": "швидке нагадування",
        "no_reminder": "без нагадування",
    }

    return mapping.get(reminder_type, reminder_type)


def format_remind_at(remind_at: datetime | None) -> str:
    if not remind_at:
        return "без нагадування"

    return remind_at.strftime("%Y-%m-%d %H:%M")


def event_type_emoji(event_type: str | None) -> str:
    mapping = {
        "appointment": "📅",
        "birthday": "🎂",
        "task": "✅",
        "reminder": "🔔",
        "other": "📝",
    }

    return mapping.get(event_type or "other", "📝")


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


def build_snooze_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✅ Готово", callback_data=f"done:{reminder_id}"),
        ],
        [
            InlineKeyboardButton("⏰ Через 10 хв", callback_data=f"snooze10:{reminder_id}"),
            InlineKeyboardButton("⏰ Через 1 год", callback_data=f"snooze60:{reminder_id}"),
        ],
        [
            InlineKeyboardButton("📅 Завтра", callback_data=f"snoozeTomorrow:{reminder_id}"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def build_reminder_message(reminder) -> str:
    title = reminder["title"]
    event_type = reminder.get("event_type")
    event_date = reminder.get("event_date")
    event_time = reminder.get("event_time")

    emoji = event_type_emoji(event_type)

    if event_type == "birthday":
        return f"🎂 Нагадування: день народження — {title}"

    if event_time:
        return f"{emoji} Нагадую: {title}\n\nЧас події: {event_time}"

    if event_date:
        return f"{emoji} Нагадую: {title}\n\nДата: {event_date}"

    return f"{emoji} Нагадую: {title}"


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
    date_text = parsed.get("date") or "Не вказано"
    time_text = parsed.get("time") or "Не вказано"

    is_recurring = parsed.get("is_recurring", False)
    recurrence_rule = parsed.get("recurrence_rule")

    response = "Я зрозумів і зберіг подію ✅\n\n"

    if event_id:
        response += f"ID: {event_id}\n"

    response += (
        f"Назва: {title}\n"
        f"Тип: {event_type}\n"
        f"Дата: {date_text}\n"
        f"Час: {time_text}\n"
    )

    if is_recurring:
        response += f"Повторення: {recurrence_rule or 'так'}\n"

    if reminder_created:
        response += (
            "\nНагадування створено ✅\n"
            f"Час нагадування: {format_remind_at(remind_at)}"
        )
    else:
        has_event_time = bool(parsed.get("time"))
        response += build_reminder_question(has_event_time)

    return response


def format_events_list(events: list, title: str = "Твої збережені події") -> str:
    if not events:
        return "Подій немає."

    lines = [f"{title}:\n"]

    current_date = None

    for event in events:
        event_id = event["id"]
        event_title = event["title"]
        event_date = event["event_date"] or "без дати"
        event_time = event["event_time"] or "без часу"
        event_type = event.get("event_type")
        emoji = event_type_emoji(event_type)

        if event["event_date"] != current_date:
            current_date = event["event_date"]
            lines.append(f"\n📌 {event_date}")

        recurring_text = " 🔁" if event["is_recurring"] else ""

        lines.append(
            f"{event_id}. {emoji} {event_title}{recurring_text}\n"
            f"   Час: {event_time}"
        )

    return "\n".join(lines)


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
            f"{reminder['id']}. 🔔 {title}\n"
            f"   Нагадати: {remind_text}\n"
            f"   Статус: {status}"
        )

    return "\n\n".join(lines)


def build_help_text() -> str:
    return (
        "Команди:\n\n"
        "/events — показати всі події\n"
        "/today — події на сьогодні\n"
        "/week — події на 7 днів\n"
        "/reminders — показати нагадування\n"
        "/remind 10 текст — швидке нагадування через 10 хв\n"
        "/delete ID — видалити подію\n"
        "/delete_reminder ID — видалити нагадування\n"
        "/clear — очистити всі події і нагадування\n"
        "/clear_reminders — очистити тільки нагадування\n"
        "/myid — показати твій chat_id\n\n"
        "Приклади:\n"
        "• Завтра о 12:00 купити корм\n"
        "• У пʼятницю о 18:30 стоматолог\n"
        "• 10 березня день народження Івана\n"
        "• /remind 10 вимкнути гречку"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    await update.message.reply_text(
        "Привіт! Я твій reminder-agent 🤖\n\n"
        "Я вмію зберігати події, нагадувати, показувати плани на сьогодні/тиждень "
        "і робити швидкі нагадування.\n\n"
        + build_help_text()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    await update.message.reply_text(build_help_text())


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_chat_id = update.effective_chat.id

    await update.message.reply_text(
        f"Твій Telegram chat_id:\n{telegram_chat_id}"
    )


async def access_debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_chat_id = update.effective_chat.id
    raw_allowed = os.getenv("ALLOWED_CHAT_IDS", "")
    parsed_allowed = get_allowed_chat_ids()

    await update.message.reply_text(
        "Access debug 🔍\n\n"
        f"Твій chat_id: {telegram_chat_id}\n"
        f"ALLOWED_CHAT_IDS raw: {raw_allowed}\n"
        f"Parsed allowed IDs: {parsed_allowed}\n"
        f"Is allowed: {is_allowed_chat(telegram_chat_id)}"
    )


async def events_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

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


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    telegram_chat_id = update.effective_chat.id
    today = datetime.now(ZoneInfo(TIMEZONE)).date()

    try:
        events = list_events_between(telegram_chat_id, today, today)
        answer = format_events_list(events, title="Події на сьогодні")
    except Exception as error:
        logging.exception("Error while listing today events")
        answer = (
            "Не зміг отримати події на сьогодні 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )

    await update.message.reply_text(answer)


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    telegram_chat_id = update.effective_chat.id
    today = datetime.now(ZoneInfo(TIMEZONE)).date()
    end_date = today + timedelta(days=7)

    try:
        events = list_events_between(telegram_chat_id, today, end_date)
        answer = format_events_list(events, title="Події на найближчі 7 днів")
    except Exception as error:
        logging.exception("Error while listing week events")
        answer = (
            "Не зміг отримати події на тиждень 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )

    await update.message.reply_text(answer)


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

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


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    telegram_chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "Напиши ID події.\n\n"
            "Приклад:\n"
            "/delete 8"
        )
        return

    try:
        event_id = int(context.args[0])
        deleted = delete_event(event_id, telegram_chat_id)

        if deleted:
            await update.message.reply_text(f"Подію {event_id} видалено ✅")
        else:
            await update.message.reply_text(f"Не знайшов подію з ID {event_id}.")
    except ValueError:
        await update.message.reply_text("ID має бути числом. Наприклад: /delete 8")
    except Exception as error:
        logging.exception("Error while deleting event")
        await update.message.reply_text(
            "Не зміг видалити подію 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )


async def delete_reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    telegram_chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "Напиши ID нагадування.\n\n"
            "Приклад:\n"
            "/delete_reminder 3"
        )
        return

    try:
        reminder_id = int(context.args[0])
        deleted = delete_reminder(reminder_id, telegram_chat_id)

        if deleted:
            await update.message.reply_text(f"Нагадування {reminder_id} видалено ✅")
        else:
            await update.message.reply_text(f"Не знайшов нагадування з ID {reminder_id}.")
    except ValueError:
        await update.message.reply_text("ID має бути числом. Наприклад: /delete_reminder 3")
    except Exception as error:
        logging.exception("Error while deleting reminder")
        await update.message.reply_text(
            "Не зміг видалити нагадування 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

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
    if await deny_if_not_allowed(update):
        return

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


async def quick_remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    telegram_chat_id = update.effective_chat.id

    if len(context.args) < 2:
        await update.message.reply_text(
            "Формат:\n"
            "/remind 10 текст нагадування\n\n"
            "Приклад:\n"
            "/remind 10 вимкнути гречку"
        )
        return

    try:
        minutes = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "Перший параметр має бути числом хвилин.\n\n"
            "Приклад:\n"
            "/remind 10 вимкнути гречку"
        )
        return

    if minutes <= 0:
        await update.message.reply_text("Кількість хвилин має бути більше 0.")
        return

    title = " ".join(context.args[1:]).strip()

    if not title:
        await update.message.reply_text("Напиши текст нагадування.")
        return

    now = datetime.now(ZoneInfo(TIMEZONE))
    event_datetime = now + timedelta(minutes=minutes)
    event_date = event_datetime.date().isoformat()
    event_time = event_datetime.strftime("%H:%M")

    try:
        event_id = save_event(
            telegram_chat_id=telegram_chat_id,
            title=title,
            event_type="reminder",
            event_date=event_date,
            event_time=event_time,
            is_recurring=False,
            recurrence_rule=None,
            reminder_missing=False,
        )

        event = get_event(event_id, telegram_chat_id)
        remind_at = calculate_remind_at(event, "at_event_time")

        save_reminder(
            event_id=event_id,
            telegram_chat_id=telegram_chat_id,
            remind_at=remind_at,
            reminder_type="quick_reminder",
        )

        await update.message.reply_text(
            "Швидке нагадування створено ✅\n\n"
            f"Подія: {title}\n"
            f"Час нагадування: {format_remind_at(remind_at)}"
        )

    except Exception as error:
        logging.exception("Error while creating quick reminder")
        await update.message.reply_text(
            "Не зміг створити швидке нагадування 😕\n\n"
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
    if await deny_if_not_allowed(update):
        return

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
            event_date = parsed.get("date")
            event_time = parsed.get("time")

            event_date, event_time = normalize_event_datetime_parts(event_date, event_time)

            parsed["date"] = event_date
            parsed["time"] = event_time

            event_id = save_event(
                telegram_chat_id=telegram_chat_id,
                title=parsed.get("title") or "Без назви",
                event_type=parsed.get("event_type"),
                event_date=event_date,
                event_time=event_time,
                is_recurring=parsed.get("is_recurring", False),
                recurrence_rule=parsed.get("recurrence_rule"),
                reminder_missing=parsed.get("reminder_missing", True),
            )

            event = get_event(event_id, telegram_chat_id)

            if event_date and event_time:
                event_datetime = build_event_datetime(event)
                now = datetime.now(ZoneInfo(TIMEZONE))

                if event_datetime and event_datetime <= now + timedelta(hours=1):
                    reminder_type = "at_event_time"
                else:
                    reminder_type = "one_hour_before"

                remind_at = calculate_remind_at(event, reminder_type)

                save_reminder(
                    event_id=event_id,
                    telegram_chat_id=telegram_chat_id,
                    remind_at=remind_at,
                    reminder_type=reminder_type,
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


async def reminder_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    telegram_chat_id = query.message.chat_id

    if not is_allowed_chat(telegram_chat_id):
        await query.edit_message_text("Доступ закритий 🔒")
        return

    data = query.data

    try:
        action, reminder_id_text = data.split(":")
        reminder_id = int(reminder_id_text)
    except Exception:
        await query.edit_message_text("Не зрозумів дію з кнопки.")
        return

    now = datetime.now(ZoneInfo(TIMEZONE))

    if action == "done":
        mark_reminder_sent(reminder_id)
        await query.edit_message_text("Готово ✅")
        return

    if action == "snooze10":
        new_time = now + timedelta(minutes=10)
        snooze_reminder(reminder_id, telegram_chat_id, new_time)
        await query.edit_message_text(
            f"Добре, нагадаю ще раз о {new_time.strftime('%H:%M')} ✅"
        )
        return

    if action == "snooze60":
        new_time = now + timedelta(hours=1)
        snooze_reminder(reminder_id, telegram_chat_id, new_time)
        await query.edit_message_text(
            f"Добре, нагадаю ще раз о {new_time.strftime('%H:%M')} ✅"
        )
        return

    if action == "snoozeTomorrow":
        new_time = datetime.combine(
            now.date() + timedelta(days=1),
            time(hour=9, minute=0),
            tzinfo=ZoneInfo(TIMEZONE),
        )
        snooze_reminder(reminder_id, telegram_chat_id, new_time)
        await query.edit_message_text(
            f"Добре, нагадаю завтра о {new_time.strftime('%H:%M')} ✅"
        )
        return


async def send_due_reminders(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(ZoneInfo(TIMEZONE))
    app = context.application

    try:
        reminders = list_due_reminders(now)

        for reminder in reminders:
            telegram_chat_id = reminder["telegram_chat_id"]
            reminder_id = reminder["reminder_id"]

            message = build_reminder_message(reminder)

            await app.bot.send_message(
                chat_id=telegram_chat_id,
                text=message,
                reply_markup=build_snooze_keyboard(reminder_id),
            )

            mark_reminder_sent(reminder_id)

            if reminder["is_recurring"] and reminder["recurrence_rule"] == "FREQ=YEARLY":
                next_event = update_event_next_year(
                    event_id=reminder["event_id"],
                    telegram_chat_id=telegram_chat_id,
                )

                if next_event:
                    next_remind_at = calculate_remind_at(
                        next_event,
                        reminder["reminder_type"],
                    )

                    save_reminder(
                        event_id=next_event["id"],
                        telegram_chat_id=telegram_chat_id,
                        remind_at=next_remind_at,
                        reminder_type=reminder["reminder_type"],
                    )

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
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("delete_reminder", delete_reminder_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("clear_reminders", clear_reminders_command))
    app.add_handler(CommandHandler("remind", quick_remind_command))
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("access_debug", access_debug_command))
    app.add_handler(CallbackQueryHandler(reminder_button_handler))
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
