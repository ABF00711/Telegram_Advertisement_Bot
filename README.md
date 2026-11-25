# Telegram Ad Automation

This is a Python automation script to post advertisement content to channels the user joined in Telegram.

A private management bot stores the ads, picks the channels, and sets the schedule. A signed-in personal account does the posting. The bot cannot post as that account. Only one Telegram user, set as `ADMIN_USER_ID`, can use the bot, and only in a private chat.

The script lists  channels the user already joined.

## Requirements

- Python 3.11 or newer
- A Telegram API ID and API hash from [my.telegram.org](https://my.telegram.org)
- A bot token from [@BotFather](https://t.me/BotFather)
- The numeric Telegram user ID of the person who will control the bot
- A personal account that is already a member of the channels

## Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file in the project folder:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
BOT_TOKEN=123456:your_bot_token
ADMIN_USER_ID=123456789
TIMEZONE=GMT
```

| Variable | Required | Meaning |
| --- | --- | --- |
| `TELEGRAM_API_ID` | yes | API ID from my.telegram.org. It must be the pair that created the session file. |
| `TELEGRAM_API_HASH` | yes | API hash for that same application. |
| `BOT_TOKEN` | yes | Token of the management bot. |
| `ADMIN_USER_ID` | yes | Numeric user ID allowed to talk to the bot. |
| `TIMEZONE` | no | IANA name used for schedule times. Default is `GMT`. Example: `GMT +1`. |
| `SESSION_NAME` | no | Telethon session path. Default is `sessions/personal_user`. |
| `DATABASE_URL` | no | SQLAlchemy URL. Default is SQLite at `data/app.db`. |

To read your user ID, open Telegram, message [@userinfobot](https://t.me/userinfobot), and copy the ID it returns. That value is `ADMIN_USER_ID`.

## Sign in

Run the app once:

```powershell
python main.py
```

If `sessions/personal_user.session` is missing or not signed in, the terminal asks for the personal phone number. Enter it with the country code, for example `+15551234567`. Telegram usually delivers the login code inside the Telegram app, in the private chat named Telegram, rather than by SMS. If the account has a cloud password, the terminal asks for that next.

The session file is tied to `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`. Reusing it with a different API ID invalidates it. A bot token is not a phone number and will not be accepted.

You can also copy an existing Telethon `.session` file to `sessions/personal_user.session` while this app is stopped. It must have been created with the same API ID and API hash. Close the file in the editor before starting the app, or Windows will lock it.

## Bot commands

Open a private chat with the management bot from the account in `ADMIN_USER_ID`.

| Command | What it does |
| --- | --- |
| `/start`, `/help` | Show the command list. |
| `/newad` | Save one advertisement: text, or one photo, video, GIF, or file with a caption. |
| `/ads` | Review or delete saved advertisements. |
| `/post` | Publish a saved advertisement now. |
| `/schedule` | Publish later, once or every day. |
| `/schedules` | View or cancel the queue. |
| `/channels` | Refresh the channels on the personal account. |
| `/status` | Show the connected account, channel count, and next post. |
| `/cancel` | Leave the current step. |

Schedule times accept `2026-11-25 14:30`, `14:30`, or a relative delay such as `+30m`, `+2h`, or `+1d`. A clock time with no date is today, or tomorrow if that time has already passed.

## How posting works

Leave `python main.py` running. The scheduler checks the queue every 15 seconds and posts with the personal account. Stopping the process stops future posts.

A daily schedule that was missed while the app was closed is sent once, then moves to the next day. It does not send one post for every missed day. Run only one copy of the app, or the same schedule can post twice.

Media sent to the bot must be 20 MB or smaller. A caption sent with media must be 1024 characters or shorter. Longer text is sent as a separate message after the file.

Logs are written to the terminal and to `logs/app.log`.
