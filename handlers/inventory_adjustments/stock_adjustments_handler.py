# handlers/inventory_adjustments/stock_adjustments_handler.py

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional
from utils.markdown_utils import escape_markdown_v2

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from states.order import OrderFSM
# ИМПОРТЫ ИЗ db_operations
from db_operations.product_operations import get_all_products_for_selection, ProductItem, record_stock_movement, get_product_by_id

router = Router()
logger = logging.getLogger(__name__)

# --- Клавиатуры ---

def build_products_keyboard_for_adjustment(products: List[ProductItem]) -> InlineKeyboardMarkup:
    """Строит клавиатуру для выбора продукта для инвентаризационной корректировки."""
    buttons = []
    for product in products:
        buttons.append([
            InlineKeyboardButton(
                text=escape_markdown_v2(product.name),
                callback_data=f"select_stock_adj_product_{product.product_id}" # Специфический callback_data
            )
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_confirm_stock_adjustment_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения инвентаризационной корректировки."""
    buttons = [
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_stock_adjustment")], # Специфический callback_data
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_stock_adjustment_data")], # Специфический callback_data
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Хендлеры для КОРРЕКТИРОВОК ИНВЕНТАРИЗАЦИИ ---

async def start_stock_adjustment_flow(message: Message, state: FSMContext, db_pool):
    """Начинает процесс инвентаризационной корректировки (оприходование/списание)."""
    # current_adjustment_type уже установлен в main_adjustment_menu.py
    # await state.update_data(current_adjustment_type="stock_adjustment_in" или "stock_adjustment_out")
    
    products = await get_all_products_for_selection(db_pool)
    if not products:
        await message.edit_text(escape_markdown_v2("Нет доступных продуктов для корректировки."), parse_mode="MarkdownV2")
        await state.clear()
        return

    await message.edit_text(
        escape_markdown_v2("Выберите продукт для корректировки:"),
        reply_markup=build_products_keyboard_for_adjustment(products),
        parse_mode="MarkdownV2"
    )
    await state.set_state(OrderFSM.stock_adjustment_waiting_for_product)

@router.callback_query(F.data.startswith("select_stock_adj_product_"), StateFilter(OrderFSM.stock_adjustment_waiting_for_product))
async def process_stock_adjustment_product_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    """Обрабатывает выбор продукта для инвентаризационной корректировки."""
    await callback.answer()
    product_id = int(callback.data.split("_")[3]) # select_stock_adj_product_ID
    
    product_info = await get_product_by_id(db_pool, product_id)
    product_name = product_info.name if product_info else "Неизвестный продукт"

    await state.update_data(adj_product_id=product_id, adj_product_name=product_name)
    
    state_data = await state.get_data()
    adj_type = state_data.get('current_adjustment_type')

    prompt_text = ""
    if adj_type == "stock_adjustment_in":
        prompt_text = "Введите количество, которое *оприходуется* \\(целое число\\):"
    elif adj_type == "stock_adjustment_out":
        prompt_text = "Введите количество, которое *списывается* \\(целое число\\):"
    
    await callback.message.edit_text(escape_markdown_v2(prompt_text), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.stock_adjustment_waiting_for_quantity)

@router.message(StateFilter(OrderFSM.stock_adjustment_waiting_for_quantity))
async def process_stock_adjustment_quantity(message: Message, state: FSMContext):
    """Обрабатывает введенное количество для инвентаризационной корректировки."""
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            await message.answer(escape_markdown_v2("Количество должно быть положительным целым числом."), parse_mode="MarkdownV2")
            return

        await state.update_data(adj_quantity=quantity)
        await message.answer(escape_markdown_v2("Введите краткое описание / причину корректировки:"), parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.stock_adjustment_waiting_for_description)
    except ValueError:
        await message.answer(escape_markdown_v2("Неверный формат количества. Пожалуйста, введите целое число."), parse_mode="MarkdownV2")

@router.message(StateFilter(OrderFSM.stock_adjustment_waiting_for_description))
async def process_stock_adjustment_description(message: Message, state: FSMContext, db_pool):
    """Обрабатывает описание инвентаризационной корректировки и показывает сводку."""
    description = message.text.strip()
    await state.update_data(adj_description=description)

    data = await state.get_data()
    adj_type = data['current_adjustment_type']
    product_name = data.get('adj_product_name', "Неизвестный продукт")
    quantity = data['adj_quantity']
    description = data['adj_description']

    summary_text = (
        f"📋 *Сводка инвентаризационной корректировки:*\n"
        f"Тип: `{escape_markdown_v2(adj_type)}`\n"
        f"Продукт: *{escape_markdown_v2(product_name)}*\n"
        f"Количество: `{quantity}` ед\\.\n"
        f"Причина: {escape_markdown_v2(description)}\n\n"
        f"Все верно?"
    )
    
    await message.answer(
        summary_text,
        reply_markup=build_confirm_stock_adjustment_keyboard(),
        parse_mode="MarkdownV2"
    )
    await state.set_state(OrderFSM.stock_adjustment_confirm_data)

@router.callback_query(F.data == "confirm_stock_adjustment", StateFilter(OrderFSM.stock_adjustment_confirm_data))
async def confirm_and_record_stock_adjustment(callback: CallbackQuery, state: FSMContext, db_pool):
    """Подтверждает и записывает инвентаризационную корректировку в БД."""
    await callback.answer()
    data = await state.get_data()
    adj_type = data['current_adjustment_type']
    product_id = data['adj_product_id']
    quantity = data['adj_quantity']
    description = data['adj_description']

    unit_cost_for_movement = None
    conn = None
    try:
        conn = await db_pool.acquire()
        # Для корректировок себестоимость берем из мастер-данных продукта
        product_info = await conn.fetchrow("SELECT cost_per_unit FROM products WHERE product_id = $1", product_id)
        if product_info:
            unit_cost_for_movement = product_info['cost_per_unit']
        else:
            logger.error(f"Не удалось получить cost_per_unit для продукта ID {product_id} при инвентаризационной корректировке.")
            await callback.message.edit_text(escape_markdown_v2("❌ Ошибка: Не удалось определить себестоимость продукта. Отмена."), parse_mode="MarkdownV2")
            await state.clear()
            return
    except Exception as e:
        logger.error(f"Ошибка БД при получении cost_per_unit для инвентаризационной корректировки: {e}", exc_info=True)
        await callback.message.edit_text(escape_markdown_v2("❌ Произошла ошибка БД при подтверждении. Отмена."), parse_mode="MarkdownV2")
        await state.clear()
        return
    finally:
        if conn: await db_pool.release(conn)

    source_doc_type = 'inventory_adjustment'
    source_doc_id = None # Инвентаризационные корректировки обычно не привязываются к конкретному ID документа

    success_stock_movement = await record_stock_movement(
        db_pool=db_pool,
        product_id=product_id,
        quantity=quantity,
        movement_type=adj_type, # 'stock_adjustment_in' или 'stock_adjustment_out'
        source_document_type=source_doc_type,
        source_document_id=source_doc_id,
        unit_cost=unit_cost_for_movement,
        description=description
    )

    if success_stock_movement:
        await callback.message.edit_text(escape_markdown_v2(f"✅ Инвентаризационная корректировка ({adj_type}) успешно записана!"), parse_mode="MarkdownV2")
    else:
        await callback.message.edit_text(escape_markdown_v2(f"❌ Произошла ошибка при записи инвентаризационной корректировки ({adj_type})."), parse_mode="MarkdownV2")
    
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "edit_stock_adjustment_data", StateFilter(OrderFSM.stock_adjustment_confirm_data))
async def edit_stock_adjustment_data(callback: CallbackQuery, state: FSMContext, db_pool):
    """Позволяет пользователю изменить введенные данные инвентаризационной корректировки."""
    await callback.answer()
    state_data = await state.get_data()
    adj_type = state_data.get('current_adjustment_type')
    if adj_type:
        # Возвращаемся к выбору продукта
        await start_stock_adjustment_flow(callback.message, state, db_pool)
    else:
        # Если тип почему-то потерян, возвращаемся в главное меню корректировок
        from handlers.inventory_adjustments.main_adjustment_menu import cmd_adjust_inventory
        await cmd_adjust_inventory(callback.message, state)