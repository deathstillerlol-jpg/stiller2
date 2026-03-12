# main.py
# Для Bothost.ru — polling по умолчанию (работает без публичного домена)

import asyncio
import json
import logging
import os
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
# НАСТРОЙКИ — добавь в Environment Variables на Bothost!

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Если позже найдёшь домен — раскомментируй BOT_HOST и webhook-часть ниже
# BOT_HOST = os.getenv("BOT_HOST")  # например bot-abcdef.bothost.ru

# Сессии храним в ENV (SESSION_+79123456789 = string_session)
# ──────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

SESSIONS: Dict[str, str] = {}

def load_sessions():
    global SESSIONS
    for key, value in os.environ.items():
        if key.startswith("SESSION_"):
            phone = key.replace("SESSION_", "")
            SESSIONS[phone] = value
    logging.info(f"Загружено {len(SESSIONS)} сессий из ENV")

load_sessions()

class AddSession(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_2fa = State()

@router.message(Command("start"))
async def cmd_start(m: types.Message):
    if m.from_user.id != OWNER_ID:
        await m.answer("Доступ запрещён.")
        return
    await m.answer(
        "Бот для управления своими сессиями.\n\n"
        "Команды:\n"
        "/add — добавить аккаунт\n"
        "/list — список номеров\n"
        "/help — это сообщение"
    )

@router.message(Command("add"))
async def cmd_add(m: types.Message, state: FSMContext):
    if m.from_user.id != OWNER_ID: return
    await m.answer("Введи номер в формате +79123456789")
    await state.set_state(AddSession.waiting_phone)

@router.message(AddSession.waiting_phone)
async def process_phone(m: types.Message, state: FSMContext):
    phone = m.text.strip()
    if not phone.startswith("+") or not phone[1:].isdigit():
        await m.answer("Неверный формат номера.")
        return

    await state.update_data(phone=phone)

    client = TelegramClient(StringSession(), API_ID, API_HASH)

    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        await state.update_data(phone_code_hash=sent.phone_code_hash, client=client)
        await m.answer("Код пришёл в Telegram. Введи его:")
        await state.set_state(AddSession.waiting_code)
    except Exception as e:
        await m.answer(f"Ошибка: {str(e)}")
        await client.disconnect()
        await state.clear()

@router.message(AddSession.waiting_code)
async def process_code(m: types.Message, state: FSMContext):
    data = await state.get_data()
    client: TelegramClient = data.get("client")
    phone = data.get("phone")
    code = m.text.strip()

    try:
        await client.sign_in(phone, code, phone_code_hash=data["phone_code_hash"])
        session_str = client.session.save()
        os.environ[f"SESSION_{phone}"] = session_str
        SESSIONS[phone] = session_str
        await m.answer(f"Аккаунт {phone} добавлен!")
        await client.disconnect()
        await state.clear()
    except SessionPasswordNeededError:
        await state.update_data(client=client)
        await m.answer("Введи 2FA-пароль:")
        await state.set_state(AddSession.waiting_2fa)
    except Exception as e:
        await m.answer(f"Ошибка кода: {str(e)}")
        await client.disconnect()
        await state.clear()

@router.message(AddSession.waiting_2fa)
async def process_2fa(m: types.Message, state: FSMContext):
    data = await state.get_data()
    client: TelegramClient = data.get("client")
    password = m.text.strip()

    try:
        await client.sign_in(password=password)
        session_str = client.session.save()
        phone = data["phone"]
        os.environ[f"SESSION_{phone}"] = session_str
        SESSIONS[phone] = session_str
        await m.answer(f"{phone} добавлен (с 2FA)!")
        await client.disconnect()
        await state.clear()
    except Exception as e:
        await m.answer(f"Ошибка 2FA: {str(e)}")
        await client.disconnect()
        await state.clear()

@router.message(Command("list"))
async def cmd_list(m: types.Message):
    if m.from_user.id != OWNER_ID: return
    if not SESSIONS:
        await m.answer("Нет сессий.")
        return
    text = "Твои аккаунты:\n" + "\n".join(f"• {p}" for p in sorted(SESSIONS))
    await m.answer(text)

# ─── POLLING (работает без домена) ────────────────────────────────────────

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Polling запущен")
    await dp.start_polling(bot, allowed_updates=types.default_allowed_updates)

# ─── WEBHOOK (раскомментируй когда найдёшь BOT_HOST) ─────────────────────
# async def on_startup():
#     webhook_url = f"https://{BOT_HOST}/webhook"
#     await bot.set_webhook(webhook_url)
#     logging.info(f"Webhook set: {webhook_url}")
#
# async def on_shutdown():
#     await bot.delete_webhook()
#
# if __name__ == "__main__":
#     from aiohttp import web
#     from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
#
#     app = web.Application()
#     handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
#     handler.register(app, path="/webhook")
#     setup_application(app, dp, bot=bot)
#
#     asyncio.run(on_startup())
#     web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

if __name__ == "__main__":
    asyncio.run(main())
