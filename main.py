import asyncio
import logging
from pathlib import Path
import json
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError

import config

# ─── Настройки ────────────────────────────────────────────────
SESSIONS_FILE = Path("my_sessions.json")
SESSIONS: Dict[str, str] = {}  # phone → string_session

if SESSIONS_FILE.exists():
    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        SESSIONS = json.load(f)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

class AddAccount(StatesGroup):
    phone = State()
    code = State()
    password = State()

def save_sessions():
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(SESSIONS, f, ensure_ascii=False, indent=2)

@router.message(Command("start"))
async def start(message: types.Message):
    if message.from_user.id != config.OWNER_ID:
        await message.answer("Доступ только владельцу.")
        return
    await message.answer(
        "Команды:\n"
        "/add    — добавить свой аккаунт\n"
        "/list   — список добавленных аккаунтов\n"
        "/help   — это сообщение"
    )

@router.message(Command("add"))
async def cmd_add(message: types.Message, state: FSMContext):
    if message.from_user.id != config.OWNER_ID:
        return
    await message.answer("Введи номер телефона (+7912...):")
    await state.set_state(AddAccount.phone)

@router.message(AddAccount.phone, F.text)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not phone.startswith("+") or not phone[1:].isdigit():
        await message.answer("Неверный формат номера.")
        return

    await state.update_data(phone=phone)

    client = TelegramClient(
        StringSession(),
        config.API_ID,
        config.API_HASH,
        connection_retries=5,
        retry_delay=2
    )

    await client.connect()

    try:
        sent_code = await client.send_code_request(phone)
        await state.update_data(
            phone_code_hash=sent_code.phone_code_hash,
            client=client  # временно храним клиента в FSM
        )
        await message.answer("Код пришёл в Telegram. Введи его (5 цифр):")
        await state.set_state(AddAccount.code)
    except FloodWaitError as e:
        await message.answer(f"Flood wait {e.seconds} сек. Подожди и попробуй позже.")
        await client.disconnect()
        await state.clear()
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
        await client.disconnect()
        await state.clear()

@router.message(AddAccount.code, F.text)
async def process_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    client: TelegramClient = data["client"]
    phone = data["phone"]
    phone_code_hash = data["phone_code_hash"]
    code = message.text.strip()

    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        session_str = client.session.save()
        SESSIONS[phone] = session_str
        save_sessions()
        await message.answer(f"Аккаунт {phone} успешно добавлен!")
        await client.disconnect()
        await state.clear()
    except SessionPasswordNeededError:
        await state.update_data(client=client)
        await message.answer("Нужен 2FA-пароль. Введи его:")
        await state.set_state(AddAccount.password)
    except Exception as e:
        await message.answer(f"Ошибка при проверке кода: {str(e)}")
        await client.disconnect()
        await state.clear()

@router.message(AddAccount.password, F.text)
async def process_2fa(message: types.Message, state: FSMContext):
    data = await state.get_data()
    client: TelegramClient = data["client"]
    phone = data["phone"]
    password = message.text.strip()

    try:
        await client.sign_in(password=password)
        session_str = client.session.save()
        SESSIONS[phone] = session_str
        save_sessions()
        await message.answer(f"Аккаунт {phone} добавлен (с 2FA)!")
        await client.disconnect()
        await state.clear()
    except Exception as e:
        await message.answer(f"Неверный 2FA или ошибка: {str(e)}")
        await client.disconnect()
        await state.clear()

@router.message(Command("list"))
async def cmd_list(message: types.Message):
    if message.from_user.id != config.OWNER_ID:
        return
    if not SESSIONS:
        await message.answer("Нет добавленных аккаунтов.")
        return

    text = "Твои аккаунты:\n\n"
    for phone in SESSIONS:
        text += f"• {phone}\n"
    await message.answer(text)

async def main():
    await dp.start_polling(bot, allowed_updates=types.default_allowed_updates)

if __name__ == "__main__":
    asyncio.run(main())
