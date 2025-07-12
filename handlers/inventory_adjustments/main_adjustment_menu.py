# handlers/inventory_adjustments/main_adjustment_menu.py

import logging
import re
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery # <--- Добавьте CallbackQuery сюда
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter

from states.order import OrderFSM
from utils.markdown_utils import escape_markdown_v2

router = Router()
logger = logging.getLogger(__name__)


def build_main_adjustment_type_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора типа корректировки/возврата."""
    buttons = [
        [InlineKeyboardButton(text="↩️ Возврат от клиента на склад", callback_data="adj_type_client_return")],
        [InlineKeyboardButton(text="⬅️ Возврат поставщику", callback_data="adj_type_supplier_return")],
        [InlineKeyboardButton(text="➕ Оприходование излишков (инвентаризация)", callback_data="adj_type_stock_adjustment_in")],
        [InlineKeyboardButton(text="➖ Списание недостачи (инвентаризация)", callback_data="adj_type_stock_adjustment_out")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_any_adjustment_flow")] # Универсальная кнопка отмены
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(Command("adjust_inventory"))
async def cmd_adjust_inventory(message: Message, state: FSMContext):
    """Начинает процесс корректировки инвентаря/возврата, показывая главное меню."""
    await state.clear()
    await message.answer(
        escape_markdown_v2("Выберите тип корректировки/возврата:"),
        reply_markup=build_main_adjustment_type_keyboard(),
        parse_mode="MarkdownV2"
    )
    await state.set_state(OrderFSM.main_adjustment_menu)

@router.callback_query(F.data.startswith("adj_type_"), StateFilter(OrderFSM.main_adjustment_menu))
async def process_main_adjustment_type_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    """Перенаправляет в соответствующий хэндлер в зависимости от выбора типа корректировки."""
    await callback.answer()
    selected_type_raw = callback.data.split("_", 2)[2] # adj_type_client_return -> client_return

    await state.update_data(current_adjustment_type=selected_type_raw) # Сохраняем выбранный тип

    if selected_type_raw == "client_return":
        from handlers.inventory_adjustments.client_returns_handler import start_client_return_flow
        await start_client_return_flow(callback.message, state, db_pool)
    elif selected_type_raw == "supplier_return":
        from handlers.inventory_adjustments.supplier_returns_handler import start_supplier_return_flow
        await start_supplier_return_flow(callback.message, state, db_pool)
    elif selected_type_raw in ["stock_adjustment_in", "stock_adjustment_out"]:
        from handlers.inventory_adjustments.stock_adjustments_handler import start_stock_adjustment_flow
        await start_stock_adjustment_flow(callback.message, state, db_pool)
    else:
        await callback.message.edit_text(escape_markdown_v2("Неизвестный тип корректировки. Пожалуйста, попробуйте снова."), parse_mode="MarkdownV2")
        await state.clear()

@router.callback_query(F.data == "cancel_any_adjustment_flow")
async def cancel_any_adjustment_flow(callback: CallbackQuery, state: FSMContext):
    """Универсальная кнопка отмены для всего процесса корректировок."""
    await state.clear()
    await callback.message.edit_text(escape_markdown_v2("Операция корректировки отменена."), parse_mode="MarkdownV2")
    await callback.answer()