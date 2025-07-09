# handlers/reports/add_delivery_handler.py

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter

# Импортируем FSM состояния из states.order
from states.order import OrderFSM

# Импортируем функции для работы с поставщиками
from db_operations.supplier_operations import (
    get_all_suppliers,
    record_incoming_delivery,
    SupplierItem,
)
# ИМПОРТ: ProductItem теперь импортируется из product_operations
from db_operations.product_operations import get_all_products_for_selection, ProductItem


router = Router()
logger = logging.getLogger(__name__)

def escape_markdown_v2(text: str) -> str:
    """
    Экранирует все специальные символы для MarkdownV2.
    Эта функция гарантирует, что каждый специальный символ будет правильно экранирован
    путем построения новой строки, обрабатывая каждый символ по очереди.
    """
    if text is None:
        logger.error("escape_markdown_v2 received NoneType text. Returning empty string.")
        return ""

    # Важно: сначала экранируем обратный слэш, чтобы избежать двойного экранирования
    # уже добавленных обратных слэшей.
    text = text.replace('\\', '\\\\')

    # Остальные специальные символы MarkdownV2
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']

    escaped_text_parts = []
    for char in text:
        if char in special_chars:
            escaped_text_parts.append('\\' + char)
        else:
            escaped_text_parts.append(char)
    return "".join(escaped_text_parts)

# --- Вспомогательные функции для клавиатур ---

def build_date_selection_keyboard(current_date: date) -> InlineKeyboardMarkup:
    """
    Строит инлайн-клавиатуру для выбора даты, показывая +/- 7 дней от текущей.
    """
    buttons = []
    row = []
    for i in range(-7, 8): # От -7 до +7 дней
        day = current_date + timedelta(days=i)
        row.append(InlineKeyboardButton(text=day.strftime('%d.%m'), callback_data=f"select_delivery_date_{day.isoformat()}"))
        if len(row) == 5: # 5 кнопок в ряду
            buttons.append(row)
            row = []
    if row: # Добавляем оставшиеся кнопки
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="cancel_add_delivery")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_suppliers_keyboard(suppliers: List[SupplierItem]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора поставщика."""
    buttons = []
    for supplier in suppliers:
        buttons.append([
            InlineKeyboardButton(
                text=escape_markdown_v2(supplier.name), # Имя поставщика - это обычный текст, который нужно экранировать
                callback_data=f"select_supplier_{supplier.supplier_id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_delivery")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_products_keyboard(products: List[ProductItem]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора продукта."""
    buttons = []
    for product in products:
        buttons.append([
            InlineKeyboardButton(
                text=escape_markdown_v2(product.name), # Имя продукта - это обычный текст, который нужно экранировать
                callback_data=f"select_product_for_delivery_{product.product_id}" # Изменено callback_data
            )
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_delivery")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_add_delivery_item_menu_keyboard(has_items: bool) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру для меню добавления/редактирования позиций поступления.
    """
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить позицию", callback_data="add_delivery_item")],
    ]
    if has_items:
        buttons.append([
            InlineKeyboardButton(text="✏️ Редактировать позицию", callback_data="edit_delivery_item"),
            InlineKeyboardButton(text="🗑️ Удалить позицию", callback_data="delete_delivery_item")
        ])
        buttons.append([
            InlineKeyboardButton(text="✅ Завершить поступление", callback_data="finish_delivery_creation")
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add_delivery")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_edit_delivery_item_keyboard(item_index: int) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру для выбора действия с конкретной позицией поступления.
    """
    buttons = [
        [InlineKeyboardButton(text="✏️ Изменить количество", callback_data=f"edit_delivery_item_qty_{item_index}")],
        # ИСПРАВЛЕНО: УДАЛЕНА ЛИШНЯЯ СКОБКА в callback_data
        [InlineKeyboardButton(text="💲 Изменить цену за ед.", callback_data=f"edit_delivery_item_cost_{item_index}")],
        [InlineKeyboardButton(text="⬅️ Назад к позициям", callback_data="back_to_adding_delivery_items")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_delivery_items_list_keyboard(items: List[Dict[str, Any]], action_prefix: str) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру со списком позиций для редактирования/удаления.
    `action_prefix` может быть "edit_selected_delivery_item_" или "delete_selected_delivery_item_".
    """
    buttons = []
    for i, item in enumerate(items):
        # Весь текст кнопки должен быть экранирован, так как он не является Markdown разметкой
        button_text = escape_markdown_v2(f"{i+1}. {item['product_name']} - {item['quantity']} ед. по {item['unit_cost']:.2f} ₴")
        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"{action_prefix}{i}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад к позициям", callback_data="back_to_adding_delivery_items")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_confirm_delivery_keyboard() -> InlineKeyboardMarkup:
    """Строит клавиатуру для подтверждения данных поступления."""
    buttons = [
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_delivery_data")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_delivery_data")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add_delivery")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- Вспомогательные функции для сводки ---

def get_delivery_summary_text(data: Dict[str, Any]) -> str:
    """
    Формирует сводный текст о текущем поступлении, правильно экранируя для MarkdownV2.
    """
    delivery_date_str = data['delivery_date'].strftime('%Y-%m-%d')
    supplier_name_escaped = escape_markdown_v2(data.get('supplier_name', 'Неизвестно'))
    items = data.get('delivery_items', [])
    
    summary_parts = [
        "🚚 *Сводка по поступлению:*\n",
        f"📅 Дата поступления: `{delivery_date_str}`\n",
        f"👤 Поставщик: *{supplier_name_escaped}*\n",
        "\n*Позиции поступления:*\n"
    ]
    
    total_delivery_amount = Decimal('0.00')
    if not items:
        # Эта строка является обычным текстом, содержащим скобки, поэтому ее нужно экранировать.
        summary_parts.append(escape_markdown_v2("   (Позиции пока не добавлены)"))
    else:
        for i, item in enumerate(items):
            item_total = item['quantity'] * item['unit_cost']
            total_delivery_amount += item_total
            
            # Экранируем только динамическое имя продукта
            product_name_escaped = escape_markdown_v2(item['product_name'])

            # Формируем строку, явно экранируя статические спецсимволы,
            # которые не являются частью Markdown-разметки.
            summary_parts.append(
                f"   *{i+1}\\. {product_name_escaped}*\n" # Экранируем '.' в '1.'
                f"      Кол\\-во: `{item['quantity']}` ед\\. по `{item['unit_cost']:.2f} ₴`\n" # Экранируем '-' в 'Кол-во' и '.' в 'ед.'
                f"      Сумма по позиции: `{item_total:.2f} ₴`\n" # Экранируем '.' в 'ед.'
            )
    
    summary_parts.append(f"\n*Общая сумма поступления: `{total_delivery_amount:.2f} ₴`*")
    
    return "".join(summary_parts)


# --- Хендлеры для процесса добавления поступления ---

@router.message(Command("add_delivery"))
async def cmd_add_delivery(message: Message, state: FSMContext):
    """Начинает процесс добавления нового поступления."""
    await state.clear() # Очищаем предыдущее состояние
    # Инициализируем список для позиций поступления
    await state.update_data(delivery_items=[]) 
    
    current_date = date.today()
    keyboard = build_date_selection_keyboard(current_date)
    await message.answer(escape_markdown_v2("Выберите дату поступления:"), reply_markup=keyboard, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.waiting_for_delivery_date)

@router.callback_query(F.data.startswith("select_delivery_date_"), OrderFSM.waiting_for_delivery_date)
async def process_delivery_date_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    """Обрабатывает выбор даты поступления из календаря."""
    selected_date_str = callback.data.split("_")[3]
    delivery_date = date.fromisoformat(selected_date_str)
    await state.update_data(delivery_date=delivery_date)

    suppliers = await get_all_suppliers(db_pool)
    if not suppliers:
        await callback.message.edit_text(escape_markdown_v2("Нет доступных поставщиков. Пожалуйста, добавьте поставщиков в базу данных."), parse_mode="MarkdownV2")
        await state.clear()
        return

    keyboard = build_suppliers_keyboard(suppliers)
    await callback.message.edit_text(escape_markdown_v2("Выберите поставщика:"), reply_markup=keyboard, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.waiting_for_supplier_selection)
    await callback.answer()

@router.callback_query(F.data.startswith("select_supplier_"), OrderFSM.waiting_for_supplier_selection)
async def process_supplier_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    """Обрабатывает выбор поставщика и переходит к добавлению позиций."""
    supplier_id = int(callback.data.split("_")[2])
    await state.update_data(supplier_id=supplier_id)

    suppliers = await get_all_suppliers(db_pool)
    selected_supplier = next((s for s in suppliers if s.supplier_id == supplier_id), None)
    if selected_supplier:
        await state.update_data(supplier_name=selected_supplier.name)

    # Переходим к меню добавления позиций
    await show_add_delivery_items_menu(callback.message, state) # Передаем message_object
    await callback.answer()


@router.callback_query(F.data == "add_delivery_item", OrderFSM.adding_delivery_items)
async def add_delivery_item_start(callback: CallbackQuery, state: FSMContext, db_pool):
    """Начинает процесс добавления новой позиции в поступление."""
    products = await get_all_products_for_selection(db_pool)
    if not products:
        await callback.message.edit_text(escape_markdown_v2("Нет доступных продуктов. Пожалуйста, добавьте продукты в базу данных."), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.adding_delivery_items) # Возвращаемся в меню позиций
        await callback.answer()
        return

    keyboard = build_products_keyboard(products)
    await callback.message.edit_text(escape_markdown_v2("Выберите продукт для поступления:"), reply_markup=keyboard, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.waiting_for_delivery_product_selection)
    await callback.answer()

@router.callback_query(F.data.startswith("select_product_for_delivery_"), OrderFSM.waiting_for_delivery_product_selection)
async def process_delivery_product_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    """Обрабатывает выбор продукта для поступления."""
    product_id = int(callback.data.split("_")[4]) # split("_")[4] из-за "select_product_for_delivery_"
    await state.update_data(current_product_id=product_id)

    products = await get_all_products_for_selection(db_pool)
    selected_product = next((p for p in products if p.product_id == product_id), None)
    
    # Экранируем только имя продукта, т.к. оно динамическое
    product_name_escaped = escape_markdown_v2(selected_product.name) if selected_product else escape_markdown_v2("продукта")
    
    # Сохраняем имя продукта в состоянии для последующего использования в process_delivery_quantity и process_delivery_unit_cost
    await state.update_data(current_product_name=selected_product.name if selected_product else None)


    # Формируем итоговый текст, явно экранируя скобки
    final_message_text = f"Введите количество для *{product_name_escaped}* \\(целое число\\):"
    
    logger.info(f"DEBUG: Отправляется сообщение: {final_message_text}") # Отладочный вывод
    logger.info(f"DEBUG: State data at end of process_delivery_product_selection: {await state.get_data()}") # Отладочный вывод состояния

    # Здесь final_message_text уже содержит правильную MarkdownV2 разметку
    await callback.message.edit_text(final_message_text, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.waiting_for_delivery_quantity)
    await callback.answer()

@router.message(OrderFSM.waiting_for_delivery_quantity)
async def process_delivery_quantity(message: Message, state: FSMContext):
    """Обрабатывает введенное количество товара для поступления."""
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
            await message.answer(escape_markdown_v2("Количество должно быть положительным целым числом."), parse_mode="MarkdownV2")
            return
        await state.update_data(current_quantity=quantity)
        
        data = await state.get_data()
        
        # --- DEBUGGING START ---
        logger.info(f"DEBUG: In process_delivery_quantity, full state data: {data}")
        product_name = data.get('current_product_name', 'продукта')
        logger.info(f"DEBUG: In process_delivery_quantity, product_name: {product_name} (type: {type(product_name)})")
        # --- DEBUGGING END ---

        # Экранируем только имя продукта, а скобки и точку явно в строке
        await message.answer(f"Введите стоимость за единицу *{escape_markdown_v2(product_name)}* \\(например, 100\\.50\\):", parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.waiting_for_delivery_unit_cost)
    except ValueError:
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await message.answer(escape_markdown_v2("Неверный формат количества. Пожалуйста, введите целое число."), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Ошибка при обработке количества поступления: {e}", exc_info=True)
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await message.answer(escape_markdown_v2("Произошла ошибка. Пожалуйста, попробуйте снова или отмените операцию."), parse_mode="MarkdownV2")

@router.message(OrderFSM.waiting_for_delivery_unit_cost)
async def process_delivery_unit_cost(message: Message, state: FSMContext):
    """Обрабатывает введенную стоимость за единицу товара и добавляет позицию."""
    # Инициализируем delivery_items здесь, чтобы Pylance не выдавал предупреждение
    delivery_items: List[Dict[str, Any]] = [] 
    try:
        unit_cost = Decimal(message.text.strip())
        if unit_cost <= 0:
            # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
            await message.answer(escape_markdown_v2("Стоимость должна быть положительным числом."), parse_mode="MarkdownV2")
            return
        
        data = await state.get_data()
        
        # Safely get current_product_name, providing a default if it's missing
        product_name_for_item = data.get('current_product_name', 'Неизвестный продукт') 
        
        # Добавляем новую позицию
        new_item = {
            'product_id': data['current_product_id'], 
            'product_name': product_name_for_item, # Используем безопасно полученное имя
            'quantity': data['current_quantity'], 
            'unit_cost': unit_cost
        }
        
        # Переопределяем delivery_items из данных состояния
        delivery_items = data.get('delivery_items', []) 
        delivery_items.append(new_item)
        await state.update_data(delivery_items=delivery_items)

        # Очищаем временные данные для текущей позиции
        await state.update_data(current_product_id=None, current_product_name=None, current_quantity=None)

        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await message.answer(escape_markdown_v2("Позиция добавлена."), parse_mode="MarkdownV2")
        await show_add_delivery_items_menu(message, state) # Возвращаемся в меню позиций

    except ValueError:
        # Эта строка является обычным текстом, содержащим точку и скобки, поэтому ее нужно экранировать.
        await message.answer(escape_markdown_v2("Неверный формат стоимости. Пожалуйста, введите число (например, 100.50)."), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Ошибка при обработке стоимости единицы поступления: {e}", exc_info=True)
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await message.answer(escape_markdown_v2("Произошла ошибка. Пожалуйста, попробуйте снова или отмените операцию."), parse_mode="MarkdownV2")


@router.callback_query(F.data == "back_to_adding_delivery_items")
async def back_to_adding_delivery_items_handler(callback: CallbackQuery, state: FSMContext):
    """Возвращает пользователя в меню добавления/редактирования позиций поступления."""
    await callback.answer()
    await show_add_delivery_items_menu(callback.message, state)


@router.callback_query(F.data == "edit_delivery_item", OrderFSM.adding_delivery_items)
async def edit_delivery_item_start(callback: CallbackQuery, state: FSMContext):
    """Показывает список позиций для редактирования."""
    data = await state.get_data()
    items = data.get('delivery_items', [])
    if not items:
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await callback.answer(escape_markdown_v2("Нет позиций для редактирования."), show_alert=True)
        return
    
    keyboard = build_delivery_items_list_keyboard(items, "edit_selected_delivery_item_")
    await callback.message.edit_text(escape_markdown_v2("Выберите позицию для редактирования:"), reply_markup=keyboard, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.editing_delivery_item_selection)
    await callback.answer()

@router.callback_query(F.data.startswith("edit_selected_delivery_item_"), StateFilter(OrderFSM.editing_delivery_item_selection))
async def select_item_to_edit_action(callback: CallbackQuery, state: FSMContext):
    """Выбирает действие для редактирования позиции (кол-во/цена)."""
    # ИСПРАВЛЕНО: Изменен индекс с [3] на [4]
    item_index = int(callback.data.split("_")[4])
    await state.update_data(editing_item_index=item_index) # Сохраняем индекс редактируемой позиции
    
    data = await state.get_data()
    item = data['delivery_items'][item_index]
    
    keyboard = build_edit_delivery_item_keyboard(item_index)
    # ИСПРАВЛЕНО: Заключены числа в обратные кавычки для автоматического экранирования
    await callback.message.edit_text(
        f"Что вы хотите изменить в позиции: *{escape_markdown_v2(item['product_name'])}* \\(Кол\\-во: `{item['quantity']}`, Цена: `{item['unit_cost']:.2f} ₴`\\)\\?",
        reply_markup=keyboard,
        parse_mode="MarkdownV2"
    )
    await state.set_state(OrderFSM.editing_delivery_item_action)
    await callback.answer()

@router.callback_query(F.data.startswith("edit_delivery_item_qty_"), OrderFSM.editing_delivery_item_action)
async def start_edit_delivery_quantity(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения количества для позиции поступления."""
    item_index = int(callback.data.split("_")[4])
    data = await state.get_data()
    item = data['delivery_items'][item_index]
    
    await state.update_data(editing_item_index=item_index)
    # ИСПРАВЛЕНО: Заключены числа в обратные кавычки для автоматического экранирования
    await callback.message.edit_text(f"Введите новое количество для *{escape_markdown_v2(item['product_name'])}* \\(текущее: `{item['quantity']}`\\):", parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.entering_new_delivery_quantity)
    await callback.answer()

@router.message(OrderFSM.entering_new_delivery_quantity)
async def process_new_delivery_quantity(message: Message, state: FSMContext):
    """Обрабатывает новое количество для позиции поступления."""
    try:
        new_quantity = int(message.text.strip())
        if new_quantity <= 0:
            # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
            await message.answer(escape_markdown_v2("Количество должно быть положительным целым числом."), parse_mode="MarkdownV2")
            return
        await state.update_data(current_quantity=new_quantity) # ИСПРАВЛЕНО: Обновляем current_quantity
        
        data = await state.get_data()
        item_index = data['editing_item_index']
        delivery_items = data['delivery_items']
        
        delivery_items[item_index]['quantity'] = new_quantity
        await state.update_data(delivery_items=delivery_items)
        
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await message.answer(escape_markdown_v2("Количество обновлено."), parse_mode="MarkdownV2")
        await show_add_delivery_items_menu(message, state) # Возвращаемся в меню позиций

    except ValueError:
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await message.answer(escape_markdown_v2("Неверный формат количества. Пожалуйста, введите целое число."), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Ошибка при обработке нового количества поступления: {e}", exc_info=True)
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await message.answer(escape_markdown_v2("Произошла ошибка. Пожалуйста, попробуйте снова или отмените операцию."), parse_mode="MarkdownV2")


@router.callback_query(F.data.startswith("edit_delivery_item_cost_"), OrderFSM.editing_delivery_item_action)
async def start_edit_delivery_unit_cost(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения цены за единицу для позиции поступления."""
    # Здесь callback.data будет иметь вид "edit_delivery_item_cost_X"
    # split("_") даст ["edit", "delivery", "item", "cost", "X"]
    # Так что [4] будет правильным индексом
    item_index = int(callback.data.split("_")[4])
    data = await state.get_data()
    item = data['delivery_items'][item_index]
    
    await state.update_data(editing_item_index=item_index)
    # ИСПРАВЛЕНО: Заключены числа в обратные кавычки для автоматического экранирования
    await callback.message.edit_text(f"Введите новую цену за единицу для *{escape_markdown_v2(item['product_name'])}* \\(текущая: `{item['unit_cost']:.2f} ₴`\\):", parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.entering_new_delivery_unit_cost)
    await callback.answer()

@router.message(OrderFSM.entering_new_delivery_unit_cost)
async def process_new_delivery_unit_cost(message: Message, state: FSMContext):
    """Обрабатывает новую цену за единицу для позиции поступления."""
    try:
        new_unit_cost = Decimal(message.text.strip())
        if new_unit_cost <= 0:
            # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
            await message.answer(escape_markdown_v2("Стоимость должна быть положительным числом."), parse_mode="MarkdownV2")
            return
        
        data = await state.get_data()
        item_index = data['editing_item_index']
        delivery_items = data['delivery_items']
        
        delivery_items[item_index]['unit_cost'] = new_unit_cost
        await state.update_data(delivery_items=delivery_items)
        
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await message.answer(escape_markdown_v2("Цена за единицу обновлена."), parse_mode="MarkdownV2")
        await show_add_delivery_items_menu(message, state) # Возвращаемся в меню позиций

    except ValueError:
        # Эта строка является обычным текстом, содержащим точку и скобки, поэтому ее нужно экранировать.
        await message.answer(escape_markdown_v2("Неверный формат стоимости. Пожалуйста, введите число (например, 100.50)."), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Ошибка при обработке новой стоимости единицы поступления: {e}", exc_info=True)
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await message.answer(escape_markdown_v2("Произошла ошибка. Пожалуйста, попробуйте снова или отмените операцию."), parse_mode="MarkdownV2")


@router.callback_query(F.data == "delete_delivery_item", OrderFSM.adding_delivery_items)
async def delete_delivery_item_start(callback: CallbackQuery, state: FSMContext):
    """Показывает список позиций для удаления."""
    data = await state.get_data()
    items = data.get('delivery_items', [])
    if not items:
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await callback.answer(escape_markdown_v2("Нет позиций для удаления."), show_alert=True)
        return
    
    keyboard = build_delivery_items_list_keyboard(items, "delete_selected_delivery_item_")
    await callback.message.edit_text(escape_markdown_v2("Выберите позицию для удаления:"), reply_markup=keyboard, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.deleting_item)
    await callback.answer()

@router.callback_query(F.data.startswith("delete_selected_delivery_item_"), StateFilter(OrderFSM.deleting_item))
async def confirm_delete_delivery_item(callback: CallbackQuery, state: FSMContext):
    """Удаляет выбранную позицию из списка."""
    # ИСПРАВЛЕНО: Изменен индекс с [3] на [4]
    item_index = int(callback.data.split("_")[4])
    data = await state.get_data()
    delivery_items = data.get('delivery_items', [])
    
    if 0 <= item_index < len(delivery_items):
        deleted_item = delivery_items.pop(item_index)
        # Экранируем сообщение об удалении
        await callback.answer(escape_markdown_v2(f"Позиция '{deleted_item['product_name']}' удалена."), show_alert=True)
        await state.update_data(delivery_items=delivery_items) # Обновляем состояние после удаления
    else:
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await callback.answer(escape_markdown_v2("Неверный индекс позиции."), show_alert=True)
    
    await show_add_delivery_items_menu(callback.message, state) # Возвращаемся в меню позиций


@router.callback_query(F.data == "finish_delivery_creation", OrderFSM.adding_delivery_items)
async def finish_delivery_creation(callback: CallbackQuery, state: FSMContext):
    """Завершает формирование поступления и переходит к подтверждению."""
    data = await state.get_data()
    items = data.get('delivery_items', [])
    if not items:
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await callback.answer(escape_markdown_v2("Невозможно завершить: нет позиций в поступлении."), show_alert=True)
        return
    
    summary_text = get_delivery_summary_text(data)
    keyboard = build_confirm_delivery_keyboard()
    # Здесь summary_text уже должен быть правильно отформатирован, без необходимости внешнего escape_markdown_v2
    await callback.message.edit_text(summary_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.confirm_delivery_data)
    await callback.answer()


@router.callback_query(F.data == "confirm_delivery_data", OrderFSM.confirm_delivery_data)
async def confirm_and_record_delivery(callback: CallbackQuery, state: FSMContext, db_pool):
    """Подтверждает и записывает все позиции поступления в БД."""
    data = await state.get_data()
    delivery_date = data['delivery_date']
    supplier_id = data['supplier_id']
    delivery_items = data.get('delivery_items', [])

    if not delivery_items:
        # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
        await callback.message.edit_text(escape_markdown_v2("Невозможно записать: нет позиций в поступлении."), parse_mode="MarkdownV2")
        await state.clear()
        await callback.answer()
        return

    success_count = 0
    failed_count = 0
    
    for item in delivery_items:
        product_id = item['product_id']
        quantity = item['quantity']
        unit_cost = item['unit_cost']

        inserted_id = await record_incoming_delivery( # Вызываем для каждой позиции
            db_pool,
            delivery_date,
            supplier_id,
            product_id,
            quantity,
            unit_cost
        )

        if inserted_id:
            success_count += 1
        else:
            failed_count += 1
            logger.error(f"Не удалось записать поступление для продукта ID {product_id}.")
    
    final_message = f"✅ Поступление успешно записано\\. Записано позиций: `{success_count}`\\. Ошибок: `{failed_count}`\\."
    if failed_count > 0:
        final_message += escape_markdown_v2("\nНекоторые позиции не были записаны из-за ошибок.") # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
    
    # final_message уже должен быть правильно отформатирован
    await callback.message.edit_text(final_message, parse_mode="MarkdownV2")
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "cancel_add_delivery") # <--- Убрал StateFilter, чтобы можно было отменить из любого состояния
async def cancel_add_delivery(callback: CallbackQuery, state: FSMContext):
    """Отменяет процесс добавления поступления."""
    await state.clear()
    # Эта строка является обычным текстом, содержащим точку, поэтому ее нужно экранировать.
    await callback.message.edit_text(escape_markdown_v2("Операция добавления поступления отменена."), parse_mode="MarkdownV2")
    await callback.answer()

@router.callback_query(F.data == "edit_delivery_data", OrderFSM.confirm_delivery_data)
async def edit_delivery_data(callback: CallbackQuery, state: FSMContext):
    """Позволяет пользователю изменить введенные данные."""
    await callback.answer()
    await show_add_delivery_items_menu(callback.message, state) # Возвращаемся в меню позиций


# --- Вспомогательная функция для отображения меню позиций ---
async def show_add_delivery_items_menu(message: Message, state: FSMContext):
    """
    Показывает меню для добавления/редактирования позиций поступления.
    """
    data = await state.get_data()
    items = data.get('delivery_items', [])
    
    summary_text = get_delivery_summary_text(data)
    keyboard = build_add_delivery_item_menu_keyboard(bool(items))
    
    try:
        # summary_text уже должен быть правильно отформатирован
        await message.edit_text(summary_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    except Exception as e:
        logger.warning(f"Не удалось отредактировать сообщение при показе меню позиций: {e}")
        # Если редактирование не удалось, отправляем новое сообщение.
        # summary_text уже должен быть правильно отформатирован.
        await message.answer(summary_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    
    await state.set_state(OrderFSM.adding_delivery_items)