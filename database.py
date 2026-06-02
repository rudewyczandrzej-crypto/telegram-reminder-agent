import os
from datetime import datetime

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


def list_events(telegram_chat_id: int, limit: int = 10):
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
