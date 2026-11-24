import asyncio
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

api_id = 37812365
api_hash = 'afbd624b1be01581b72b5df131022945'
phone = '+14244122375'

async def main():
    client = TelegramClient(
        'my_session', 
        api_id, 
        api_hash, 
        device_model="Desktop",
        system_version="Windows 11",
        app_version="4.16.8",
        lang_code="en",
        system_lang_code="en-US"
        )
    await client.connect()

    if not await client.is_user_authorized():
        # Request and submit the login code (handle 2FA if enabled)
        sent = await client.send_code_request(phone)
        code = input('Enter the code: ')
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
        except SessionPasswordNeededError:
            await client.sign_in(password=input('Enter your 2FA password: '))

    await client.disconnect()

asyncio.run(main())
