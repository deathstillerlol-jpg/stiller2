# main.py
# Python 3.10+
# pip install aiogram telethon

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict

from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    PhoneNumberInvalidError,
)

# ──────────────────────────────────────────────
# НАСТРОЙКИ — поменяй на свои значения!

BOT_TOKEN = "8757500911:AAEbSh9hlRam0GYC1HdkoXCGTd9Q1vVBeNc"          # от @BotFather
API_ID = 31462757                                                     # my.telegram.org
API_HASH = "79ae4e151e84526e11b107e99ad67177"                        # my.telegram.org
OWNER_ID = 8559221549                                                 # твой Telegram ID (узнай через @userinfobot)

SESSIONS_FILE = Path("sessions.json")
# ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# Загружаем существующие сессии
SESSIONS: Dict[str, str] = {}  # phone → string_session

if SESSIONS_FILE.exists():
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            SESSIONS = json.load(f)
        logging.info(f"Загружено {len(SESSIONS)} сессий")
    except Exception as e:
        logging.error(f"Ошибка чтения sessions.json: {e}")

def save_sessions():
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(SESSIONS, f, ensure_ascii=False, indent=2)
        logging.info("Сессии сохранены")
    except Exception as e:
        logging.error(f"Ошибка сохранения сессий: {e}")

# ─── Состояния FSM ─────────────────────────────────────────────

class AddSession(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_2fa = State()

# ─── Команды ───────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(m: types.Message):
    if m.from_user.id != OWNER_ID:
        await m.answer("У тебя нет доступа к этому боту.")
        return

    await m.answer(
        "Привет! Это твой личный менеджер сессий.\n\n"
        "Команды:\n"
        "/add — добавить новый аккаунт\n"
        "/list — показать все добавленные номера\n"
        "/del <+7912...> — удалить сессию (осторожно!)"
    )

@router.message(Command("add"))
async def cmd_add(m: types.Message, state: FSMContext):
    if m.from_user.id != OWNER_ID:
        return
    await m.answer("Введи номер телефона в международном формате\nПример: +79123456789")
    await state.set_state(AddSession.waiting_phone)

@router.message(AddSession.waiting_phone)
async def process_phone(m: types.Message, state: FSMContext):
    phone = m.text.strip()

    if not phone.startswith("+") or not phone[1:].isdigit():
        await m.answer("Номер должен начинаться с + и содержать только цифры.\nПопробуй ещё раз.")
        return

    await state.update_data(phone=phone)

    client = TelegramClient(
        StringSession(),
        API_ID,
        API_HASH,
        connection_retries=3,
        retry_delay=2,
    )

    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        await state.update_data(
            phone_code_hash=sent.phone_code_hash,
            client=client,  # сохраняем клиента в контексте (временно)
        )
        await m.answer("Код отправлен в Telegram.\n\nВведи код (5 цифр):")
        await state.set_state(AddSession.waiting_code)

    except FloodWaitError as e:
        await m.answer(f"Слишком много попыток. Подожди {e.seconds // 60 + 1} минут.")
        await client.disconnect()
        await state.clear()
    except PhoneNumberInvalidError:
        await m.answer("Номер введён неверно или не зарегистрирован в Telegram.")
        await client.disconnect()
        await state.clear()
    except Exception as e:
        await m.answer(f"Ошибка: {str(e)}")
        await client.disconnect()
        await state.clear()

@router.message(AddSession.waiting_code)
async def process_code(m: types.Message, state: FSMContext):
    code = m.text.strip()
    data = await state.get_data()
    client: TelegramClient = data.get("client")
    phone = data.get("phone")
    phone_code_hash = data.get("phone_code_hash")

    if not client or not phone:
        await m.answer("Сессия устарела. Начни заново /add")
        await state.clear()
        return

    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        session_str = client.session.save()
        SESSIONS[phone] = session_str
        save_sessions()
        await m.answer(f"Аккаунт {phone} успешно добавлен!")
        await client.disconnect()
        await state.clear()

    except SessionPasswordNeededError:
        await state.update_data(client=client)
        await m.answer("Включена двухфакторная аутентификация.\nВведи пароль 2FA:")
        await state.set_state(AddSession.waiting_2fa)

    except Exception as e:
        await m.answer(f"Ошибка при проверке кода: {str(e)}")
        await client.disconnect()
        await state.clear()

@router.message(AddSession.waiting_2fa)
async def process_2fa(m: types.Message, state: FSMContext):
    password = m.text.strip()
    data = await state.get_data()
    client: TelegramClient = data.get("client")
    phone = data.get("phone")

    if not client or not phone:
        await m.answer("Сессия устарела. Начни заново /add")
        await state.clear()
        return

    try:
        await client.sign_in(password=password)
        session_str = client.session.save()
        SESSIONS[phone] = session_str
        save_sessions()
        await m.answer(f"Аккаунт {phone} успешно добавлен (с 2FA)!")
        await client.disconnect()
        await state.clear()

    except Exception as e:
        await m.answer(f"Неверный пароль 2FA или ошибка: {str(e)}")
        await client.disconnect()
        await state.clear()

@router.message(Command("list"))
async def cmd_list(m: types.Message):
    if m.from_user.id != OWNER_ID:
        return

    if not SESSIONS:
        await m.answer("Пока нет ни одной сохранённой сессии.")
        return

    lines = ["Добавленные аккаунты:"]
    for phone in sorted(SESSIONS):
        lines.append(f"• {phone}")
    await m.answer("\n".join(lines))

@router.message(Command("del"))
async def cmd_del(m: types.Message):
    if m.from_user.id != OWNER_ID:
        return

    if len(m.text.split()) < 2:
        await m.answer("Укажи номер для удаления\nПример: /del +79123456789")
        return

    phone = m.text.split(maxsplit=1)[1].strip()

    if phone in SESSIONS:
        del SESSIONS[phone]
        save_sessions()
        await m.answer(f"Сессия {phone} удалена.")
    else:
        await m.answer("Такого номера нет в списке.")

# ─── Запуск ────────────────────────────────────────────────────

async def main():
    await dp.start_polling(bot, allowed_updates=types.default_allowed_updates)

if __name__ == "__main__":
    asyncio.run(main())
