# Telegram AI Reminder Agent

Personal Telegram-based AI agent for creating events, reminders, birthdays, and recurring notifications.

## What problem it solves

People often forget appointments, errands, birthdays, and personal tasks.  
This agent allows the user to write reminders in natural language, save them in a database, and receive Telegram notifications at the right time.

## Main features

- Natural language event creation
- Automatic date and time parsing
- One-time reminders
- Birthday / yearly recurring reminders
- PostgreSQL database
- Telegram notifications
- Inline buttons and reply keyboard
- Separate data per Telegram user
- Private access with `ALLOWED_CHAT_IDS`
- Commands for viewing, deleting, and clearing events
- Deployed as a 24/7 Telegram worker

## Example use case

User writes:

```text
I have a haircut next Tuesday at 18:00
```

The agent saves the event and creates a reminder.

Another example:

```text
Ivan has birthday on March 10
```

The agent saves it as a yearly reminder.

## Commands

```text
/start — start the bot
/today — events for today
/week — events for the next 7 days
/events — all events
/reminders — all reminders
/remind — quick reminder
/delete — delete event
/delete_reminder — delete reminder
/clear — clear all data
/myid — show Telegram chat ID
```

## Tech stack

- Python
- python-telegram-bot
- Groq / AI API
- PostgreSQL
- Railway-compatible deployment

## Environment variables

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GROQ_API_KEY=your_groq_api_key
DATABASE_URL=your_postgres_database_url
ALLOWED_CHAT_IDS=
```

`ALLOWED_CHAT_IDS` is optional. If empty, the bot is open to everyone. For private use, add Telegram chat IDs separated by commas.

## How to run locally

```bash
pip install -r requirements.txt
python main.py
```

## How to deploy

The project can be deployed as a worker process.  
Example `Procfile`:

```text
worker: python main.py
```

## Portfolio value

This project demonstrates:

- AI parsing of natural language reminders
- event scheduling logic
- recurring reminders
- Telegram bot development
- PostgreSQL persistence
- user-specific data separation
- private bot access control
- Railway deployment
