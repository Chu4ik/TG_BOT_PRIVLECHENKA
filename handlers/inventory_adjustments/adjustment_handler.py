# handlers/inventory_adjustments/adjustment_handler.py

import logging
import re
from datetime import date, datetime, timedelta # Добавляем timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional, NamedTuple

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter

from states.order import OrderFSM
# ИМПОРТЫ ИЗ db_operations
from db_operations.product_operations import get_all_products_for_selection, ProductItem, record_stock_movement, get_product_by_id, get_products_sold_to_client
from db_operations.client_operations import find_clients_by_name, get_client_by_id
from db_operations.report_payment_operations import get_client_outstanding_invoices, UnpaidInvoice, get_order_by_invoice_number
from db_operations.supplier_operations import (
    find_suppliers_by_name, get_supplier_by_id, get_supplier_incoming_deliveries,
    record_supplier_payment_or_return, IncomingDelivery, SupplierInvoice, create_supplier_invoice,
    get_supplier_invoice_by_number, record_incoming_delivery as record_incoming_delivery_line, Supplier # Импортируем как record_incoming_delivery_line
)

router = Router()
logger = logging.getLogger(__name__)

# --- КОНСТАНТЫ ДЛЯ ОГРАНИЧЕНИЯ СПИСКОВ ВЫБОРА ---
MAX_RESULTS_TO_SHOW = 10 # Максимальное количество клиентов/накладных/поставок/поставщиков для отображения кнопками

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for MarkdownV2."""
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

def build_client_selection_keyboard_for_return(clients: list) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора клиентов для возврата."""
    buttons = []
    for client in clients[:MAX_RESULTS_TO_SHOW]:
        escaped_client_name = escape_markdown_v2(client['name'])
        buttons.append([InlineKeyboardButton(text=escaped_client_name, callback_data=f"select_return_client_{client['client_id']}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_adjustment")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_invoice_selection_keyboard_for_return(invoices: List[UnpaidInvoice]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора накладных для возврата."""
    buttons = []
    for invoice in invoices[:MAX_RESULTS_TO_SHOW]:
        date_str = invoice.confirmation_date.strftime('%d.%m.%Y') if invoice.confirmation_date else "Н/Д"
        button_text = f"№{invoice.invoice_number} ({date_str}) - {invoice.outstanding_balance:.2f}₴"
        buttons.append([
            InlineKeyboardButton(text=escape_markdown_v2(button_text), callback_data=f"select_return_invoice_{invoice.order_id}")
        ])
    buttons.append([InlineKeyboardButton(text="➡️ Оформить без привязки к накладной", callback_data="select_return_invoice_none")])
    buttons.append([InlineKeyboardButton(text="↩️ Выбрать другого клиента", callback_data="select_another_return_client")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_adjustment")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_adjustment_type_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора типа корректировки/возврата."""
    buttons = [
        [InlineKeyboardButton(text="↩️ Возврат от клиента на склад", callback_data="adj_type_return_in")],
        [InlineKeyboardButton(text="⬅️ Возврат поставщику", callback_data="adj_type_return_out")],
        [InlineKeyboardButton(text="➕ Оприходование излишков (инвентаризация)", callback_data="adj_type_adjustment_in")],
        [InlineKeyboardButton(text="➖ Списание недостачи (инвентаризация)", callback_data="adj_type_adjustment_out")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_adjustment")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_products_keyboard_adj(products: List[ProductItem]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора продукта для корректировки/возврата."""
    buttons = []
    for product in products:
        buttons.append([
            InlineKeyboardButton(
                text=escape_markdown_v2(product.name),
                callback_data=f"select_adj_product_{product.product_id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel_adjustment")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_confirm_adjustment_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения корректировки/возврата."""
    buttons = [
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_adjustment")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_adjustment")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_adjustment")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- НОВЫЕ КЛАВИАТУРЫ ДЛЯ ПОСТАВОК И ВОЗВРАТА ПОСТАВЩИКУ ---

def build_date_selection_keyboard(current_date: date) -> InlineKeyboardMarkup:
    """Строит инлайн-клавиатуру для выбора даты, показывая +/- 7 дней от текущей."""
    buttons = []
    row = []
    for i in range(-7, 8):
        day = current_date + timedelta(days=i)
        row.append(InlineKeyboardButton(text=day.strftime('%d.%m'), callback_data=f"select_new_inv_date_{day.isoformat()}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_new_supplier_invoice")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_supplier_selection_keyboard(suppliers: List[Supplier]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора поставщиков (MAX_RESULTS_TO_SHOW)."""
    buttons = []
    for supplier in suppliers[:MAX_RESULTS_TO_SHOW]:
        buttons.append([InlineKeyboardButton(text=escape_markdown_v2(supplier.name), callback_data=f"select_supplier_{supplier.supplier_id}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_new_supplier_invoice")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_incoming_delivery_selection_keyboard(deliveries: List[IncomingDelivery]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора входящих поставок от поставщика (MAX_RESULTS_TO_SHOW)."""
    buttons = []
    for delivery in deliveries[:MAX_RESULTS_TO_SHOW]:
        date_str = delivery.delivery_date.strftime('%d.%m.%Y') if delivery.delivery_date else "Н/Д"
        button_text = f"Накл\\. №{delivery.invoice_number or 'Без номера'} ({date_str}) - {delivery.total_amount:.2f}₴"
        buttons.append([
            InlineKeyboardButton(text=escape_markdown_v2(button_text), callback_data=f"select_incoming_delivery_{delivery.incoming_delivery_id}")
        ])

    buttons.append([InlineKeyboardButton(text="➡️ Оформить без привязки к поставке", callback_data="select_incoming_delivery_none")])
    buttons.append([InlineKeyboardButton(text="↩️ Выбрать другого поставщика", callback_data="select_another_supplier_return")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_adjustment")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_add_supplier_invoice_item_menu_keyboard(has_items: bool) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить позицию", callback_data="add_new_supplier_invoice_item")],
    ]
    if has_items:
        # TODO: добавить кнопки редактирования/удаления позиций, если нужно
        buttons.append([
            InlineKeyboardButton(text="✅ Завершить накладную", callback_data="finish_new_supplier_invoice_creation")
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_new_supplier_invoice")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Вспомогательная функция для отображения продуктов (для return_in и adjustment_in/out)
async def show_products_for_return_selection(message: Message, state: FSMContext, db_pool):
    products = await get_all_products_for_selection(db_pool)
    if not products:
        await message.answer(escape_markdown_v2("Нет доступных продуктов для выбора."), parse_mode="MarkdownV2")
        await state.clear()
        return

    await message.answer(
        escape_markdown_v2("Выберите продукт:"),
        reply_markup=build_products_keyboard_adj(products),
        parse_mode="MarkdownV2"
    )

async def show_products_for_return_to_supplier_selection(message: Message, state: FSMContext, db_pool):
    """Вспомогательная функция для отображения продуктов для возврата поставщику."""
    products = await get_all_products_for_selection(db_pool)
    if not products:
        await message.answer(escape_markdown_v2("Нет доступных продуктов для выбора."), parse_mode="MarkdownV2")
        await state.clear()
        return

    await message.answer(
        escape_markdown_v2("Выберите продукт:"),
        reply_markup=build_products_keyboard_adj(products),
        parse_mode="MarkdownV2"
    )

def get_supplier_invoice_summary_text(data: Dict[str, Any]) -> str:
    """Формирует сводный текст по новой накладной поставщика."""
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


# --- Хендлеры для корректировок инвентаря ---

@router.message(Command("adjust_inventory"))
async def cmd_adjust_inventory(message: Message, state: FSMContext):
    """Начинает процесс корректировки инвентаря/возврата."""
    await state.clear()
    await message.answer(
        escape_markdown_v2("Выберите тип корректировки/возврата:"),
        reply_markup=build_adjustment_type_keyboard(),
        parse_mode="MarkdownV2"
    )
    await state.set_state(OrderFSM.waiting_for_adjustment_type)

@router.callback_query(F.data.startswith("adj_type_"), StateFilter(OrderFSM.waiting_for_adjustment_type))
async def process_adjustment_type(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    adj_type = callback.data.split("_")[2:]
    movement_type_str = "_".join(adj_type)

    await state.update_data(adjustment_type=movement_type_str)

    if movement_type_str == "return_in": # Возврат от клиента
        await callback.message.edit_text(escape_markdown_v2("Введите имя или название клиента, от которого осуществляется возврат:"), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.waiting_for_return_client_name)
    elif movement_type_str == "return_out": # Возврат поставщику
        await callback.message.edit_text(escape_markdown_v2("Введите имя или название поставщика, которому осуществляется возврат:"), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.waiting_for_supplier_name)
    else: # Оприходование/списание (инвентаризация)
        products = await get_all_products_for_selection(db_pool)
        if not products:
            await callback.message.edit_text(escape_markdown_v2("Нет доступных продуктов для корректировки."), parse_mode="MarkdownV2")
            await state.clear()
            return

        await callback.message.edit_text(
            escape_markdown_v2("Выберите продукт для корректировки:"),
            reply_markup=build_products_keyboard_adj(products),
            parse_mode="MarkdownV2"
        )
        await state.set_state(OrderFSM.waiting_for_return_product) # Это состояние универсально для выбора продукта для всех корректировок


# --- Хендлеры для выбора клиента для возврата --- (Без изменений)
@router.message(StateFilter(OrderFSM.waiting_for_return_client_name))
async def process_return_client_name_input(message: Message, state: FSMContext, db_pool):
    client_name_query = message.text.strip()
    clients = await find_clients_by_name(db_pool, client_name_query)
    
    if clients:
        if len(clients) == 1:
            client = clients[0]
            await state.update_data(adj_client_id=client['client_id'], adj_client_name=client['name'])
            await message.answer(f"✅ Выбран клиент для возврата: *{escape_markdown_v2(client['name'])}*", parse_mode="MarkdownV2")
            
            await message.answer(escape_markdown_v2("Введите номер накладной для возврата (или часть номера), или 'нет', если без накладной:"), parse_mode="MarkdownV2")
            await state.set_state(OrderFSM.waiting_for_return_invoice_number)
        elif 1 < len(clients) <= MAX_RESULTS_TO_SHOW:
            keyboard = build_client_selection_keyboard_for_return(clients)
            await message.answer(escape_markdown_v2("Найдено несколько клиентов. Выберите одного:"), reply_markup=keyboard, parse_mode="MarkdownV2")
        else:
            await message.answer(escape_markdown_v2(f"Найдено слишком много клиентов ({len(clients)}). Пожалуйста, уточните запрос (введите больше символов имени)."), parse_mode="MarkdownV2")
    else:
        await message.answer("Клиент с таким именем не найден. Пожалуйста, попробуйте еще раз или введите другое имя.")

@router.callback_query(StateFilter(OrderFSM.waiting_for_return_client_name), F.data.startswith("select_return_client_"))
async def select_return_client_from_list(callback: CallbackQuery, state: FSMContext, db_pool):
    client_id = int(callback.data.split("_")[3])
    client = await get_client_by_id(db_pool, client_id)
    
    if client:
        await state.update_data(adj_client_id=client['client_id'], adj_client_name=client['name'])
        await callback.message.edit_text(f"✅ Выбран клиент для возврата: *{escape_markdown_v2(client['name'])}*", parse_mode="MarkdownV2", reply_markup=None)
        
        await callback.message.answer(escape_markdown_v2("Введите номер накладной для возврата (или часть номера), или 'нет', если без накладной:"), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.waiting_for_return_invoice_number)
    else:
        await callback.answer("Ошибка при выборе клиента. Попробуйте снова.", show_alert=True)
    await callback.answer()

@router.callback_query(F.data == "select_another_return_client")
async def select_another_return_client(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(adj_client_id=None, adj_client_name=None)
    await callback.message.edit_text(escape_markdown_v2("Введите имя или название клиента, от которого осуществляется возврат:"), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.waiting_for_return_client_name)


# --- Хендлеры для выбора накладной для возврата --- (Без изменений, кроме имени state_data['found_invoices'])
@router.message(StateFilter(OrderFSM.waiting_for_return_invoice_number))
async def process_return_invoice_number_input(message: Message, state: FSMContext, db_pool):
    invoice_number_query = message.text.strip()
    state_data = await state.get_data()
    client_id = state_data.get('adj_client_id')

    if not client_id:
        await message.answer(escape_markdown_v2("Ошибка: не удалось определить клиента. Начните возврат сначала."), parse_mode="MarkdownV2")
        await state.clear()
        return

    if invoice_number_query.lower() == 'нет':
        await state.update_data(adj_invoice_id=None, adj_invoice_number=None)
        await message.answer(escape_markdown_v2("Возврат будет оформлен без привязки к конкретной накладной."), parse_mode="MarkdownV2")
        await message.answer(escape_markdown_v2("Теперь выберите продукт для возврата:"), parse_mode="MarkdownV2")
        await show_products_for_return_selection(message, state, db_pool)
        await state.set_state(OrderFSM.waiting_for_return_product)
        return

    all_client_invoices = await get_client_outstanding_invoices(db_pool, client_id)
    
    found_invoices = [
        inv for inv in all_client_invoices 
        if invoice_number_query.lower() in (inv.invoice_number or '').lower()
    ]
    await state.update_data(found_return_invoices=found_invoices) # ИЗМЕНЕНО: Имя ключа

    if not found_invoices:
        await message.answer(escape_markdown_v2("Накладных с таким номером или его частью и задолженностью не найдено. Попробуйте другой номер, или выберите 'Без накладной'."),
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                 [InlineKeyboardButton(text="➡️ Оформить без привязки к накладной", callback_data="select_return_invoice_none")],
                                 [InlineKeyboardButton(text="↩️ Выбрать другого клиента", callback_data="select_another_return_client")],
                                 [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_adjustment")]
                             ]),
                             parse_mode="MarkdownV2")
        return

    if len(found_invoices) == 1:
        invoice = found_invoices[0]
        await state.update_data(adj_invoice_id=invoice.order_id, adj_invoice_number=invoice.invoice_number)
        await message.answer(f"✅ Выбрана накладная: *{escape_markdown_v2(invoice.invoice_number)}*", parse_mode="MarkdownV2")
        
        await message.answer(escape_markdown_v2("Теперь выберите продукт для возврата:"), parse_mode="MarkdownV2")
        await show_products_for_return_selection(message, state, db_pool)
        await state.set_state(OrderFSM.waiting_for_return_product)
    else:
        text_to_send = escape_markdown_v2("Найдено несколько накладных. Выберите одну:")
        
        found_invoices.sort(key=lambda x: x.confirmation_date or date.min, reverse=True)
        keyboard = build_invoice_selection_keyboard_for_return(found_invoices)

        await message.answer(text_to_send, reply_markup=keyboard, parse_mode="MarkdownV2")


@router.callback_query(StateFilter(OrderFSM.waiting_for_return_invoice_number), F.data.startswith("select_return_invoice_"))
async def process_return_invoice_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    invoice_id_str = callback.data.split("_")[3]
    
    if invoice_id_str == "none":
        await state.update_data(adj_invoice_id=None, adj_invoice_number=None)
        await callback.message.edit_text(escape_markdown_v2("Возврат будет оформлен без привязки к конкретной накладной."), parse_mode="MarkdownV2", reply_markup=None)
    else:
        order_id = int(invoice_id_str)
        state_data = await state.get_data()
        found_invoices = state_data.get('found_return_invoices', []) # ИЗМЕНЕНО: Имя ключа
        selected_invoice = next((inv for inv in found_invoices if inv.order_id == order_id), None)
        invoice_number_display = selected_invoice.invoice_number if selected_invoice else "Н/Д"
        
        await state.update_data(adj_invoice_id=order_id, adj_invoice_number=invoice_number_display)
        await callback.message.edit_text(f"✅ Выбрана накладная: *{escape_markdown_v2(invoice_number_display)}*", parse_mode="MarkdownV2", reply_markup=None)
    
    await callback.message.answer(escape_markdown_v2("Теперь выберите продукт для возврата:"), parse_mode="MarkdownV2")
    await show_products_for_return_selection(callback.message, state, db_pool)
    await state.set_state(OrderFSM.waiting_for_return_product)


# --- Хендлеры для выбора продукта для корректировки/возврата (УНИВЕРСАЛЬНЫЕ) ---


@router.callback_query(F.data.startswith("select_adj_product_"), StateFilter(OrderFSM.waiting_for_return_product, OrderFSM.waiting_for_return_to_supplier_product)) # Обновил StateFilter
async def process_adjustment_product(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    product_id = int(callback.data.split("_")[3])
    
    product_info = await get_product_by_id(db_pool, product_id)
    product_name = product_info.name if product_info else "Неизвестный продукт"

    state_data = await state.get_data()
    adj_type = state_data.get('adjustment_type')

    # Проверка для возврата от клиента
    if adj_type == "return_in":
        adj_client_id = state_data.get('adj_client_id')
        adj_invoice_id = state_data.get('adj_invoice_id')

        product_was_sold_to_client = False
        if adj_client_id: # Проверяем, если клиент выбран
            if adj_invoice_id: # Если выбрана конкретная накладная
                conn = None
                try:
                    conn = await db_pool.acquire()
                    check_query = await conn.fetchrow("""
                        SELECT COUNT(*) FROM order_lines WHERE order_id = $1 AND product_id = $2;
                    """, adj_invoice_id, product_id)
                    if check_query and check_query['count'] > 0:
                        product_was_sold_to_client = True
                except Exception as e:
                    logger.error(f"Ошибка при проверке продукта {product_id} в накладной {adj_invoice_id}: {e}")
                finally:
                    if conn: await db_pool.release(conn)
            else: # Если накладная не выбрана, проверяем, был ли продукт продан клиенту когда-либо
                sold_products = await get_products_sold_to_client(db_pool, adj_client_id)
                sold_product_ids = {p['product_id'] for p in sold_products}
                if product_id in sold_product_ids:
                    product_was_sold_to_client = True

        if not product_was_sold_to_client:
            message_text = "⚠️ Внимание: Этот продукт, возможно, не был продан выбранному клиенту"
            if adj_invoice_id:
                message_text += f" или не входит в выбранную накладную №{adj_invoice_id}"
            message_text += ". Вы уверены, что хотите оформить возврат?"

            await callback.message.edit_text(
                escape_markdown_v2(message_text),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Продолжить", callback_data=f"confirm_adj_product_{product_id}")],
                    [InlineKeyboardButton(text="↩️ Выбрать другой продукт", callback_data="select_another_adj_product")],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_adjustment")]
                ]),
                parse_mode="MarkdownV2"
            )
            return
    
    # Проверка для возврата поставщику
    elif adj_type == "return_out":
        adj_supplier_id = state_data.get('adj_supplier_id')
        adj_incoming_delivery_id = state_data.get('adj_incoming_delivery_id')

        product_was_received_from_supplier = False
        if adj_supplier_id: # Проверяем, если поставщик выбран
            conn = None
            try:
                if adj_incoming_delivery_id: # Если выбрана конкретная поставка
                    conn = await db_pool.acquire()
                    check_query = await conn.fetchrow("""
                        SELECT COUNT(*) FROM incoming_deliveries WHERE delivery_id = $1 AND product_id = $2;
                    """, adj_incoming_delivery_id, product_id) # ТЕПЕРЬ incoming_deliveries - это строки
                    if check_query and check_query['count'] > 0:
                        product_was_received_from_supplier = True
                else: # Если поставка не выбрана, проверяем, был ли продукт получен от поставщика когда-либо
                    conn = await db_pool.acquire()
                    check_query = await conn.fetchrow("""
                        SELECT COUNT(*) FROM incoming_deliveries id
                        WHERE id.supplier_id = $1 AND id.product_id = $2;
                    """, adj_supplier_id, product_id)
                    if check_query and check_query['count'] > 0:
                        product_was_received_from_supplier = True
            except Exception as e:
                logger.error(f"Ошибка при проверке продукта {product_id} от поставщика {adj_supplier_id}: {e}")
            finally:
                if conn: await db_pool.release(conn)

        if not product_was_received_from_supplier:
            message_text = "⚠️ Внимание: Этот продукт, возможно, не был получен от выбранного поставщика"
            if adj_incoming_delivery_id:
                message_text += f" или не входит в выбранную поставку №{adj_incoming_delivery_id}"
            message_text += ". Вы уверены, что хотите оформить возврат?"

            await callback.message.edit_text(
                escape_markdown_v2(message_text),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Продолжить", callback_data=f"confirm_adj_product_to_supplier_{product_id}")],
                    [InlineKeyboardButton(text="↩️ Выбрать другой продукт", callback_data="select_another_adj_product_to_supplier")],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_adjustment")]
                ]),
                parse_mode="MarkdownV2"
            )
            return

    # Если проверка пройдена или это не возврат, продолжаем
    await state.update_data(adj_product_id=product_id, adj_product_name=product_name)
    
    prompt_text = ""
    if adj_type in ['return_in', 'adjustment_in']:
        prompt_text = "Введите количество, которое *поступило* на склад \\(целое число\\):"
        await state.set_state(OrderFSM.waiting_for_return_quantity) # Универсальное состояние для количества
    elif adj_type in ['return_out', 'adjustment_out']:
        prompt_text = "Введите количество, которое *списывается* со склада \\(целое число\\):"
        await state.set_state(OrderFSM.waiting_for_return_to_supplier_quantity) # Раздельное состояние для количества списания
    
    await callback.message.edit_text(escape_markdown_v2(prompt_text), parse_mode="MarkdownV2")

@router.callback_query(F.data.startswith("confirm_adj_product_"), StateFilter(OrderFSM.waiting_for_return_product))
async def confirm_adj_product(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    product_id = int(callback.data.split("_")[3]) # для 'confirm_adj_product_'
    
    product_info = await get_product_by_id(db_pool, product_id)
    product_name = product_info.name if product_info else "Неизвестный продукт"
    
    await state.update_data(adj_product_id=product_id, adj_product_name=product_name)
    
    state_data = await state.get_data()
    adj_type = state_data.get('adjustment_type')

    prompt_text = ""
    if adj_type in ['return_in', 'adjustment_in']:
        prompt_text = "Введите количество, которое *поступило* на склад \\(целое число\\):"
        await state.set_state(OrderFSM.waiting_for_return_quantity)
    elif adj_type in ['return_out', 'adjustment_out']:
        prompt_text = "Введите количество, которое *списывается* со склада \\(целое число\\):"
        await state.set_state(OrderFSM.waiting_for_return_to_supplier_quantity) # Раздельное состояние для количества списания
    
    await callback.message.edit_text(escape_markdown_v2(prompt_text), parse_mode="MarkdownV2")

@router.callback_query(F.data == "select_another_adj_product", StateFilter(OrderFSM.waiting_for_return_product))
async def select_another_adj_product(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    await show_products_for_return_selection(callback.message, state, db_pool)


@router.message(StateFilter(OrderFSM.waiting_for_return_quantity))
async def process_return_quantity(message: Message, state: FSMContext):
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            await message.answer(escape_markdown_v2("Количество должно быть положительным целым числом."), parse_mode="MarkdownV2")
            return

        await state.update_data(adj_quantity=quantity)
        await message.answer(escape_markdown_v2("Введите краткое описание / причину корректировки:"), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.waiting_for_return_description)
    except ValueError:
        await message.answer(escape_markdown_v2("Неверный формат количества. Пожалуйста, введите целое число."), parse_mode="MarkdownV2")


# --- Хендлеры для возврата поставщику (Количество, Описание, Подтверждение) ---
@router.callback_query(F.data.startswith("confirm_adj_product_to_supplier_"), StateFilter(OrderFSM.waiting_for_return_to_supplier_product))
async def confirm_adj_product_to_supplier(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    product_id = int(callback.data.split("_")[4])
    
    product_info = await get_product_by_id(db_pool, product_id)
    product_name = product_info.name if product_info else "Неизвестный продукт"
    
    await state.update_data(adj_product_id=product_id, adj_product_name=product_name)
    
    prompt_text = "Введите количество, которое *возвращается* поставщику \\(целое число\\):"
    
    await callback.message.edit_text(escape_markdown_v2(prompt_text), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.waiting_for_return_to_supplier_quantity)

@router.callback_query(F.data == "select_another_adj_product_to_supplier", StateFilter(OrderFSM.waiting_for_return_to_supplier_product))
async def select_another_adj_product_to_supplier(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    await show_products_for_return_to_supplier_selection(callback.message, state, db_pool)

@router.message(StateFilter(OrderFSM.waiting_for_return_to_supplier_quantity))
async def process_return_to_supplier_quantity(message: Message, state: FSMContext):
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            await message.answer(escape_markdown_v2("Количество должно быть положительным целым числом."), parse_mode="MarkdownV2")
            return

        await state.update_data(adj_quantity=quantity)
        await message.answer(escape_markdown_v2("Введите краткое описание / причину возврата поставщику:"), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.waiting_for_return_to_supplier_description)
    except ValueError:
        await message.answer(escape_markdown_v2("Неверный формат количества. Пожалуйста, введите целое число."), parse_mode="MarkdownV2")

@router.message(StateFilter(OrderFSM.waiting_for_return_to_supplier_description))
async def process_return_to_supplier_description(message: Message, state: FSMContext, db_pool):
    description = message.text.strip()
    await state.update_data(adj_description=description)

    data = await state.get_data()
    adj_type = data['adjustment_type']
    product_id = data['adj_product_id']
    quantity = data['adj_quantity']
    description = data['adj_description']
    product_name = data.get('adj_product_name', "Неизвестный продукт")
    supplier_name = data.get('adj_supplier_name', "Не указан")
    incoming_delivery_id = data.get('adj_incoming_delivery_id')
    incoming_delivery_number = data.get('adj_incoming_delivery_number', "Не указана")

    delivery_info_display = ""
    if incoming_delivery_id:
        delivery_info_display = f"Поставка: *{escape_markdown_v2(incoming_delivery_number)}*\n"

    summary_text = (
        f"📋 *Сводка возврата поставщику:*\n"
        f"Тип: `{escape_markdown_v2(adj_type)}`\n"
        f"Поставщик: *{escape_markdown_v2(supplier_name)}*\n"
    )
    if delivery_info_display:
        summary_text += delivery_info_display
    
    summary_text += (
        f"Продукт: *{escape_markdown_v2(product_name)}*\n"
        f"Количество: `{quantity}` ед\\.\n"
        f"Причина: {escape_markdown_v2(description)}\n\n"
        f"Все верно?"
    )
    
    await message.answer(
        summary_text,
        reply_markup=build_confirm_adjustment_keyboard(),
        parse_mode="MarkdownV2"
    )
    await state.set_state(OrderFSM.confirm_return_to_supplier_data)

@router.callback_query(F.data == "confirm_adjustment", StateFilter(OrderFSM.confirm_return_data, OrderFSM.confirm_return_to_supplier_data))
async def confirm_and_record_adjustment(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    data = await state.get_data()
    adj_type = data['adjustment_type']
    product_id = data['adj_product_id']
    quantity = data['adj_quantity']
    description = data['adj_description']
    
    final_message = ""
    success_stock_movement = False

    # --- ЛОГИКА ДЛЯ ВОЗВРАТА ОТ КЛИЕНТА ИЛИ КОРРЕКТИРОВОК ---
    if adj_type in ["return_in", "adjustment_in", "adjustment_out"]:
        client_id = data.get('adj_client_id')
        invoice_id = data.get('adj_invoice_id')
        
        unit_cost_for_movement = None
        selling_price_for_return = None
        conn = None
        try:
            conn = await db_pool.acquire()
            product_info = await conn.fetchrow("SELECT cost_per_unit, price FROM products WHERE product_id = $1", product_id)
            if product_info:
                unit_cost_for_movement = product_info['cost_per_unit']
                selling_price_for_return = product_info['price'] 
            else:
                logger.error(f"Не удалось получить cost_per_unit/price для продукта ID {product_id} при подтверждении корректировки.")
                final_message += escape_markdown_v2("❌ Ошибка: Не удалось определить себестоимость/цену продукта. Отмена.\\n")
                await callback.message.edit_text(final_message, parse_mode="MarkdownV2")
                await state.clear()
                return
        except Exception as e:
            logger.error(f"Ошибка БД при получении cost_per_unit/price: {e}", exc_info=True)
            final_message += escape_markdown_v2("❌ Произошла ошибка БД при подтверждении. Отмена.\\n")
            await callback.message.edit_text(final_message, parse_mode="MarkdownV2")
            await state.clear()
            return
        finally:
            if conn: await db_pool.release(conn)

        source_doc_type = 'adjustment'
        source_doc_id = None
        if adj_type == "return_in":
            source_doc_type = 'return'
            source_doc_id = invoice_id

        success_stock_movement = await record_stock_movement(
            db_pool=db_pool,
            product_id=product_id,
            quantity=quantity,
            movement_type=adj_type,
            source_document_type=source_doc_type,
            source_document_id=source_doc_id,
            unit_cost=unit_cost_for_movement,
            description=description
        )

        if success_stock_movement:
            final_message += escape_markdown_v2("✅ Корректировка/Возврат на склад успешно записан!\n")
            
            if adj_type == "return_in" and invoice_id and client_id:
                conn = None
                try:
                    conn = await db_pool.acquire()
                    async with conn.transaction():
                        return_amount_value = quantity * selling_price_for_return
                        
                        invoice_info = await conn.fetchrow("SELECT total_amount, amount_paid, payment_status FROM orders WHERE order_id = $1 FOR UPDATE;", invoice_id)
                        if invoice_info:
                            current_total_amount = invoice_info['total_amount']
                            current_amount_paid = invoice_info['amount_paid']
                            
                            new_amount_paid = current_amount_paid - return_amount_value
                            if new_amount_paid < 0:
                                new_amount_paid = Decimal('0.00') 
                            
                            new_payment_status = invoice_info['payment_status']
                            if new_amount_paid < current_total_amount:
                                if new_amount_paid == 0:
                                    new_payment_status = 'unpaid'
                                else:
                                    new_payment_status = 'partially_paid'
                            elif new_amount_paid >= current_total_amount:
                                new_payment_status = 'paid'
                            
                            await conn.execute("""
                                UPDATE orders
                                SET amount_paid = $1, payment_status = $2
                                WHERE order_id = $3;
                            """, new_amount_paid, new_payment_status, invoice_id)

                            await conn.execute("""
                                INSERT INTO client_payments (payment_date, client_id, order_id, amount, payment_method, description)
                                VALUES ($1, $2, $3, $4, $5, $6);
                            """, date.today(), client_id, invoice_id, -return_amount_value, 'return_credit', f"Возврат товара по накладной {data.get('adj_invoice_number', '')}: {description}")
                            
                            final_message += escape_markdown_v2(f"✅ Задолженность по накладной *{data.get('adj_invoice_number', '')}* уменьшена на *{return_amount_value:.2f}* грн\\. Новый статус оплаты: *{new_payment_status}*\\.\n")
                            logger.info(f"Задолженность клиента {client_id} по накладной {invoice_id} уменьшена на {return_amount_value}.")

                        else:
                            final_message += escape_markdown_v2("⚠️ Не удалось найти накладную для обновления задолженности\\. Проверьте ID накладной\\.\n")
                            logger.warning(f"Накладная {invoice_id} не найдена для уменьшения задолженности.")

                except Exception as e:
                    final_message += escape_markdown_v2("❌ Ошибка при уменьшении дебиторской задолженности\\. Обратитесь к админу\\.\n")
                    logger.error(f"Ошибка при уменьшении дебиторской задолженности для клиента {client_id}, накладная {invoice_id}: {e}", exc_info=True)
                finally:
                    if conn: await db_pool.release(conn)
            
        else:
            final_message += escape_markdown_v2("❌ Произошла ошибка при записи корректировки/возврата на склад\\.\n")

    # --- ЛОГИКА ДЛЯ ВОЗВРАТА ПОСТАВЩИКУ ---
    elif adj_type == "return_out":
        supplier_id = data.get('adj_supplier_id')
        incoming_delivery_id = data.get('adj_incoming_delivery_id')

        unit_cost_for_return = None
        conn = None
        try:
            conn = await db_pool.acquire()
            # Пытаемся получить себестоимость из строки поступления, если привязана
            if incoming_delivery_id:
                product_line_info = await conn.fetchrow("""
                    SELECT unit_cost FROM incoming_deliveries -- Теперь это таблица строк
                    WHERE delivery_id = $1 AND product_id = $2;
                """, incoming_delivery_id, product_id)
                if product_line_info:
                    unit_cost_for_return = product_line_info['unit_cost']
            
            # Если не нашли в конкретной строке или строка не выбрана, берем из master-данных продукта
            if not unit_cost_for_return:
                product_info = await conn.fetchrow("SELECT cost_per_unit FROM products WHERE product_id = $1", product_id)
                if product_info:
                    unit_cost_for_return = product_info['cost_per_unit']
            
            if not unit_cost_for_return:
                logger.error(f"Не удалось получить себестоимость для продукта ID {product_id} при возврате поставщику.")
                final_message += escape_markdown_v2("❌ Ошибка: Не удалось определить себестоимость продукта для возврата. Отмена.\\n")
                await callback.message.edit_text(final_message, parse_mode="MarkdownV2")
                await state.clear()
                return
        except Exception as e:
            logger.error(f"Ошибка БД при получении себестоимости для возврата поставщику: {e}", exc_info=True)
            final_message += escape_markdown_v2("❌ Произошла ошибка БД при подтверждении возврата поставщику. Отмена.\\n")
            await callback.message.edit_text(final_message, parse_mode="MarkdownV2")
            await state.clear()
            return
        finally:
            if conn: await db_pool.release(conn)

        success_stock_movement = await record_stock_movement(
            db_pool=db_pool,
            product_id=product_id,
            quantity=quantity,
            movement_type='outgoing', # Всегда 'outgoing' для возврата поставщику
            source_document_type='return_to_supplier',
            source_document_id=incoming_delivery_id, # Используем ID строки поставки
            unit_cost=unit_cost_for_return,
            description=description
        )

        if success_stock_movement:
            final_message += escape_markdown_v2("✅ Возврат товара поставщику (склад) успешно записан!\n")
            
            if supplier_id:
                return_amount_value = quantity * unit_cost_for_return # Сумма, на которую уменьшается долг
                payment_method = 'return_credit' 
                supplier_invoice_id = data.get('adj_supplier_invoice_id') # Получаем ID шапки накладной поставщика

                success_supplier_payment = await record_supplier_payment_or_return(
                    db_pool=db_pool,
                    supplier_id=supplier_id,
                    amount=-return_amount_value, # Отрицательная сумма
                    payment_method=payment_method,
                    description=f"Возврат товара поставщику по поставке {data.get('adj_incoming_delivery_number', '')}: {description}",
                    incoming_delivery_id=incoming_delivery_id,
                    supplier_invoice_id=supplier_invoice_id # Передаем ID шапки
                )

                if success_supplier_payment:
                    final_message += escape_markdown_v2(f"✅ Задолженность перед поставщиком *{data.get('adj_supplier_name', '')}* по накладной *{data.get('adj_incoming_delivery_number', '')}* уменьшена на *{return_amount_value:.2f}* грн\\.\n")
                    logger.info(f"Задолженность перед поставщиком {supplier_id} по поставке {incoming_delivery_id} уменьшена на {return_amount_value}.")
                else:
                    final_message += escape_markdown_v2("❌ Ошибка при уменьшении задолженности перед поставщиком\\. Обратитесь к админу\\.\n")
                    logger.error(f"Ошибка при уменьшении задолженности перед поставщиком {supplier_id}, поставка {incoming_delivery_id}.")
            else:
                final_message += escape_markdown_v2("⚠️ Не удалось определить поставщика для обновления задолженности\\. Проверьте данные\\.\n")
                logger.warning("Поставщик не определен для записи возврата в supplier_payments.")

        else:
            final_message += escape_markdown_v2("❌ Произошла ошибка при записи возврата товара поставщику на склад\\.\n")
    
    await callback.message.edit_text(final_message, parse_mode="MarkdownV2")
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "edit_adjustment", StateFilter(OrderFSM.confirm_return_data, OrderFSM.confirm_return_to_supplier_data))
async def edit_adjustment_data(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    await cmd_adjust_inventory(callback.message, state)

@router.callback_query(F.data == "cancel_adjustment")
async def cancel_adjustment(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(escape_markdown_v2("Операция корректировки отменена."), parse_mode="MarkdownV2")
    await callback.answer()

# --- НОВЫЕ ХЕНДЛЕРЫ ДЛЯ ДОБАВЛЕНИЯ ПОСТУПЛЕНИЯ ТОВАРА (НОВАЯ ФУНКЦИЯ) ---
# Эта логика будет в handlers/reports/add_delivery_handler.py,
# но поскольку мы сейчас работаем в adjustment_handler.py, я даю здесь для контекста.
# Вам нужно будет перенести ее в add_delivery_handler.py

# @router.message(Command("add_delivery"))
# async def cmd_add_delivery(message: Message, state: FSMContext):
#     """Начинает процесс добавления новой накладной поставщика."""
#     await state.clear()
#     await state.update_data(new_supplier_invoice_items=[]) # Инициализируем позиции накладной
    
#     current_date = date.today()
#     keyboard = build_date_selection_keyboard(current_date)
#     await message.answer(escape_markdown_v2("Выберите дату накладной поставщика:"), reply_markup=keyboard, parse_mode="MarkdownV2")
#     await state.set_state(OrderFSM.waiting_for_new_supplier_invoice_date)

# @router.callback_query(F.data.startswith("select_new_inv_date_"), OrderFSM.waiting_for_new_supplier_invoice_date)
# async def process_new_supplier_invoice_date_selection(callback: CallbackQuery, state: FSMContext, db_pool):
#     await callback.answer()
#     selected_date_str = callback.data.split("_")[4]
#     invoice_date = date.fromisoformat(selected_date_str)
#     await state.update_data(new_supplier_invoice_date=invoice_date)

#     suppliers = await find_suppliers_by_name(db_pool, "") # Получаем всех поставщиков
#     if not suppliers:
#         await callback.message.edit_text(escape_markdown_v2("Нет доступных поставщиков. Пожалуйста, добавьте их в базу данных."), parse_mode="MarkdownV2")
#         await state.clear()
#         return

#     keyboard = build_supplier_selection_keyboard(suppliers)
#     await callback.message.edit_text(escape_markdown_v2("Выберите поставщика накладной:"), reply_markup=keyboard, parse_mode="MarkdownV2")
#     await state.set_state(OrderFSM.waiting_for_new_supplier_invoice_supplier)

# # ... (и так далее для остальных шагов создания накладной поставщика)