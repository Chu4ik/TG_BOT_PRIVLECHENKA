# handlers/inventory_adjustments/supplier_returns_handler.py

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional, NamedTuple # Убедитесь, что NamedTuple импортирован
from utils.markdown_utils import escape_markdown_v2

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter # Убедитесь, что StateFilter импортирован

from states.order import OrderFSM # Убедитесь, что OrderFSM импортирован
# ИМПОРТЫ ИЗ db_operations
from db_operations.product_operations import get_all_products_for_selection, ProductItem, record_stock_movement, get_product_by_id
from db_operations.supplier_operations import (
    find_suppliers_by_name, get_supplier_by_id, get_supplier_incoming_deliveries,
    record_supplier_payment_or_return, IncomingDeliveryLine, Supplier, SupplierInvoice
)

router = Router()
logger = logging.getLogger(__name__)

MAX_RESULTS_TO_SHOW = 10 

# --- Клавиатуры ---

def build_supplier_selection_keyboard(suppliers: List[Supplier]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора поставщиков (MAX_RESULTS_TO_SHOW)."""
    buttons = []
    for supplier in suppliers[:MAX_RESULTS_TO_SHOW]:
        buttons.append([InlineKeyboardButton(text=escape_markdown_v2(supplier.name), callback_data=f"select_supplier_return_supplier_{supplier.supplier_id}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_incoming_delivery_selection_keyboard(deliveries: List[IncomingDeliveryLine]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора входящих поставок от поставщика (MAX_RESULTS_TO_SHOW)."""
    buttons = []
    for delivery in deliveries[:MAX_RESULTS_TO_SHOW]:
        date_str = delivery.delivery_date.strftime('%d.%m.%Y') if delivery.delivery_date else "Н/Д"
        button_text = f"Накл\\. №{delivery.invoice_number or 'Без номера'} ({date_str}) - {delivery.total_cost:.2f}₴"
        buttons.append([
            InlineKeyboardButton(text=escape_markdown_v2(button_text), callback_data=f"select_supplier_return_delivery_{delivery.delivery_id}")
        ])

    buttons.append([InlineKeyboardButton(text="➡️ Оформить без привязки к поставке", callback_data="select_supplier_return_delivery_none")])
    buttons.append([InlineKeyboardButton(text="↩️ Выбрать другого поставщика", callback_data="select_another_supplier_return")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_products_keyboard_adj(products: List[ProductItem]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора продукта для корректировки/возврата."""
    buttons = []
    for product in products:
        buttons.append([
            InlineKeyboardButton(
                text=escape_markdown_v2(product.name),
                callback_data=f"select_supplier_return_product_{product.product_id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Отмена", callback_data="cancel_any_adjustment_flow")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_confirm_return_to_supplier_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения возврата поставщику."""
    buttons = [
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_supplier_return")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_supplier_return_data")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Вспомогательные функции для отображения продуктов (ПЕРЕМЕЩЕНО СЮДА) ---

async def show_products_for_supplier_return_selection(message: Message, state: FSMContext, db_pool):
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

# --- Хендлеры для ВОЗВРАТА ПОСТАВЩИКУ ---

async def start_supplier_return_flow(message: Message, state: FSMContext, db_pool):
    """Начинает процесс возврата поставщику."""
    await state.update_data(current_adjustment_type="return_out") # Явно устанавливаем тип
    await message.edit_text(escape_markdown_v2("Введите имя или название поставщика, которому осуществляется возврат:"), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.supplier_return_waiting_for_supplier_name)

@router.message(StateFilter(OrderFSM.supplier_return_waiting_for_supplier_name))
async def process_supplier_return_supplier_name_input(message: Message, state: FSMContext, db_pool):
    supplier_name_query = message.text.strip()
    suppliers = await find_suppliers_by_name(db_pool, supplier_name_query)

    if suppliers:
        if len(suppliers) == 1:
            supplier = suppliers[0]
            await state.update_data(adj_supplier_id=supplier.supplier_id, adj_supplier_name=supplier.name)
            await message.answer(f"✅ Выбран поставщик для возврата: *{escape_markdown_v2(supplier.name)}*", parse_mode="MarkdownV2")
            
            await message.answer(escape_markdown_v2("Введите номер поставки для возврата (или часть номера), или 'нет', если без привязки к поставке:"), parse_mode="MarkdownV2")
            await state.set_state(OrderFSM.supplier_return_waiting_for_delivery_selection)
        elif 1 < len(suppliers) <= MAX_RESULTS_TO_SHOW:
            keyboard = build_supplier_selection_keyboard(suppliers)
            await message.answer(escape_markdown_v2("Найдено несколько поставщиков. Выберите одного:"), reply_markup=keyboard, parse_mode="MarkdownV2")
        else:
            await message.answer(escape_markdown_v2(f"Найдено слишком много поставщиков ({len(suppliers)}). Пожалуйста, уточните запрос (введите больше символов имени)."), parse_mode="MarkdownV2")
    else:
        await message.answer("Поставщик с таким именем не найден. Пожалуйста, попробуйте еще раз или введите другое имя.")

@router.callback_query(StateFilter(OrderFSM.supplier_return_waiting_for_supplier_name), F.data.startswith("select_supplier_return_supplier_"))
async def select_supplier_for_return_from_list(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    supplier_id = int(callback.data.split("_")[4])
    supplier = await get_supplier_by_id(db_pool, supplier_id)
    
    if supplier:
        await state.update_data(adj_supplier_id=supplier.supplier_id, adj_supplier_name=supplier.name)
        await callback.message.edit_text(f"✅ Выбран поставщик для возврата: *{escape_markdown_v2(supplier.name)}*", parse_mode="MarkdownV2", reply_markup=None)
        
        await callback.message.answer(escape_markdown_v2("Введите номер поставки для возврата (или часть номера), или 'нет', если без привязки к поставке:"), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.supplier_return_waiting_for_delivery_selection)
    else:
        await callback.answer("Ошибка при выборе поставщика. Попробуйте снова.", show_alert=True)
    await callback.answer()

@router.callback_query(F.data == "select_another_supplier_return")
async def select_another_supplier_return(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(adj_supplier_id=None, adj_supplier_name=None)
    await callback.message.edit_text(escape_markdown_v2("Введите имя или название поставщика, которому осуществляется возврат:"), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.supplier_return_waiting_for_supplier_name)

@router.message(StateFilter(OrderFSM.supplier_return_waiting_for_delivery_selection))
async def process_supplier_return_delivery_input(message: Message, state: FSMContext, db_pool):
    delivery_query = message.text.strip()
    state_data = await state.get_data()
    supplier_id = state_data.get('adj_supplier_id')

    if not supplier_id:
        await message.answer(escape_markdown_v2("Ошибка: не удалось определить поставщика. Начните возврат сначала."), parse_mode="MarkdownV2")
        await state.clear()
        return

    if delivery_query.lower() == 'нет':
        await state.update_data(adj_incoming_delivery_id=None, adj_incoming_delivery_number=None, adj_supplier_invoice_id=None) # Очищаем supplier_invoice_id
        await message.answer(escape_markdown_v2("Возврат будет оформлен без привязки к конкретной поставке."), parse_mode="MarkdownV2")
        
        await message.answer(escape_markdown_v2("Теперь выберите продукт для возврата поставщику:"), parse_mode="MarkdownV2")
        await show_products_for_supplier_return_selection(message, state, db_pool)
        await state.set_state(OrderFSM.supplier_return_waiting_for_product)
        return

    all_supplier_deliveries = await get_supplier_incoming_deliveries(db_pool, supplier_id)

    found_deliveries = [
        d for d in all_supplier_deliveries 
        if delivery_query.lower() in (d.invoice_number or '').lower() or delivery_query.lower() in str(d.delivery_id)
    ]
    await state.update_data(found_supplier_return_deliveries=found_deliveries)

    if not found_deliveries:
        await message.answer(escape_markdown_v2("Поставок с таким номером или его частью не найдено. Попробуйте другой номер, или выберите 'Без привязки к поставке'."),
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                 [InlineKeyboardButton(text="➡️ Оформить без привязки к поставке", callback_data="select_supplier_return_delivery_none")],
                                 [InlineKeyboardButton(text="↩️ Выбрать другого поставщика", callback_data="select_another_supplier_return")],
                                 [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")]
                             ]),
                             parse_mode="MarkdownV2")
        return

    if len(found_deliveries) == 1:
        delivery = found_deliveries[0]
        await state.update_data(adj_incoming_delivery_id=delivery.delivery_id, adj_incoming_delivery_number=delivery.invoice_number, adj_supplier_invoice_id=delivery.supplier_invoice_id)
        await message.answer(f"✅ Выбрана поставка: *{escape_markdown_v2(delivery.invoice_number or str(delivery.delivery_id))}*", parse_mode="MarkdownV2")
        
        await message.answer(escape_markdown_v2("Теперь выберите продукт для возврата поставщику:"), parse_mode="MarkdownV2")
        await show_products_for_supplier_return_selection(message, state, db_pool)
        await state.set_state(OrderFSM.supplier_return_waiting_for_product)
    else:
        text_to_send = escape_markdown_v2("Найдено несколько поставок. Выберите одну:")
        
        found_deliveries.sort(key=lambda x: x.delivery_date, reverse=True)
        keyboard = build_incoming_delivery_selection_keyboard(found_deliveries)

        await message.answer(text_to_send, reply_markup=keyboard, parse_mode="MarkdownV2")

@router.callback_query(StateFilter(OrderFSM.supplier_return_waiting_for_delivery_selection), F.data.startswith("select_supplier_return_delivery_"))
async def process_supplier_return_delivery_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    delivery_id_str = callback.data.split("_")[4]
    
    if delivery_id_str == "none":
        await state.update_data(adj_incoming_delivery_id=None, adj_incoming_delivery_number=None, adj_supplier_invoice_id=None) # Очищаем supplier_invoice_id
        await callback.message.edit_text(escape_markdown_v2("Возврат будет оформлен без привязки к конкретной поставке."), parse_mode="MarkdownV2", reply_markup=None)
    else:
        incoming_delivery_id = int(delivery_id_str)
        state_data = await state.get_data()
        found_deliveries = state_data.get('found_supplier_return_deliveries', [])
        selected_delivery = next((d for d in found_deliveries if d.delivery_id == incoming_delivery_id), None)
        delivery_number_display = selected_delivery.invoice_number if selected_delivery else str(incoming_delivery_id)
        
        await state.update_data(adj_incoming_delivery_id=incoming_delivery_id, adj_incoming_delivery_number=delivery_number_display, adj_supplier_invoice_id=selected_delivery.supplier_invoice_id) # Сохраняем ID шапки накладной
        await callback.message.edit_text(f"✅ Выбрана поставка: *{escape_markdown_v2(delivery_number_display)}*", parse_mode="MarkdownV2", reply_markup=None)
    
    await callback.message.answer(escape_markdown_v2("Теперь выберите продукт для возврата поставщику:"), parse_mode="MarkdownV2")
    await show_products_for_supplier_return_selection(callback.message, state, db_pool)
    await state.set_state(OrderFSM.supplier_return_waiting_for_product)

# --- Хендлеры для выбора продукта для возврата поставщику ---
# Вспомогательная функция show_products_for_supplier_return_selection определена выше
@router.callback_query(F.data.startswith("select_supplier_return_product_"), StateFilter(OrderFSM.supplier_return_waiting_for_product))
async def process_supplier_return_product(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    product_id = int(callback.data.split("_")[4])
    
    product_info = await get_product_by_id(db_pool, product_id)
    product_name = product_info.name if product_info else "Неизвестный продукт"

    state_data = await state.get_data()
    adj_supplier_id = state_data.get('adj_supplier_id')
    adj_incoming_delivery_id = state_data.get('adj_incoming_delivery_id')

    product_was_received_from_supplier = False
    if adj_supplier_id:
        conn = None
        try:
            conn = await db_pool.acquire()
            if adj_incoming_delivery_id:
                check_query = await conn.fetchrow("""
                    SELECT COUNT(*) FROM incoming_deliveries WHERE delivery_id = $1 AND product_id = $2;
                """, adj_incoming_delivery_id, product_id)
                if check_query and check_query['count'] > 0:
                    product_was_received_from_supplier = True
            else:
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
                [InlineKeyboardButton(text="✅ Продолжить", callback_data=f"confirm_supplier_return_product_{product_id}")],
                [InlineKeyboardButton(text="↩️ Выбрать другой продукт", callback_data="select_another_supplier_return_product")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")]
            ]),
            parse_mode="MarkdownV2"
        )
        return
    
    await state.update_data(adj_product_id=product_id, adj_product_name=product_name)
    await callback.message.edit_text(escape_markdown_v2("Введите количество, которое *возвращается* поставщику \\(целое число\\):"), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.supplier_return_waiting_for_quantity)

@router.callback_query(F.data.startswith("confirm_supplier_return_product_"), StateFilter(OrderFSM.supplier_return_waiting_for_product))
async def confirm_supplier_return_product(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    product_id = int(callback.data.split("_")[4])
    
    product_info = await get_product_by_id(db_pool, product_id)
    product_name = product_info.name if product_info else "Неизвестный продукт"
    
    await state.update_data(adj_product_id=product_id, adj_product_name=product_name)
    
    await callback.message.edit_text(escape_markdown_v2("Введите количество, которое *возвращается* поставщику \\(целое число\\):"), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.supplier_return_waiting_for_quantity)

@router.callback_query(F.data == "select_another_supplier_return_product", StateFilter(OrderFSM.supplier_return_waiting_for_product))
async def select_another_supplier_return_product(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    await show_products_for_supplier_return_selection(callback.message, state, db_pool)

@router.message(StateFilter(OrderFSM.supplier_return_waiting_for_quantity))
async def process_supplier_return_quantity(message: Message, state: FSMContext):
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            await message.answer(escape_markdown_v2("Количество должно быть положительным целым числом."), parse_mode="MarkdownV2")
            return

        await state.update_data(adj_quantity=quantity)
        await message.answer(escape_markdown_v2("Введите краткое описание / причину возврата поставщику:"), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.supplier_return_waiting_for_description)
    except ValueError:
        await message.answer(escape_markdown_v2("Неверный формат количества. Пожалуйста, введите целое число."), parse_mode="MarkdownV2")

@router.message(StateFilter(OrderFSM.supplier_return_waiting_for_description))
async def process_supplier_return_description(message: Message, state: FSMContext, db_pool):
    description = message.text.strip()
    await state.update_data(adj_description=description)

    data = await state.get_data()
    adj_type = data['current_adjustment_type']
    product_id = data['adj_product_id']
    quantity = data['adj_quantity']
    description = data['adj_description']
    product_name = data.get('adj_product_name', "Неизвестный продукт")
    supplier_name = data.get('adj_supplier_name', "Не указан")
    incoming_delivery_id = data.get('adj_incoming_delivery_id')
    incoming_delivery_number = data.get('adj_incoming_delivery_number', "Не указана")
    supplier_invoice_id = data.get('adj_supplier_invoice_id')

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
        reply_markup=build_confirm_return_to_supplier_keyboard(),
        parse_mode="MarkdownV2"
    )
    await state.set_state(OrderFSM.supplier_return_confirm_data)

@router.callback_query(F.data == "confirm_supplier_return", StateFilter(OrderFSM.supplier_return_confirm_data))
async def confirm_and_record_supplier_return(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    data = await state.get_data()
    adj_type = data['current_adjustment_type']
    product_id = data['adj_product_id']
    quantity = data['adj_quantity']
    description = data['adj_description']
    supplier_id = data.get('adj_supplier_id')
    incoming_delivery_id = data.get('adj_incoming_delivery_id')
    supplier_invoice_id = data.get('adj_supplier_invoice_id')

    final_message = ""
    success_stock_movement = False

    unit_cost_for_return = None
    conn = None
    try:
        conn = await db_pool.acquire()
        if incoming_delivery_id:
            product_line_info = await conn.fetchrow("""
                SELECT unit_cost FROM incoming_deliveries
                WHERE delivery_id = $1 AND product_id = $2;
            """, incoming_delivery_id, product_id)
            if product_line_info:
                unit_cost_for_return = product_line_info['unit_cost']
        
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
        movement_type='outgoing',
        source_document_type='return_to_supplier',
        source_document_id=incoming_delivery_id,
        unit_cost=unit_cost_for_return,
        description=description
    )

    if success_stock_movement:
        final_message += escape_markdown_v2("✅ Возврат товара поставщику (склад) успешно записан!\n")
        
        if supplier_id:
            return_amount_value = quantity * unit_cost_for_return
            payment_method = 'return_credit' 

            success_supplier_payment, new_payment_status = await record_supplier_payment_or_return(
                pool=db_pool,
                supplier_id=supplier_id,
                amount=-return_amount_value,
                payment_method=payment_method,
                description=f"Возврат товара поставщику по поставке {data.get('adj_incoming_delivery_number', '')}: {description}",
                incoming_delivery_id=incoming_delivery_id,
                supplier_invoice_id=supplier_invoice_id
            )

            if success_supplier_payment:
                status_display = escape_markdown_v2(new_payment_status) if new_payment_status else "Н/Д"
                final_message += escape_markdown_v2(f"✅ Задолженность перед поставщиком *{data.get('adj_supplier_name', '')}* по накладной *{data.get('adj_incoming_delivery_number', '')}* уменьшена на *{return_amount_value:.2f}* грн\\. Новый статус оплаты: *{status_display}*\\.\n")
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

@router.callback_query(F.data == "edit_supplier_return_data", StateFilter(OrderFSM.supplier_return_confirm_data))
async def edit_supplier_return_data(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    await start_supplier_return_flow(callback.message, state, db_pool)