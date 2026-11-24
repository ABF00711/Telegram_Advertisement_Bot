import getpass
import logging
from pathlib import Path

from telethon import TelegramClient, errors, utils
from telethon.tl import functions
from telethon.tl.types import Channel

from config import API_HASH, API_ID, SESSION_NAME

logger = logging.getLogger(__name__)

account_name: str | None = None
account_id: int | None = None

_CODE_WHERE = {
    "SentCodeTypeApp": (
        "Telegram sent the code inside the Telegram app, not by SMS.\n"
        "Open Telegram on your phone and read the chat named Telegram."
    ),
    "SentCodeTypeSms": "Telegram sent the code by SMS.",
    "SentCodeTypeCall": "Telegram is calling this number and will read the code.",
    "SentCodeTypeFlashCall": "Telegram is placing a short call. The code is the caller number.",
    "SentCodeTypeMissedCall": "Telegram is placing a missed call. The code is the caller number.",
    "SentCodeTypeEmailCode": "Telegram sent the code to this account's email.",
    "SentCodeTypeFragmentSms": "Telegram sent the code by Fragment SMS.",
    "SentCodeTypeFirebaseSms": "Telegram sent the code by SMS.",
    "SentCodeTypeSmsPhrase": "Telegram sent the code by SMS.",
    "SentCodeTypeSmsWord": "Telegram sent the code by SMS.",
    "SentCodeTypeSetUpEmailRequired": (
        "Telegram will not send a code until this account has an email.\n"
        "Add one in the official Telegram app under Settings, then run this again."
    ),
}


def _build_client() -> TelegramClient:
    return TelegramClient(
        SESSION_NAME,
        API_ID,
        API_HASH,
        receive_updates=False,
    )


client = _build_client()


def get_client() -> TelegramClient:
    return client


def _ask_phone() -> str:
    while True:
        value = input("Personal phone number, with country code: ").strip()
        if not value:
            continue
        if ":" in value:
            print(
                "That is a bot token. Enter the phone number of your personal account, "
                "for example +15551234567."
            )
            continue
        phone = utils.parse_phone(value)
        if not phone:
            print("Enter the full number, including the country code, for example +15551234567.")
            continue
        return phone


def _print_code_destination(sent) -> None:
    kind = type(getattr(sent, "type", None)).__name__
    message = _CODE_WHERE.get(kind, "Telegram sent a login code.")
    print("")
    for line in message.splitlines():
        print(f"[TELEGRAM] {line}")
    if kind == "SentCodeTypeSetUpEmailRequired":
        return
    print("[TELEGRAM] Also check Telegram Desktop and any other device on this account.")
    if getattr(sent, "next_type", None) is not None:
        print("[TELEGRAM] If it still does not arrive, type resend and press Enter.")


async def _sign_in_with_code(phone: str) -> None:
    current = get_client()
    try:
        sent = await current.send_code_request(phone)
    except errors.FloodWaitError as exc:
        raise RuntimeError(
            f"Telegram is limiting login codes. Wait {exc.seconds} seconds, then run this again."
        ) from exc
    except errors.PhoneNumberInvalidError as exc:
        raise RuntimeError(
            "Telegram rejected that phone number. Use the country code, for example +15551234567."
        ) from exc
    except errors.PhoneNumberFloodError as exc:
        raise RuntimeError(
            "Too many login codes were requested for this number. Wait a while, then run this again."
        ) from exc

    _print_code_destination(sent)
    if type(sent.type).__name__ == "SentCodeTypeSetUpEmailRequired":
        raise RuntimeError("Add an email to this Telegram account in the official app, then try again.")

    attempts = 0
    while attempts < 3:
        code = input("Login code (or resend): ").strip()
        if code.lower() == "resend":
            try:
                sent = await current(functions.auth.ResendCodeRequest(phone, sent.phone_code_hash))
            except errors.FloodWaitError as exc:
                print(f"Telegram asked to wait {exc.seconds} seconds before another code.")
                continue
            _print_code_destination(sent)
            continue
        try:
            await current.sign_in(phone, code, phone_code_hash=sent.phone_code_hash)
            return
        except errors.SessionPasswordNeededError:
            password = getpass.getpass("Two-step password: ")
            await current.sign_in(password=password)
            return
        except errors.PhoneCodeInvalidError:
            print("That code was not accepted. Check the Telegram chat and try again.")
        except errors.PhoneCodeExpiredError:
            print("That code expired. Type resend and press Enter.")
        attempts += 1

    raise RuntimeError("Sign-in did not succeed. Run the app again and request a new code.")


async def _discard_session() -> None:
    """Drop the local login without calling Telegram log-out."""
    global client
    current = client
    filename = None
    if current.session is not None:
        filename = current.session.filename
    if current.is_connected():
        await current.disconnect()
    if current.session is not None:
        current.session.close()
    if filename and filename != ":memory:":
        Path(filename).unlink(missing_ok=True)
        Path(filename + "-journal").unlink(missing_ok=True)
    client = _build_client()


async def connect_user_account():
    global account_name, account_id

    await client.connect()
    me = await client.get_me()
    if me is not None and me.bot:
        print(
            "\n[TELEGRAM] This saved login is the bot account.\n"
            "[TELEGRAM] A bot cannot publish on your channels, so that login was removed.\n"
            "[TELEGRAM] Sign in with the phone number of your personal account.\n"
            "[TELEGRAM] Do not paste the bot token here.\n"
        )
        await _discard_session()
        me = None

    if me is None:
        print(
            "\n[TELEGRAM] Type the phone number in this terminal, with the country code.\n"
            "[TELEGRAM] Example: +15551234567\n"
            "[TELEGRAM] The code usually arrives in the Telegram app, in the chat named Telegram.\n"
            "[TELEGRAM] It often does not arrive as an SMS.\n"
        )
        await _sign_in_with_code(_ask_phone())
        me = await get_client().get_me()

    if me is None or me.bot:
        await _discard_session()
        raise RuntimeError(
            "The sign-in was not a personal account. "
            "Run the app again and enter your phone number, not the bot token."
        )

    account_name = (
        " ".join(part for part in (me.first_name, me.last_name) if part)
        or me.username
        or "account"
    )
    account_id = me.id
    logger.info("Personal account connected: %s (%s)", account_name, account_id)
    return me


async def get_authorized_channels():
    current = get_client()
    channels = []

    async for dialog in current.iter_dialogs():
        entity = dialog.entity
        if not isinstance(entity, Channel) or not entity.broadcast:
            continue

        admin_rights = entity.admin_rights
        can_post = entity.creator or (
            admin_rights is not None and admin_rights.post_messages
        )
        channels.append(
            {
                "id": entity.id,
                "access_hash": entity.access_hash or 0,
                "title": entity.title,
                "username": entity.username,
                "can_post": bool(can_post),
            }
        )

    return channels
