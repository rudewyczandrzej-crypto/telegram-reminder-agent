import os
from datetime import datetime, date, timedelta

import psycopg
from psycopg.rows import dict_row


def get_connection():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL не знайдено у Railway Variables")

    return psycopg.connect(database_url, row_factory=dict_row)


def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    telegram_chat_id BIGINT NOT NULL,
                    title TEXT NOT NULL,
                    event_type TEXT,
                    event_date DATE,
                    event_time TIME,
                    is_recurring BOOLEAN DEFAULT FALSE,
                    recurrence_rule TEXT,
                    reminder_missing BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id SERIAL PRIMARY KEY,
                    event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
                    telegram_chat_id BIGINT NOT NULL,
                    remind_at TIMESTAMP,
                    reminder_type TEXT,
                    sent BOOLEAN DEFAULT FALSE,
                    sent_at TIMESTAMP
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_state (
                    telegram_chat_id BIGINT PRIMARY KEY,
                    pending_action TEXT,
                    pending_event_id INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            conn.commit()


def save_event(
    telegram_chat_id: int,
    title: str,
    event_type: str | None,
    event_date: str | None,
    event_time: str | None,
    is_recurring: bool,
    recurrence_rule: str | None,
    reminder_missing: bool,
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO events (
                    telegram_chat_id,
                    title,
                    event_type,
                    event_date,
                    event_time,
                    is_recurring,
                    recurrence_rule,
                    reminder_missing
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    telegram_chat_id,
                    title,
                    event_type,
                    event_date,
                    event_time,
                    is_recurring,
                    recurrence_rule,
                    reminder_missing,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row["id"]


def get_event(event_id: int, telegram_chat_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    telegram_chat_id,
                    title,
                    event_type,
                    event_date,
                    event_time,
                    is_recurring,
                    recurrence_rule
                FROM events
                WHERE id = %s AND telegram_chat_id = %s;
                """,
                (event_id, telegram_chat_id),
            )
            return cur.fetchone()


def list_events(telegram_chat_id: int, limit: int = 20):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    title,
                    event_type,
                    event_date,
                    event_time,
                    is_recurring,
                    recurrence_rule
                FROM events
                WHERE telegram_chat_id = %s
                ORDER BY event_date NULLS LAST, event_time NULLS LAST, id DESC
                LIMIT %s;
                """,
                (telegram_chat_id, limit),
            )
            return cur.fetchall()


def list_events_between(telegram_chat_id: int, start_date: date, end_date: date):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    title,
                    event_type,
                    event_date,
                    event_time,
                    is_recurring,
                    recurrence_rule
                FROM events
                WHERE telegram_chat_id = %s
                  AND event_date >= %s
                  AND event_date <= %s
                ORDER BY event_date ASC, event_time NULLS LAST, id ASC;
                """,
                (telegram_chat_id, start_date, end_date),
            )
            return cur.fetchall()


def delete_event(event_id: int, telegram_chat_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM events
                WHERE id = %s AND telegram_chat_id = %s
                RETURNING id;
                """,
                (event_id, telegram_chat_id),
            )
            row = cur.fetchone()
            conn.commit()
            return row is not None


def set_conversation_state(
    telegram_chat_id: int,
    pending_action: str,
    pending_event_id: int | None,
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_state (
                    telegram_chat_id,
                    pending_action,
                    pending_event_id,
                    updated_at
                )
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (telegram_chat_id)
                DO UPDATE SET
                    pending_action = EXCLUDED.pending_action,
                    pending_event_id = EXCLUDED.pending_event_id,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (telegram_chat_id, pending_action, pending_event_id),
            )
            conn.commit()


def get_conversation_state(telegram_chat_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT telegram_chat_id, pending_action, pending_event_id
                FROM conversation_state
                WHERE telegram_chat_id = %s;
                """,
                (telegram_chat_id,),
            )
            return cur.fetchone()


def clear_conversation_state(telegram_chat_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM conversation_state
                WHERE telegram_chat_id = %s;
                """,
                (telegram_chat_id,),
            )
            conn.commit()


def save_reminder(
    event_id: int,
    telegram_chat_id: int,
    remind_at: datetime | None,
    reminder_type: str,
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reminders (
                    event_id,
                    telegram_chat_id,
                    remind_at,
                    reminder_type,
                    sent
                )
                VALUES (%s, %s, %s, %s, FALSE)
                RETURNING id;
                """,
                (event_id, telegram_chat_id, remind_at, reminder_type),
            )
            row = cur.fetchone()
            conn.commit()
            return row["id"]


def list_due_reminders(now: datetime):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    reminders.id AS reminder_id,
                    reminders.telegram_chat_id,
                    reminders.remind_at,
                    reminders.reminder_type,
                    events.id AS event_id,
                    events.title,
                    events.event_type,
                    events.event_date,
                    events.event_time,
                    events.is_recurring,
                    events.recurrence_rule
                FROM reminders
                JOIN events ON events.id = reminders.event_id
                WHERE reminders.sent = FALSE
                  AND reminders.remind_at IS NOT NULL
                  AND reminders.remind_at <= %s
                ORDER BY reminders.remind_at ASC
                LIMIT 20;
                """,
                (now,),
            )
            return cur.fetchall()


def mark_reminder_sent(reminder_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE reminders
                SET sent = TRUE, sent_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (reminder_id,),
            )
            conn.commit()


def list_reminders(telegram_chat_id: int, limit: int = 20):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    reminders.id,
                    reminders.remind_at,
                    reminders.reminder_type,
                    reminders.sent,
                    events.title,
                    events.event_date,
                    events.event_time
                FROM reminders
                JOIN events ON events.id = reminders.event_id
                WHERE reminders.telegram_chat_id = %s
                ORDER BY reminders.sent ASC, reminders.remind_at NULLS LAST
                LIMIT %s;
                """,
                (telegram_chat_id, limit),
            )
            return cur.fetchall()


def get_reminder(reminder_id: int, telegram_chat_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    reminders.id,
                    reminders.event_id,
                    reminders.telegram_chat_id,
                    reminders.remind_at,
                    reminders.reminder_type,
                    reminders.sent,
                    events.title,
                    events.event_date,
                    events.event_time,
                    events.is_recurring,
                    events.recurrence_rule
                FROM reminders
                JOIN events ON events.id = reminders.event_id
                WHERE reminders.id = %s
                  AND reminders.telegram_chat_id = %s;
                """,
                (reminder_id, telegram_chat_id),
            )
            return cur.fetchone()


def delete_reminder(reminder_id: int, telegram_chat_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM reminders
                WHERE id = %s AND telegram_chat_id = %s
                RETURNING id;
                """,
                (reminder_id, telegram_chat_id),
            )
            row = cur.fetchone()
            conn.commit()
            return row is not None


def update_event_next_year(event_id: int, telegram_chat_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE events
                SET event_date = event_date + INTERVAL '1 year'
                WHERE id = %s
                  AND telegram_chat_id = %s
                  AND event_date IS NOT NULL
                RETURNING
                    id,
                    telegram_chat_id,
                    title,
                    event_type,
                    event_date,
                    event_time,
                    is_recurring,
                    recurrence_rule;
                """,
                (event_id, telegram_chat_id),
            )
            row = cur.fetchone()
            conn.commit()
            return row


def snooze_reminder(reminder_id: int, telegram_chat_id: int, new_remind_at: datetime):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE reminders
                SET remind_at = %s,
                    sent = FALSE,
                    sent_at = NULL
                WHERE id = %s
                  AND telegram_chat_id = %s;
                """,
                (new_remind_at, reminder_id, telegram_chat_id),
            )
            conn.commit()


def clear_all_user_data(telegram_chat_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM reminders
                WHERE telegram_chat_id = %s;
                """,
                (telegram_chat_id,),
            )

            cur.execute(
                """
                DELETE FROM events
                WHERE telegram_chat_id = %s;
                """,
                (telegram_chat_id,),
            )

            cur.execute(
                """
                DELETE FROM conversation_state
                WHERE telegram_chat_id = %s;
                """,
                (telegram_chat_id,),
            )

            conn.commit()


def clear_user_reminders(telegram_chat_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM reminders
                WHERE telegram_chat_id = %s;
                """,
                (telegram_chat_id,),
            )

            conn.commit()
