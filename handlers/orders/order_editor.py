from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from utils.order_cache import order_cache, add_to_cart, update_delivery_date
from datetime import date, timedelta

router = Router()

def build_cart_text(cart: list) -> str:
    if not cart:
        return "🛒 Корзина пуста."

    text = "<b>🧾 Текущий заказ:</b>\n"
    for i, item in enumerate(cart, start=1):
        text += f"{i}. {item['product_name']} × {item['quantity']} шт. — {item['unit_price']}₴\n"
    total = sum(item["quantity"] * item["unit_price"] for item in cart)
    text += f"\n<b>Итого:</b> {total:.2f}₴"
    return text

def build_cart_keyboard(cart_len: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✏ Изменить строку", callback_data="edit_line")],
        [InlineKeyboardButton(text="📅 Изменить дату доставки", callback_data="edit_delivery_date")],
        [InlineKeyboardButton(text="✅ Подтвердить заказ", callback_data="confirm_order")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def show_cart_menu(message: Message, state: FSMContext):
    user_id = message.from_user.id
    cart = order_cache[user_id].get("cart", [])
    text = build_cart_text(cart)
    kb = build_cart_keyboard(len(cart))
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "edit_line")
async def edit_line_menu(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cart = order_cache[user_id].get("cart", [])

    if not cart:
        await callback.answer("Корзина пуста.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{i+1}. {item['product_name']} × {item['quantity']}",
                callback_data=f"line_{i}"
            )] for i, item in enumerate(cart)
        ]
    )
    await callback.message.edit_text("🔧 Выберите строку для редактирования:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("line_"))
async def edit_line_actions(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[1])
    await state.update_data(line_index=index)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏ Изменить количество", callback_data="edit_qty")],
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data="edit_price")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="remove_line")],
        [InlineKeyboardButton(text="↩ Назад", callback_data="back_to_cart")]
    ])
    item = order_cache[callback.from_user.id]["cart"][index]
    await callback.message.edit_text(
        f"🎯 <b>{item['product_name']}</b>\nКоличество: {item['quantity']}\nЦена: {item['unit_price']}₴",
        reply_markup=keyboard, parse_mode="HTML"
    )

@router.callback_query(F.data == "edit_delivery_date")
async def edit_delivery_date(callback: CallbackQuery, state: FSMContext):
    kb = build_calendar_keyboard()
    await callback.message.edit_text("📅 Выберите новую дату доставки:", reply_markup=kb)
    await state.set_state(OrderFSM.change_delivery_date)

@router.callback_query(F.data == "back_to_cart")
async def return_to_cart(callback: CallbackQuery, state: FSMContext):
    await show_cart_menu(callback.message, state)


def build_calendar_keyboard(days: int = 7) -> InlineKeyboardMarkup:
    today = date.today()
    buttons = []

    for i in range(days):
        d = today + timedelta(days=i)
        label = d.strftime("%d.%m (%a)")
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"date_{d.isoformat()}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

