# handlers/reports/add_delivery_handler.py

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter

from states.order import OrderFSM # Импортируем FSM состояния
# ОБНОВЛЕННЫЕ ИМПОРТЫ ИЗ db_operations
from db_operations.product_operations import get_all_products_for_selection, ProductItem, get_product_by_id
from db_operations.supplier_operations import (
    find_suppliers_by_name, Supplier, create_supplier_invoice,
    record_incoming_delivery as record_incoming_delivery_line, # Импортируем как record_incoming_delivery_line
    get_supplier_by_id
)

router = Router()
logger = logging.getLogger(__name__)

# --- КОНСТАНТЫ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
MAX_RESULTS_TO_SHOW = 10 # Для отображения поставщиков
DEFAULT_DUE_DATE_DAYS = 7 # Срок оплаты по умолчанию (7 дней)

def escape_markdown_v2(text: str) -> str:
    """Escapes all special characters for MarkdownV2."""
    if text is None:
        return ""
    text = text.replace('\\', '\\\\')
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    escaped_text_parts = []
    for char in text:
        if char in special_chars:
            escaped_text_parts.append('\\' + char)
        else:
            escaped_text_parts.append(char)
    return "".join(escaped_text_parts)

# --- Клавиатуры ---

def build_date_selection_keyboard(current_date: date) -> InlineKeyboardMarkup:
    """Строит инлайн-клавиатуру для выбора даты, показывая +/- 7 дней от текущей."""
    buttons = []
    row = []
    for i in range(-7, 8):
        day = current_date + timedelta(days=i)
        row.append(InlineKeyboardButton(text=day.strftime('%d.%m'), callback_data=f"select_inv_date_{day.isoformat()}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_new_supplier_invoice")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_supplier_selection_keyboard(suppliers: List[Supplier]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора поставщика."""
    buttons = []
    for supplier in suppliers[:MAX_RESULTS_TO_SHOW]:
        buttons.append([
            InlineKeyboardButton(
                text=escape_markdown_v2(supplier.name),
                callback_data=f"select_supplier_for_new_inv_{supplier.supplier_id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_new_supplier_invoice")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_products_keyboard(products: List[ProductItem]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора продукта."""
    buttons = []
    for product in products:
        buttons.append([
            InlineKeyboardButton(
                text=escape_markdown_v2(product.name),
                callback_data=f"select_product_for_new_inv_item_{product.product_id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_new_supplier_invoice")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_add_supplier_invoice_item_menu_keyboard(has_items: bool) -> InlineKeyboardMarkup:
    """Строит клавиатуру для меню добавления/редактирования позиций накладной поставщика."""
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить позицию", callback_data="add_new_supplier_invoice_item")],
    ]
    if has_items:
        buttons.append([
            InlineKeyboardButton(text="✅ Завершить накладную", callback_data="finish_new_supplier_invoice_creation")
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_new_supplier_invoice")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_confirm_new_supplier_invoice_keyboard() -> InlineKeyboardMarkup:
    """Строит клавиатуру для подтверждения данных накладной поставщика."""
    buttons = [
        [InlineKeyboardButton(text="✅ Подтвердить и создать", callback_data="confirm_new_supplier_invoice_data")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_new_supplier_invoice_data")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_new_supplier_invoice")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Вспомогательные функции для сводки ---

def get_supplier_invoice_summary_text(data: Dict[str, Any]) -> str:
    """Формирует сводный текст о новой накладной поставщика, правильно экранируя для MarkdownV2."""
    invoice_date_str = data.get('new_supplier_invoice_date', date.today()).strftime('%Y-%m-%d')
    supplier_name_escaped = escape_markdown_v2(data.get('new_supplier_name', 'Неизвестно'))
    invoice_number_escaped = escape_markdown_v2(data.get('new_supplier_invoice_number', 'Без номера'))
    due_date_str = data.get('new_supplier_invoice_due_date', 'Не указан').strftime('%Y-%m-%d') if data.get('new_supplier_invoice_due_date') else 'Не указан'
    
    items = data.get('new_supplier_invoice_items', [])
    
    summary_parts = [
        "🧾 *Сводка по новой накладной поставщика:*\n",
        f"📅 Дата накладной: `{invoice_date_str}`\n",
        f"👤 Поставщик: *{supplier_name_escaped}*\n",
        f"📝 Номер накладной: *{invoice_number_escaped}*\n",
        f"🗓️ Срок оплаты: `{due_date_str}`\n",
        "\n*Позиции:*\n"
    ]
    
    total_invoice_amount = Decimal('0.00')
    if not items:
        summary_parts.append(escape_markdown_v2("   (Позиции пока не добавлены)"))
    else:
        for i, item in enumerate(items):
            item_total = item['quantity'] * item['unit_cost']
            total_invoice_amount += item_total
            
            product_name_escaped = escape_markdown_v2(item['product_name'])

            summary_parts.append(
                f"   *{i+1}\\. {product_name_escaped}*\n"
                f"      Кол\\-во: `{item['quantity']}` ед\\. по `{item['unit_cost']:.2f} ₴`\n"
                f"      Сумма по позиции: `{item_total:.2f} ₴`\n"
            )
    
    summary_parts.append(f"\n*Общая сумма накладной: `{total_invoice_amount:.2f} ₴`*")
    
    return "".join(summary_parts)


# --- Хендлеры для процесса добавления поступления/накладной поставщика ---

@router.message(Command("add_delivery"))
async def cmd_add_delivery(message: Message, state: FSMContext):
    """Начинает процесс добавления новой накладной поставщика."""
    await state.clear()
    await state.update_data(new_supplier_invoice_items=[]) # Инициализируем позиции накладной
    
    current_date = date.today()
    keyboard = build_date_selection_keyboard(current_date)
    await message.answer(escape_markdown_v2("Выберите дату накладной поставщика:"), reply_markup=keyboard, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.waiting_for_new_supplier_invoice_date)

@router.callback_query(F.data.startswith("select_inv_date_"), OrderFSM.waiting_for_new_supplier_invoice_date)
async def process_new_supplier_invoice_date_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    """Обрабатывает выбор даты накладной поставщика."""
    await callback.answer()
    selected_date_str = callback.data.split("_")[3]
    invoice_date = date.fromisoformat(selected_date_str)
    await state.update_data(new_supplier_invoice_date=invoice_date)

    await callback.message.edit_text(escape_markdown_v2("Введите имя или название поставщика:"), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.waiting_for_new_supplier_invoice_supplier)

@router.message(StateFilter(OrderFSM.waiting_for_new_supplier_invoice_supplier))
async def process_new_supplier_invoice_supplier_input(message: Message, state: FSMContext, db_pool):
    """Обрабатывает ввод имени поставщика для новой накладной."""
    supplier_name_query = message.text.strip()
    suppliers = await find_suppliers_by_name(db_pool, supplier_name_query)

    if suppliers:
        if len(suppliers) == 1:
            supplier = suppliers[0]
            await state.update_data(new_supplier_id=supplier.supplier_id, new_supplier_name=supplier.name)
            await message.answer(f"✅ Выбран поставщик: *{escape_markdown_v2(supplier.name)}*", parse_mode="MarkdownV2")
            await message.answer(escape_markdown_v2("Введите номер накладной поставщика:"), parse_mode="MarkdownV2")
            await state.set_state(OrderFSM.waiting_for_new_supplier_invoice_number)
        elif 1 < len(suppliers) <= MAX_RESULTS_TO_SHOW:
            keyboard = build_supplier_selection_keyboard(suppliers)
            await message.answer(escape_markdown_v2("Найдено несколько поставщиков. Выберите одного:"), reply_markup=keyboard, parse_mode="MarkdownV2")
        else:
            await message.answer(escape_markdown_v2(f"Найдено слишком много поставщиков ({len(suppliers)}). Пожалуйста, уточните запрос."), parse_mode="MarkdownV2")
    else:
        await message.answer("Поставщик с таким именем не найден. Пожалуйста, попробуйте еще раз.")

@router.callback_query(StateFilter(OrderFSM.waiting_for_new_supplier_invoice_supplier), F.data.startswith("select_supplier_for_new_inv_"))
async def select_new_supplier_invoice_supplier(callback: CallbackQuery, state: FSMContext, db_pool):
    """Обрабатывает выбор поставщика из списка для новой накладной."""
    await callback.answer()
    supplier_id = int(callback.data.split("_")[4])
    supplier = await get_supplier_by_id(db_pool, supplier_id)
    
    if supplier:
        await state.update_data(new_supplier_id=supplier.supplier_id, new_supplier_name=supplier.name)
        await callback.message.edit_text(f"✅ Выбран поставщик: *{escape_markdown_v2(supplier.name)}*", parse_mode="MarkdownV2", reply_markup=None)
        await callback.message.answer(escape_markdown_v2("Введите номер накладной поставщика:"), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.waiting_for_new_supplier_invoice_number)
    else:
        await callback.answer("Ошибка при выборе поставщика. Попробуйте снова.", show_alert=True)

@router.message(StateFilter(OrderFSM.waiting_for_new_supplier_invoice_number))
async def process_new_supplier_invoice_number(message: Message, state: FSMContext):
    """Обрабатывает ввод номера накладной поставщика."""
    invoice_number = message.text.strip()
    if not invoice_number:
        await message.answer(escape_markdown_v2("Номер накладной не может быть пустым. Введите номер:"), parse_mode="MarkdownV2")
        return
    await state.update_data(new_supplier_invoice_number=invoice_number)

    # Предлагаем срок оплаты по умолчанию
    invoice_date = (await state.get_data()).get('new_supplier_invoice_date', date.today())
    default_due_date = invoice_date + timedelta(days=DEFAULT_DUE_DATE_DAYS)

    await message.answer(
        escape_markdown_v2(f"Введите срок оплаты накладной (например, `{default_due_date.strftime('%Y-%m-%d')}` для {DEFAULT_DUE_DATE_DAYS} дней, или 'нет', если без срока):"),
        parse_mode="MarkdownV2"
    )
    await state.set_state(OrderFSM.waiting_for_new_supplier_invoice_due_date)

@router.message(StateFilter(OrderFSM.waiting_for_new_supplier_invoice_due_date))
async def process_new_supplier_invoice_due_date(message: Message, state: FSMContext):
    """Обрабатывает ввод срока оплаты накладной."""
    due_date_str = message.text.strip()
    new_due_date = None
    if due_date_str.lower() != 'нет':
        try:
            new_due_date = date.fromisoformat(due_date_str)
            if new_due_date < date.today():
                await message.answer(escape_markdown_v2("Срок оплаты не может быть в прошлом. Введите корректную дату:"), parse_mode="MarkdownV2")
                return
        except ValueError:
            await message.answer(escape_markdown_v2("Неверный формат даты. Введите дату в формате ГГГГ-ММ-ДД или 'нет':"), parse_mode="MarkdownV2")
            return
    
    await state.update_data(new_supplier_invoice_due_date=new_due_date)
    await show_add_supplier_invoice_items_menu(message, state) # Переходим к добавлению позиций
    await state.set_state(OrderFSM.adding_new_supplier_invoice_items)

async def show_add_supplier_invoice_items_menu(message: Message, state: FSMContext):
    """Показывает меню для добавления/редактирования позиций новой накладной поставщика."""
    data = await state.get_data()
    items = data.get('new_supplier_invoice_items', [])
    
    summary_text = get_supplier_invoice_summary_text(data)
    keyboard = build_add_supplier_invoice_item_menu_keyboard(bool(items))
    
    try:
        await message.edit_text(summary_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    except Exception as e:
        logger.warning(f"Не удалось отредактировать сообщение при показе меню позиций накладной поставщика: {e}")
        await message.answer(summary_text, reply_markup=keyboard, parse_mode="MarkdownV2")

@router.callback_query(F.data == "add_new_supplier_invoice_item", StateFilter(OrderFSM.adding_new_supplier_invoice_items))
async def add_new_supplier_invoice_item_start(callback: CallbackQuery, state: FSMContext, db_pool):
    """Начинает процесс добавления новой позиции в накладную поставщика."""
    await callback.answer()
    products = await get_all_products_for_selection(db_pool)
    if not products:
        await callback.message.edit_text(escape_markdown_v2("Нет доступных продуктов. Пожалуйста, добавьте продукты в базу данных."), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.adding_new_supplier_invoice_items)
        return

    keyboard = build_products_keyboard(products)
    await callback.message.edit_text(escape_markdown_v2("Выберите продукт для поступления:"), reply_markup=keyboard, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.waiting_for_new_supplier_invoice_product_selection)

@router.callback_query(F.data.startswith("select_product_for_new_inv_item_"), StateFilter(OrderFSM.waiting_for_new_supplier_invoice_product_selection))
async def process_new_supplier_invoice_product_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    """Обрабатывает выбор продукта для новой накладной поставщика."""
    await callback.answer()
    product_id = int(callback.data.split("_")[6])
    product_info = await get_product_by_id(db_pool, product_id)
    
    if product_info:
        await state.update_data(current_new_inv_item_product_id=product_id, current_new_inv_item_product_name=product_info.name)
        await callback.message.edit_text(
            f"Введите количество для *{escape_markdown_v2(product_info.name)}* \\(целое число\\):",
            parse_mode="MarkdownV2"
        )
        await state.set_state(OrderFSM.waiting_for_new_supplier_invoice_quantity)
    else:
        await callback.message.edit_text(escape_markdown_v2("Неизвестный продукт. Пожалуйста, выберите из списка."), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.adding_new_supplier_invoice_items) # Возвращаемся в меню добавления позиций

@router.message(StateFilter(OrderFSM.waiting_for_new_supplier_invoice_quantity))
async def process_new_supplier_invoice_quantity(message: Message, state: FSMContext):
    """Обрабатывает введенное количество товара для новой накладной поставщика."""
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            await message.answer(escape_markdown_v2("Количество должно быть положительным целым числом."), parse_mode="MarkdownV2")
            return
        await state.update_data(current_new_inv_item_quantity=quantity)
        
        product_name = (await state.get_data()).get('current_new_inv_item_product_name', 'продукта')
        await message.answer(f"Введите стоимость за единицу *{escape_markdown_v2(product_name)}* \\(например, 100\\.50\\):", parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.waiting_for_new_supplier_invoice_unit_cost)
    except ValueError:
        await message.answer(escape_markdown_v2("Неверный формат количества. Пожалуйста, введите целое число."), parse_mode="MarkdownV2")

@router.message(StateFilter(OrderFSM.waiting_for_new_supplier_invoice_unit_cost))
async def process_new_supplier_invoice_unit_cost(message: Message, state: FSMContext):
    """Обрабатывает введенную стоимость за единицу товара и добавляет позицию."""
    try:
        unit_cost = Decimal(message.text.strip())
        if unit_cost <= 0:
            await message.answer(escape_markdown_v2("Стоимость должна быть положительным числом."), parse_mode="MarkdownV2")
            return
        
        data = await state.get_data()
        items = data.get('new_supplier_invoice_items', [])
        
        new_item = {
            'product_id': data['current_new_inv_item_product_id'], 
            'product_name': data['current_new_inv_item_product_name'],
            'quantity': data['current_new_inv_item_quantity'], 
            'unit_cost': unit_cost
        }
        items.append(new_item)
        await state.update_data(new_supplier_invoice_items=items)

        # Очищаем временные данные для текущей позиции
        await state.update_data(current_new_inv_item_product_id=None, current_new_inv_item_product_name=None, current_new_inv_item_quantity=None)

        await message.answer(escape_markdown_v2("Позиция добавлена."), parse_mode="MarkdownV2")
        await show_add_supplier_invoice_items_menu(message, state)
        await state.set_state(OrderFSM.adding_new_supplier_invoice_items)

    except ValueError:
        await message.answer(escape_markdown_v2("Неверный формат стоимости. Пожалуйста, введите число (например, 100.50)."), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Ошибка при обработке стоимости единицы для новой накладной: {e}", exc_info=True)
        await message.answer(escape_markdown_v2("Произошла ошибка. Пожалуйста, попробуйте снова или отмените операцию."), parse_mode="MarkdownV2")

@router.callback_query(F.data == "finish_new_supplier_invoice_creation", StateFilter(OrderFSM.adding_new_supplier_invoice_items))
async def finish_new_supplier_invoice_creation(callback: CallbackQuery, state: FSMContext):
    """Завершает формирование накладной поставщика и переходит к подтверждению."""
    await callback.answer()
    data = await state.get_data()
    items = data.get('new_supplier_invoice_items', [])
    if not items:
        await callback.answer(escape_markdown_v2("Невозможно завершить: нет позиций в накладной."), show_alert=True)
        return
    
    summary_text = get_supplier_invoice_summary_text(data)
    keyboard = build_confirm_new_supplier_invoice_keyboard()
    await callback.message.edit_text(summary_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.confirm_new_supplier_invoice_data)

@router.callback_query(F.data == "confirm_new_supplier_invoice_data", StateFilter(OrderFSM.confirm_new_supplier_invoice_data))
async def confirm_and_create_supplier_invoice(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    data = await state.get_data()
    
    invoice_date = data['new_supplier_invoice_date']
    supplier_id = data['new_supplier_id']
    invoice_number = data['new_supplier_invoice_number']
    due_date = data['new_supplier_invoice_due_date']
    items = data.get('new_supplier_invoice_items', [])

    if not items:
        # Убедимся, что это сообщение тоже экранировано
        await callback.message.edit_text(escape_markdown_v2("Невозможно создать: нет позиций в накладной."), parse_mode="MarkdownV2")
        await state.clear()
        return

    total_amount = sum(item['quantity'] * item['unit_cost'] for item in items)
    
    supplier_invoice_id = await create_supplier_invoice(
        db_pool,
        supplier_id,
        invoice_number,
        invoice_date,
        total_amount,
        due_date,
        description="Создано через Telegram-бота"
    )

    if supplier_invoice_id:
        success_count = 0
        failed_count = 0
        for item in items:
            inserted_id = await record_incoming_delivery_line(
                db_pool,
                delivery_date=invoice_date,
                supplier_id=supplier_id,
                product_id=item['product_id'],
                quantity=item['quantity'],
                unit_cost=item['unit_cost'],
                supplier_invoice_id=supplier_invoice_id
            )
            if inserted_id:
                success_count += 1
            else:
                failed_count += 1
                logger.error(f"Не удалось записать позицию поступления для продукта ID {item['product_id']}.")
        
        # --- ИСПРАВЛЕНО ЗДЕСЬ: Экранируем всю строку целиком ---
        final_message_raw = f"✅ Накладная поставщика *{invoice_number}* успешно создана!\nЗаписано позиций: `{success_count}`. Ошибок: `{failed_count}`."
        if failed_count > 0:
            final_message_raw += "\nНекоторые позиции не были записаны из-за ошибок."
        
        await callback.message.edit_text(escape_markdown_v2(final_message_raw), parse_mode="MarkdownV2") # Экранируем весь текст
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
    else:
        # Убедимся, что это сообщение тоже экранировано
        await callback.message.edit_text(escape_markdown_v2("❌ Произошла ошибка при создании накладной поставщика. Возможно, номер накладной уже существует."), parse_mode="MarkdownV2")
    
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "edit_new_supplier_invoice_data", StateFilter(OrderFSM.confirm_new_supplier_invoice_data))
async def edit_new_supplier_invoice_data(callback: CallbackQuery, state: FSMContext, db_pool):
    """Позволяет пользователю изменить введенные данные."""
    await callback.answer()
    await show_add_supplier_invoice_items_menu(callback.message, state)
    await state.set_state(OrderFSM.adding_new_supplier_invoice_items)

@router.callback_query(F.data == "cancel_new_supplier_invoice")
async def cancel_new_supplier_invoice(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(escape_markdown_v2("Операция создания накладной поставщика отменена."), parse_mode="MarkdownV2")
    await callback.answer()


# --- Хендлеры для корректировок инвентаря (return_in, adjustment_in/out) --- (БЕЗ ИЗМЕНЕНИЙ, кроме изменения FSM States)
# ... (process_return_quantity, process_adjustment_description, confirm_and_record_adjustment, edit_adjustment_data, cancel_adjustment) ...

# --- Хендлеры для возврата поставщику (return_out) --- (БЕЗ ИЗМЕНЕНИЙ, кроме изменения FSM States)
# ... (process_supplier_name_input, select_supplier_for_return_from_list, select_another_supplier_return, process_incoming_delivery_input, process_incoming_delivery_selection, show_products_for_return_to_supplier_selection, process_return_to_supplier_product, confirm_adj_product_to_supplier, select_another_adj_product_to_supplier, process_return_to_supplier_quantity, process_return_to_supplier_description, confirm_and_record_return_to_supplier) ...