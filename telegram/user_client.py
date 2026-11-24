import getpass
import logging
from pathlib import Path

from telethon import TelegramClient, errors, utils
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


def _print_code_destination(sent, phone: str) -> None:
    kind = type(getattr(sent, "type", None)).__name__
    message = _CODE_WHERE.get(kind, "Telegram sent a login code.")
    print("")
    print(f"[TELEGRAM] Login code requested for +{phone}.")
    for line in message.splitlines():
        print(f"[TELEGRAM] {line}")
    if kind == "SentCodeTypeApp":
        print("[TELEGRAM] This number already has a Telegram account.")
        print("[TELEGRAM] The code goes only to devices logged into this same number.")
        print("[TELEGRAM] A different phone will not show it, and no SMS is sent.")
    elif kind != "SentCodeTypeSetUpEmailRequired":
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

    _print_code_destination(sent, phone)
    if type(sent.type).__name__ == "SentCodeTypeSetUpEmailRequired":
        raise RuntimeError("Add an email to this Telegram account in the official app, then try again.")

    attempts = 0
    while attempts < 3:
        code = input("Login code (or resend): ").strip()
        if code.lower() == "resend":
            try:
                sent = await current.send_code_request(phone)
            except errors.FloodWaitError as exc:
                print(f"Telegram asked to wait {exc.seconds} seconds before another code.")
                continue
            except errors.PhoneCodeExpiredError:
                current._phone_code_hash.pop(phone, None)
                sent = await current.send_code_request(phone)
            _print_code_destination(sent, phone)
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


def _session_files() -> list[Path]:
    current = get_client()
    filename = None if current.session is None else current.session.filename
    if not filename or filename == ":memory:":
        return []
    path = Path(filename)
    return [path, Path(str(path) + "-journal"), Path(str(path) + ".api_id")]


async def _discard_session() -> None:
    """Drop the local login without calling Telegram log-out."""
    global client
    current = client
    paths = _session_files()
    if current.is_connected():
        await current.disconnect()
    if current.session is not None:
        current.session.close()
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except PermissionError as exc:
            raise RuntimeError(
                "Could not replace the session file. Close sessions/personal_user.session and run again."
            ) from exc
    client = _build_client()


def _remember_api_id() -> None:
    filename = None if get_client().session is None else get_client().session.filename
    if not filename or filename == ":memory:":
        return
    Path(str(filename) + ".api_id").write_text(str(API_ID), encoding="utf-8")


def _saved_api_id() -> str | None:
    filename = None if client.session is None else client.session.filename
    if not filename or filename == ":memory:":
        return None
    marker = Path(str(filename) + ".api_id")
    if not marker.exists():
        return None
    return marker.read_text(encoding="utf-8").strip()


async def _prepare_session():
    """Reuse a personal login. Otherwise delete the session and start a new key."""
    saved_api_id = _saved_api_id()
    if saved_api_id is not None and saved_api_id != str(API_ID):
        print(
            "\n[TELEGRAM] The saved session was created with a different API ID.\n"
            "[TELEGRAM] That session cannot be reused. A new one will be created.\n"
        )
        await _discard_session()

    current = get_client()
    try:
        await current.connect()
        me = await current.get_me()
    except errors.AuthKeyUnregisteredError:
        print(
            "\n[TELEGRAM] Telegram rejected the saved session key.\n"
            "[TELEGRAM] Removing it and creating a new session.\n"
        )
        await _discard_session()
        await get_client().connect()
        return None

    if me is not None and not getattr(me, "bot", False):
        _remember_api_id()
        return me

    if me is not None and me.bot:
        print(
            "\n[TELEGRAM] This saved login is the bot account.\n"
            "[TELEGRAM] A bot cannot publish on your channels, so that session was removed.\n"
            "[TELEGRAM] The bot token is not used for this login.\n"
        )
    else:
        print(
            "\n[TELEGRAM] The saved session is not a signed-in personal account.\n"
            "[TELEGRAM] Phone number, bot token, and admin user id do not change that file.\n"
            "[TELEGRAM] Removing it so this login starts with a new session.\n"
        )
    await _discard_session()
    await get_client().connect()
    return None


async def connect_user_account():
    global account_name, account_id

    me = await _prepare_session()

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
