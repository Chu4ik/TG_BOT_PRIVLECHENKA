# handlers/inventory_adjustments/client_returns_handler.py

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from states.order import OrderFSM
# ИМПОРТЫ ИЗ db_operations
from db_operations.product_operations import get_all_products_for_selection, ProductItem, record_stock_movement, get_product_by_id, get_products_sold_to_client
from db_operations.client_operations import find_clients_by_name, get_client_by_id
from db_operations.report_payment_operations import get_client_outstanding_invoices, UnpaidInvoice, get_order_by_invoice_number
from db_operations.report_payment_operations import confirm_payment_in_db # Пример, если нужно для клиентских платежей
from db_operations.supplier_operations import IncomingDelivery # Используется для типизации в некоторых клавиатурах, но тут не нужна

router = Router()
logger = logging.getLogger(__name__)

MAX_RESULTS_TO_SHOW = 10 # Максимальное количество клиентов/накладных для отображения кнопками

# --- Клавиатуры ---

def build_client_selection_keyboard_for_return(clients: list) -> InlineKeyboardMarkup:
    buttons = []
    for client in clients[:MAX_RESULTS_TO_SHOW]:
        escaped_client_name = escape_markdown_v2(client['name'])
        buttons.append([InlineKeyboardButton(text=escaped_client_name, callback_data=f"select_client_return_client_{client['client_id']}")]) # Изменено callback_data
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")]) # Универсальная отмена
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_invoice_selection_keyboard_for_return(invoices: List[UnpaidInvoice]) -> InlineKeyboardMarkup:
    buttons = []
    for invoice in invoices[:MAX_RESULTS_TO_SHOW]:
        date_str = invoice.confirmation_date.strftime('%d.%m.%Y') if invoice.confirmation_date else "Н/Д"
        button_text = f"№{invoice.invoice_number} ({date_str}) - {invoice.outstanding_balance:.2f}₴"
        buttons.append([
            InlineKeyboardButton(text=escape_markdown_v2(button_text), callback_data=f"select_client_return_invoice_{invoice.order_id}") # Изменено callback_data
        ])
    buttons.append([InlineKeyboardButton(text="➡️ Оформить без привязки к накладной", callback_data="select_client_return_invoice_none")]) # Изменено callback_data
    buttons.append([InlineKeyboardButton(text="↩️ Выбрать другого клиента", callback_data="select_another_client_return")]) # Изменено callback_data
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_products_keyboard_adj(products: List[ProductItem]) -> InlineKeyboardMarkup:
    buttons = []
    for product in products:
        buttons.append([
            InlineKeyboardButton(
                text=escape_markdown_v2(product.name),
                callback_data=f"select_client_return_product_{product.product_id}" # Изменено callback_data
            )
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel_any_adjustment_flow")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_confirm_return_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_client_return")], # Изменено callback_data
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_client_return_data")], # Изменено callback_data
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Хендлеры для ВОЗВРАТА ОТ КЛИЕНТА ---

async def start_client_return_flow(message: Message, state: FSMContext, db_pool):
    """Начинает процесс возврата от клиента."""
    await state.update_data(current_adjustment_type="return_in") # Явно устанавливаем тип
    await message.edit_text(escape_markdown_v2("Введите имя или название клиента, от которого осуществляется возврат:"), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.client_return_waiting_for_client_name)

@router.message(StateFilter(OrderFSM.client_return_waiting_for_client_name))
async def process_client_return_client_name_input(message: Message, state: FSMContext, db_pool):
    client_name_query = message.text.strip()
    clients = await find_clients_by_name(db_pool, client_name_query)
    
    if clients:
        if len(clients) == 1:
            client = clients[0]
            await state.update_data(adj_client_id=client['client_id'], adj_client_name=client['name'])
            await message.answer(f"✅ Выбран клиент для возврата: *{escape_markdown_v2(client['name'])}*", parse_mode="MarkdownV2")
            
            await message.answer(escape_markdown_v2("Введите номер накладной для возврата (или часть номера), или 'нет', если без накладной:"), parse_mode="MarkdownV2")
            await state.set_state(OrderFSM.client_return_waiting_for_invoice_number)
        elif 1 < len(clients) <= MAX_RESULTS_TO_SHOW:
            keyboard = build_client_selection_keyboard_for_return(clients)
            await message.answer(escape_markdown_v2("Найдено несколько клиентов. Выберите одного:"), reply_markup=keyboard, parse_mode="MarkdownV2")
        else:
            await message.answer(escape_markdown_v2(f"Найдено слишком много клиентов ({len(clients)}). Пожалуйста, уточните запрос (введите больше символов имени)."), parse_mode="MarkdownV2")
    else:
        await message.answer("Клиент с таким именем не найден. Пожалуйста, попробуйте еще раз или введите другое имя.")

@router.callback_query(StateFilter(OrderFSM.client_return_waiting_for_client_name), F.data.startswith("select_client_return_client_")) # Изменено F.data
async def select_client_return_client_from_list(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    client_id = int(callback.data.split("_")[4]) # Изменено split индекс
    client = await get_client_by_id(db_pool, client_id)
    
    if client:
        await state.update_data(adj_client_id=client['client_id'], adj_client_name=client['name'])
        await callback.message.edit_text(f"✅ Выбран клиент для возврата: *{escape_markdown_v2(client['name'])}*", parse_mode="MarkdownV2", reply_markup=None)
        
        await callback.message.answer(escape_markdown_v2("Введите номер накладной для возврата (или часть номера), или 'нет', если без накладной:"), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.client_return_waiting_for_invoice_number)
    else:
        await callback.answer("Ошибка при выборе клиента. Попробуйте снова.", show_alert=True)

@router.callback_query(F.data == "select_another_client_return") # Изменено callback_data
async def select_another_client_return(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(adj_client_id=None, adj_client_name=None)
    await callback.message.edit_text(escape_markdown_v2("Введите имя или название клиента, от которого осуществляется возврат:"), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.client_return_waiting_for_client_name)

@router.message(StateFilter(OrderFSM.client_return_waiting_for_invoice_number)) # Изменено StateFilter
async def process_client_return_invoice_number_input(message: Message, state: FSMContext, db_pool):
    invoice_number_query = message.text.strip()
    state_data = await state.get_data()
    client_id = state_data.get('adj_client_id')

    if not client_id:
        await message.answer(escape_markdown_v2("Ошибка: не удалось определить клиента. Начните возврат сначала."), parse_mode="MarkdownV2")
        await state.clear() # Универсальная отмена
        return

    if invoice_number_query.lower() == 'нет':
        await state.update_data(adj_invoice_id=None, adj_invoice_number=None)
        await message.answer(escape_markdown_v2("Возврат будет оформлен без привязки к конкретной накладной."), parse_mode="MarkdownV2")
        
        await message.answer(escape_markdown_v2("Теперь выберите продукт для возврата:"), parse_mode="MarkdownV2")
        await show_products_for_client_return_selection(message, state, db_pool) # Новая функция для выбора продуктов
        await state.set_state(OrderFSM.client_return_waiting_for_product) # Изменено состояние
        return

    all_client_invoices = await get_client_outstanding_invoices(db_pool, client_id)
    
    found_invoices = [
        inv for inv in all_client_invoices 
        if invoice_number_query.lower() in (inv.invoice_number or '').lower()
    ]
    await state.update_data(found_client_return_invoices=found_invoices) # Изменено имя ключа

    if not found_invoices:
        await message.answer(escape_markdown_v2("Накладных с таким номером или его частью и задолженностью не найдено. Попробуйте другой номер, или выберите 'Без накладной'."),
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                 [InlineKeyboardButton(text="➡️ Оформить без привязки к накладной", callback_data="select_client_return_invoice_none")], # Изменено callback_data
                                 [InlineKeyboardButton(text="↩️ Выбрать другого клиента", callback_data="select_another_client_return")],
                                 [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")]
                             ]),
                             parse_mode="MarkdownV2")
        return

    if len(found_invoices) == 1:
        invoice = found_invoices[0]
        await state.update_data(adj_invoice_id=invoice.order_id, adj_invoice_number=invoice.invoice_number)
        await message.answer(f"✅ Выбрана накладная: *{escape_markdown_v2(invoice.invoice_number)}*", parse_mode="MarkdownV2")
        
        await message.answer(escape_markdown_v2("Теперь выберите продукт для возврата:"), parse_mode="MarkdownV2")
        await show_products_for_client_return_selection(message, state, db_pool) # Новая функция для выбора продуктов
        await state.set_state(OrderFSM.client_return_waiting_for_product) # Изменено состояние
    else:
        text_to_send = escape_markdown_v2("Найдено несколько накладных. Выберите одну:")
        
        found_invoices.sort(key=lambda x: x.confirmation_date or date.min, reverse=True)
        keyboard = build_invoice_selection_keyboard_for_return(found_invoices)

        await message.answer(text_to_send, reply_markup=keyboard, parse_mode="MarkdownV2")


@router.callback_query(StateFilter(OrderFSM.client_return_waiting_for_invoice_number), F.data.startswith("select_client_return_invoice_")) # Изменено StateFilter и F.data
async def process_client_return_invoice_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    invoice_id_str = callback.data.split("_")[4] # Изменен индекс
    
    if invoice_id_str == "none":
        await state.update_data(adj_invoice_id=None, adj_invoice_number=None)
        await callback.message.edit_text(escape_markdown_v2("Возврат будет оформлен без привязки к конкретной накладной."), parse_mode="MarkdownV2", reply_markup=None)
    else:
        order_id = int(invoice_id_str)
        state_data = await state.get_data()
        found_invoices = state_data.get('found_client_return_invoices', []) # Изменено имя ключа
        selected_invoice = next((inv for inv in found_invoices if inv.order_id == order_id), None)
        invoice_number_display = selected_invoice.invoice_number if selected_invoice else "Н/Д"
        
        await state.update_data(adj_invoice_id=order_id, adj_invoice_number=invoice_number_display)
        await callback.message.edit_text(f"✅ Выбрана накладная: *{escape_markdown_v2(invoice_number_display)}*", parse_mode="MarkdownV2", reply_markup=None)
    
    await callback.message.answer(escape_markdown_v2("Теперь выберите продукт для возврата:"), parse_mode="MarkdownV2")
    await show_products_for_client_return_selection(callback.message, state, db_pool) # Новая функция
    await state.set_state(OrderFSM.client_return_waiting_for_product) # Изменено состояние


# --- Хендлеры для выбора продукта для возврата клиента ---
async def show_products_for_client_return_selection(message: Message, state: FSMContext, db_pool):
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

@router.callback_query(F.data.startswith("select_client_return_product_"), StateFilter(OrderFSM.client_return_waiting_for_product)) # Изменено F.data и StateFilter
async def process_client_return_product_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    product_id = int(callback.data.split("_")[4]) # Изменено split индекс
    
    product_info = await get_product_by_id(db_pool, product_id)
    product_name = product_info.name if product_info else "Неизвестный продукт"

    state_data = await state.get_data()
    adj_client_id = state_data.get('adj_client_id')
    adj_invoice_id = state_data.get('adj_invoice_id')

    product_was_sold_to_client = False
    if adj_client_id:
        if adj_invoice_id:
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
        else:
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
                [InlineKeyboardButton(text="✅ Продолжить", callback_data=f"confirm_client_return_product_{product_id}")], # Изменено callback_data
                [InlineKeyboardButton(text="↩️ Выбрать другой продукт", callback_data="select_another_client_return_product")], # Изменено callback_data
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")]
            ]),
            parse_mode="MarkdownV2"
        )
        return
    
    await state.update_data(adj_product_id=product_id, adj_product_name=product_name)
    await callback.message.edit_text(escape_markdown_v2("Введите количество, которое *поступило* на склад \\(целое число\\):"), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.client_return_waiting_for_quantity) # Изменено состояние

@router.callback_query(F.data.startswith("confirm_client_return_product_"), StateFilter(OrderFSM.client_return_waiting_for_product)) # Изменено F.data и StateFilter
async def confirm_client_return_product(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    product_id = int(callback.data.split("_")[4]) # Изменено split индекс
    
    product_info = await get_product_by_id(db_pool, product_id)
    product_name = product_info.name if product_info else "Неизвестный продукт"
    
    await state.update_data(adj_product_id=product_id, adj_product_name=product_name)
    
    await callback.message.edit_text(escape_markdown_v2("Введите количество, которое *поступило* на склад \\(целое число\\):"), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.client_return_waiting_for_quantity)

@router.callback_query(F.data == "select_another_client_return_product", StateFilter(OrderFSM.client_return_waiting_for_product)) # Изменено F.data и StateFilter
async def select_another_client_return_product(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    await show_products_for_client_return_selection(callback.message, state, db_pool)

@router.message(StateFilter(OrderFSM.client_return_waiting_for_quantity)) # Изменено StateFilter
async def process_client_return_quantity(message: Message, state: FSMContext):
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            await message.answer(escape_markdown_v2("Количество должно быть положительным целым числом."), parse_mode="MarkdownV2")
            return

        await state.update_data(adj_quantity=quantity)
        await message.answer(escape_markdown_v2("Введите краткое описание / причину возврата:"), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.client_return_waiting_for_description) # Изменено StateFilter
    except ValueError:
        await message.answer(escape_markdown_v2("Неверный формат количества. Пожалуйста, введите целое число."), parse_mode="MarkdownV2")

@router.message(StateFilter(OrderFSM.client_return_waiting_for_description)) # Изменено StateFilter
async def process_client_return_description(message: Message, state: FSMContext, db_pool):
    description = message.text.strip()
    await state.update_data(adj_description=description)

    data = await state.get_data()
    adj_type = data['current_adjustment_type'] # Теперь берем из current_adjustment_type
    product_id = data['adj_product_id']
    quantity = data['adj_quantity']
    description = data['adj_description']
    product_name = data.get('adj_product_name', "Неизвестный продукт")
    client_name = data.get('adj_client_name', "Не указан")
    invoice_id = data.get('adj_invoice_id')
    invoice_number = data.get('adj_invoice_number', "Не указана")

    invoice_info_display = ""
    if adj_type == "client_return" and invoice_id: # Изменено
        invoice_info_display = f"Накладная: *{escape_markdown_v2(invoice_number)}*\n"

    summary_text = (
        f"📋 *Сводка возврата:*\n" # Универсальный заголовок
        f"Тип: `{escape_markdown_v2(adj_type)}`\n"
        f"Продукт: *{escape_markdown_v2(product_name)}*\n"
    )
    if adj_type == "client_return": # Изменено
        summary_text += f"Клиент: *{escape_markdown_v2(client_name)}*\n"
        if invoice_info_display:
            summary_text += invoice_info_display
    
    summary_text += (
        f"Количество: `{quantity}` ед\\.\n"
        f"Причина: {escape_markdown_v2(description)}\n\n"
        f"Все верно?"
    )
    
    await message.answer(
        summary_text,
        reply_markup=build_confirm_return_keyboard(), # Универсальная клавиатура
        parse_mode="MarkdownV2"
    )
    await state.set_state(OrderFSM.client_return_confirm_data) # Изменено StateFilter

@router.callback_query(F.data == "confirm_client_return", StateFilter(OrderFSM.client_return_confirm_data))
async def confirm_and_record_client_return(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    data = await state.get_data()
    adj_type = data['current_adjustment_type']
    product_id = data['adj_product_id']
    quantity = data['adj_quantity']
    description = data['adj_description']
    client_id = data.get('adj_client_id')
    invoice_id = data.get('adj_invoice_id')
    
    final_message_parts = [] # Собираем части сообщения, а потом соединяем
    
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
            logger.error(f"Не удалось получить cost_per_unit/price для продукта ID {product_id} при подтверждении возврата клиента.")
            final_message_parts.append("❌ Ошибка: Не удалось определить себестоимость/цену продукта. Отмена.")
            await callback.message.edit_text(escape_markdown_v2("".join(final_message_parts)), parse_mode="MarkdownV2")
            await state.clear()
            return
    except Exception as e:
        logger.error(f"Ошибка БД при получении cost_per_unit/price для возврата клиента: {e}", exc_info=True)
        final_message_parts.append("❌ Произошла ошибка БД при подтверждении. Отмена.")
        await callback.message.edit_text(escape_markdown_v2("".join(final_message_parts)), parse_mode="MarkdownV2")
        await state.clear()
        return
    finally:
        if conn: await db_pool.release(conn)

    source_doc_type = 'return'
    source_doc_id = invoice_id

    success_stock_movement = await record_stock_movement(
        db_pool=db_pool,
        product_id=product_id,
        quantity=quantity,
        movement_type='return_in',
        source_document_type=source_doc_type,
        source_document_id=source_doc_id,
        unit_cost=unit_cost_for_movement,
        description=description
    )

    if success_stock_movement:
        final_message_parts.append("✅ Возврат на склад успешно записан!\n")
        
        if invoice_id and client_id:
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
                            INSERT INTO client_payments (payment_date, client_id, order_id, amount, payment_method, description, payment_type) -- ДОБАВЛЕН payment_type
                            VALUES ($1, $2, $3, $4, $5, $6, $7);
                        """, date.today(), client_id, invoice_id, -return_amount_value, 'return_credit', f"Возврат товара по накладной {data.get('adj_invoice_number', '')}: {description}", 'return_credit') # ДОБАВЛЕНА 'return_credit
                        
                        final_message_parts.append(f"✅ Задолженность по накладной *{escape_markdown_v2(data.get('adj_invoice_number', ''))}* уменьшена на *{return_amount_value:.2f}* грн\\. Новый статус оплаты: *{escape_markdown_v2(new_payment_status)}*\\.\n")
                        logger.info(f"Задолженность клиента {client_id} по накладной {invoice_id} уменьшена на {return_amount_value}.")

                    else:
                        final_message_parts.append("⚠️ Не удалось найти накладную для обновления задолженности\\. Проверьте ID накладной\\.\n")
                        logger.warning(f"Накладная {invoice_id} не найдена для уменьшения задолженности.")

            except Exception as e:
                final_message_parts.append("❌ Ошибка при уменьшении дебиторской задолженности\\. Обратитесь к админу\\.\n")
                logger.error(f"Ошибка при уменьшении дебиторской задолженности для клиента {client_id}, накладная {invoice_id}: {e}", exc_info=True)
            finally:
                if conn: await db_pool.release(conn)
            
        # else: Эта ветка не нужна, т.к. final_message_parts уже инициализирована
        # final_message_parts.append("❌ Произошла ошибка при записи возврата на склад\\.\n") # Это уже покрыто outer else
    else: # Если success_stock_movement == False
        final_message_parts.append("❌ Произошла ошибка при записи возврата на склад\\.\n")
    
    # --- ИСПРАВЛЕНИЕ: Добавляем запасное сообщение, если final_message_parts пуст ---
    if not final_message_parts:
        final_message_parts.append("⚠️ Операция завершилась, но сообщение не сформировано\\. Проверьте логи\\.")

    await callback.message.edit_text(escape_markdown_v2("".join(final_message_parts)), parse_mode="MarkdownV2")
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "edit_client_return_data", StateFilter(OrderFSM.client_return_confirm_data)) # Изменено F.data и StateFilter
async def edit_client_return_data(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    # Возвращаемся к началу процесса возврата клиента
    await start_client_return_flow(callback.message, state, db_pool)