# handlers/orders/order_editor.py
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from utils.order_cache import order_cache, update_delivery_date
from datetime import date, timedelta
from decimal import Decimal
import logging
from keyboards.inline_keyboards import build_cart_keyboard

# Импортируем _send_cart_summary из нового файла order_helpers
from handlers.orders.order_helpers import _send_cart_summary
# Импортируем send_all_products из product_selection
from handlers.orders.product_selection import send_all_products

router = Router()
logger = logging.getLogger(__name__) 

def build_cart_keyboard(cart_len: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✏ Изменить строку", callback_data="edit_line")],
        [InlineKeyboardButton(text="📅 Изменить дату доставки", callback_data="edit_delivery_date")],
        [InlineKeyboardButton(text="✅ Подтвердить заказ", callback_data="confirm_order")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def show_cart_menu(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_order_data = order_cache.get(user_id, {})
    cart = user_order_data.get("cart", []) # <-- ДОБАВЬТЕ ЭТУ СТРОКУ

    await _send_cart_summary(message, user_id)

    if cart:
        cart_len = len(cart)
        reply_markup = build_cart_keyboard(cart_len) # Используем локальную функцию
        await message.answer("🛒 Меню корзины:", reply_markup=reply_markup)
    else:
        # Теперь, когда _send_cart_summary также проверяет пустую корзину и дату,
        # этот блок можно упростить или удалить, если _send_cart_summary уже отправила сообщение.
        # Например, можно просто отправить клавиатуру для добавления товаров, если корзина пуста
        await message.answer("Ваша корзина пуста. Добавьте товары, чтобы продолжить.",
                             reply_markup=ReplyKeyboardRemove()) # Убираем текущую клавиатуру

        # Перенаправляем на выбор товаров, если корзина пуста
        await send_all_products(message, state) # Возвращаем пользователя к выбору товаров
        await state.set_state(OrderFSM.selecting_product)

@router.callback_query(F.data == "edit_line")
async def request_line_to_edit(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cart = order_cache.get(user_id, {}).get("cart", [])

    if not cart:
        await callback.answer("Корзина пуста.", show_alert=True)
        await show_cart_menu(callback.message, state)
        return

    keyboard_buttons = []
    for i, item in enumerate(cart):
        keyboard_buttons.append([InlineKeyboardButton(text=f"{i+1}. {item['product_name']} ({item['quantity']} шт.)", callback_data=f"select_line_{i}")])

    keyboard_buttons.append([InlineKeyboardButton(text="↩ Назад", callback_data="back_to_cart")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await callback.message.edit_text("Выберите строку для редактирования:", reply_markup=keyboard)
    await state.set_state(OrderFSM.editing_order)


@router.callback_query(StateFilter(OrderFSM.editing_order), F.data.startswith("select_line_"))
async def edit_line(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    cart = order_cache.get(user_id, {}).get("cart", [])

    if index >= len(cart) or index < 0:
        await callback.answer("Неверный номер строки.", show_alert=True)
        await show_cart_menu(callback.message, state)
        return

    await state.update_data(editing_item_index=index)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏ Изменить количество", callback_data="edit_qty")],
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data="edit_price")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="remove_line")],
        [InlineKeyboardButton(text="↩ Назад", callback_data="back_to_cart")]
    ])
    item = order_cache[callback.from_user.id]["cart"][index]
    await callback.message.edit_text(
        f"🎯 <b>{item['product_name']}</b>\nКоличество: {item['quantity']}\nЦена: {item['price']}₴",
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
    keyboard_buttons = []
    for i in range(days):
        day = today + timedelta(days=i)
        keyboard_buttons.append([InlineKeyboardButton(text=day.strftime("%d.%m.%Y"), callback_data=f"set_date_{day.isoformat()}")])
    keyboard_buttons.append([InlineKeyboardButton(text="↩ Назад", callback_data="back_to_cart")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

@router.callback_query(StateFilter(OrderFSM.change_delivery_date), F.data.startswith("set_date_"))
async def set_delivery_date(callback: CallbackQuery, state: FSMContext):
    selected_date_str = callback.data.split("_")[2]
    selected_date = date.fromisoformat(selected_date_str)
    user_id = callback.from_user.id
    print(f"[DEBUG] set_delivery_date called for user_id: {user_id}. Current delivery_date: {order_cache.get(user_id, {}).get('delivery_date')}")
    update_delivery_date(user_id, selected_date)
    await callback.answer(f"📅 Дата доставки установлена на {selected_date.strftime('%d.%m.%Y')}", show_alert=True)
    await show_cart_menu(callback.message, state)
    await state.set_state(OrderFSM.editing_order)
    print(f"[DEBUG] set_delivery_date completed for user_id: {user_id}. After setting: {order_cache.get(user_id, {}).get('delivery_date')}")

@router.callback_query(StateFilter(OrderFSM.editing_order), F.data == "edit_qty")
async def request_new_quantity(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🔢 Введите новое количество:")
    await state.set_state(OrderFSM.editing_product_line)

@router.message(StateFilter(OrderFSM.editing_product_line))
async def process_new_quantity(message: Message, state: FSMContext):
    user_id = message.from_user.id
    state_data = await state.get_data()
    index = state_data.get("editing_item_index")

    if index is None:
        await message.answer("⚠️ Ошибка: не удалось определить редактируемую позицию.")
        await show_cart_menu(message, state)
        return

    try:
        new_qty = int(message.text.strip())
        if new_qty <= 0:
            raise ValueError("Количество должно быть положительным числом.")
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное целое число для количества.")
        return

    cart = order_cache[user_id]["cart"]
    if 0 <= index < len(cart):
        cart[index]["quantity"] = new_qty
        await message.answer(f"✅ Количество обновлено на {new_qty} шт.", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("⚠️ Ошибка при обновлении количества.", reply_markup=ReplyKeyboardRemove())

    await show_cart_menu(message, state)
    await state.set_state(OrderFSM.editing_order)

@router.callback_query(StateFilter(OrderFSM.editing_order), F.data == "edit_price")
async def request_new_price(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("💰 Введите новую цену:")
    await state.set_state(OrderFSM.editing_product_line)

@router.message(StateFilter(OrderFSM.editing_product_line))
async def process_new_price(message: Message, state: FSMContext):
    user_id = message.from_user.id
    state_data = await state.get_data()
    index = state_data.get("editing_item_index")

    if index is None:
        await message.answer("⚠️ Ошибка: не удалось определить редактируемую позицию.")
        await show_cart_menu(message, state)
        return

    try:
        new_price = Decimal(message.text.strip().replace(',', '.'))
        if new_price < 0:
            raise ValueError("Цена не может быть отрицательной.")
    except Exception:
        await message.answer("❌ Пожалуйста, введите корректное число для цены (например, 100.50).")
        return

    cart = order_cache[user_id]["cart"]
    if 0 <= index < len(cart):
        cart[index]["price"] = new_price
        await message.answer(f"✅ Цена обновлена на {new_price:.2f}₴", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("⚠️ Ошибка при обновлении цены.", reply_markup=ReplyKeyboardRemove())

    await show_cart_menu(message, state)
    await state.set_state(OrderFSM.editing_order)


@router.callback_query(StateFilter(OrderFSM.editing_order), F.data == "remove_line")
async def remove_product_line(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    state_data = await state.get_data()
    index = state_data.get("editing_item_index")

    if index is None:
        await callback.answer("⚠️ Ошибка: не удалось определить позицию для удаления.", show_alert=True)
        await show_cart_menu(callback.message, state)
        return

    # НАЧАЛО ИСПРАВЛЕНИЯ
    # Безопасно получаем данные заказа пользователя и содержимое корзины
    user_order_data = order_cache.get(user_id, {})
    cart = user_order_data.get("cart", []) # Теперь 'cart' всегда будет списком (или пустым списком)
    # КОНЕЦ ИСПРАВЛЕНИЯ

    if 0 <= index < len(cart):
        removed_item = cart.pop(index)
        # Поскольку 'cart' теперь является ссылкой на список внутри 'user_order_data' (который, в свою очередь, является ссылкой на dict в order_cache),
        # операция `.pop()` изменяет список непосредственно в кеше.
        # Поэтому явное присвоение `order_cache[user_id]["cart"] = cart` не требуется.

        # Эти логи можно раскомментировать для отладки
        logger.debug(f"[DEBUG] remove_product_line called for user_id: {user_id}. Current cart: {order_cache.get(user_id, {}).get('cart')}")

        await callback.answer(f"🗑 Строка с товаром '{removed_item['product_name']}' удалена.", show_alert=True)

        logger.debug(f"[DEBUG] remove_product_line completed for user_id: {user_id}. After removal: {order_cache.get(user_id, {}).get('cart')}")
    else:
        await callback.answer("⚠️ Ошибка при удалении строки.", show_alert=True)

    await show_cart_menu(callback.message, state)
    await state.set_state(OrderFSM.editing_order)
    current_cart_for_debug = order_cache.get(user_id, {}).get('cart', [])
    print(f"[DEBUG] remove_product_line completed for user_id: {user_id}. After removal: {current_cart_for_debug}")

@router.callback_query(F.data == "confirm_order")
async def confirm_order(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    order_data = order_cache.get(user_id)
    if not order_data or not order_data.get("cart"):
        await callback.answer("Ваш заказ пуст. Нечего подтверждать.", show_alert=True)
        await show_cart_menu(callback.message, state)
        return

    await callback.answer("✅ Заказ подтвержден! (Логика сохранения будет добавлена позже)", show_alert=True)
    await callback.message.edit_text("Заказ успешно подтвержден! Спасибо!")
    await state.clear()