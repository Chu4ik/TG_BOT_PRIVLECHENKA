# handlers/main_menu.py

import logging
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove # Удаляем KeyboardButton, ReplyKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

router = Router()
logger = logging.getLogger(__name__)

# --- УДАЛЕНА ФУНКЦИЯ get_main_menu_keyboard() ---
# def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
#     """
#     Создает клавиатуру главного меню, включающую все основные разделы бота.
#     """
#     buttons = [
#         [KeyboardButton(text="➕ Создать новый заказ")],
#         [KeyboardButton(text="📄 Мои заказы"), KeyboardButton(text="📝 Показать draft заказы")],
#         [KeyboardButton(text="💰 Оплаты клиентов"), KeyboardButton(text="📊 Отчет об оплатах за сегодня")],
#         [KeyboardButton(text="💸 Оплаты поставщикам за сегодня"), KeyboardButton(text="🚚 Добавить поступление товара")],
#         [KeyboardButton(text="📈 Отчет об остатках товара")]
#     ]
#     return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=False)

@router.message(F.text.in_({"/start", "🔁 Назад в меню"}))
@router.message(Command("start"))
async def show_main_menu(message: Message, state: FSMContext):
    """
    Обрабатывает команды /start и "🔁 Назад в меню",
    очищает состояние и показывает приветственное сообщение,
    а также удаляет любую ReplyKeyboardMarkup.
    """
    await state.clear()
    
    # Отправляем сообщение, которое удаляет любую предыдущую ReplyKeyboardMarkup
    # и просто приветствует пользователя, предлагая использовать /menu
    await message.answer(
        "🔷 Добро пожаловать! Используйте меню команд (синяя кнопка 'Меню' слева внизу) для навигации.",
        reply_markup=ReplyKeyboardRemove() # Это удалит "висящую" клавиатуру
    )
    logger.info(f"Пользователь {message.from_user.id} получил приветственное сообщение без ReplyKeyboardMarkup.")