from aiogram import Router, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup
from aiogram.fsm.context import FSMContext

router = Router()

main_menu_keyboard = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text="✅ Создать заказ")],
    [KeyboardButton(text="📦 Склад"), 
     KeyboardButton(text="💰 Касса")],
    [KeyboardButton(text="📊 Мои отчёты")]
])

@router.message(F.text.in_({"/start", "🔁 Назад в меню"}))
async def show_main_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🔷 Главное меню:", reply_markup=main_menu_keyboard)

# Заглушки
@router.message(F.text == "📦 Склад")
async def warehouse_placeholder(message: Message):
    await message.answer("📦 Раздел 'Склад' пока в разработке.")

@router.message(F.text == "💰 Касса")
async def finance_placeholder(message: Message):
    await message.answer("💰 Раздел 'Касса' будет доступен позже.")

@router.message(F.text == "📊 Мои отчёты")
async def reports_placeholder(message: Message):
    await message.answer("📊 Отчёты ещё не готовы — скоро появятся!")