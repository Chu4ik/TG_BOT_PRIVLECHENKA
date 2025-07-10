# handlers/admin_orders/admin_order_editor.py

import logging
import re
from datetime import date
from decimal import Decimal
from typing import List, Dict, Optional

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

# Импорты из ваших существующих файлов
from db_operations.report_order_confirmation import UnconfirmedOrder # Используется для типизации списка заказов
from db_operations import get_employee_id # Полезно для будущей проверки роли, пока не используем
from states.order import OrderFSM
from handlers.orders.order_editor import show_cart_menu # Используем для отображения корзины редактируемого заказа
from handlers.orders.order_helpers import _get_cart_summary_text # Для сводки заказа

router = Router()
logger = logging.getLogger(__name__)

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for MarkdownV2."""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)

# Временная заглушка для проверки роли (пока не используем, но сохраняем структуру)
async def is_admin(db_pool, telegram_user_id: int) -> bool:
    # Здесь можно будет добавить реальную проверку роли сотрудника
    # Пока всегда возвращаем True для демонстрации функционала
    # conn = None
    # try:
    #     conn = await db_pool.acquire()
    #     employee_role = await conn.fetchval("SELECT role FROM employees WHERE id_telegram = $1", telegram_user_id)
    #     return employee_role == 'admin'
    # except Exception as e:
    #     logger.error(f"Ошибка при проверке роли администратора для {telegram_user_id}: {e}", exc_info=True)
    #     return False
    # finally:
    #     if conn:
    #         await db_pool.release(conn)
    return True # ВРЕМЕННО: ВСЕГДА True, чтобы не блокировать функционал

def build_editable_order_list_keyboard(orders: List[UnconfirmedOrder]) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру со списком заказов в статусе 'draft' или 'confirmed' для редактирования.
    """
    buttons = []
    for order in orders:
        escaped_client_name = escape_markdown_v2(order.client_name)
        buttons.append([
            InlineKeyboardButton(
                text=f"Заказ №{order.order_id} ({escaped_client_name}) - {order.total_amount:.2f}₴",
                callback_data=f"edit_existing_order_{order.order_id}"
            )
        ])
    if orders:
        buttons.append([InlineKeyboardButton(text="↩️ Назад в главное меню", callback_data="back_to_main_menu_from_admin_edit")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("edit_order_admin")) # Новая команда для админов
async def cmd_edit_order_admin(message: Message, state: FSMContext, db_pool):
    """
    Показывает список заказов, доступных для редактирования администратору.
    """
    user_id = message.from_user.id
    # УБРАНА ПРОВЕРКА РОЛИ ВРЕМЕННО: if not await is_admin(db_pool, user_id):
    # УБРАНА ПРОВЕРКА РОЛИ ВРЕМЕННО:     await message.answer(escape_markdown_v2("У вас нет прав для выполнения этой команды."), parse_mode="MarkdownV2")
    # УБРАНА ПРОВЕРКА РОЛИ ВРЕМЕННО:     return

    logger.info(f"Пользователь {user_id} запросил список заказов для редактирования.")
    await state.clear() # Очищаем состояние перед началом редактирования существующего заказа

    conn = None
    try:
        conn = await db_pool.acquire()
        query = """
        SELECT
            o.order_id,
            o.order_date,
            o.delivery_date,
            c.name AS client_name,
            a.address_text,
            o.total_amount
        FROM
            orders o
        JOIN
            clients c ON o.client_id = c.client_id
        JOIN
            addresses a ON o.address_id = a.address_id
        WHERE
            o.status IN ('draft', 'confirmed') -- Заказы, которые можно редактировать
        ORDER BY
            o.order_date DESC, o.order_id DESC;
        """
        rows = await conn.fetch(query)
        editable_orders = [UnconfirmedOrder(**r) for r in rows]

        if not editable_orders:
            report_text = escape_markdown_v2("Нет заказов в статусе 'draft' или 'confirmed' для редактирования.")
            await message.answer(report_text, parse_mode="MarkdownV2")
            return

        initial_text = escape_markdown_v2("Выберите заказ для редактирования:")
        keyboard = build_editable_order_list_keyboard(editable_orders)

        await message.answer(initial_text, reply_markup=keyboard, parse_mode="MarkdownV2")
        await state.set_state(OrderFSM.editing_order_selection_admin) # Новое состояние для админского выбора заказа
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка редактируемых заказов для пользователя {user_id}: {e}", exc_info=True)
        await message.answer(escape_markdown_v2("Произошла ошибка при загрузке заказов для редактирования. Пожалуйста, попробуйте снова."), parse_mode="MarkdownV2")
    finally:
        if conn:
            await db_pool.release(conn)

@router.callback_query(F.data.startswith("edit_existing_order_"), OrderFSM.editing_order_selection_admin)
async def start_editing_existing_order(callback: CallbackQuery, state: FSMContext, db_pool):
    """
    Начинает процесс редактирования существующего заказа.
    Загружает данные заказа в FSM-состояние для последующей работы.
    """
    await callback.answer()
    order_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id

    # УБРАНА ПРОВЕРКА РОЛИ ВРЕМЕННО: if not await is_admin(db_pool, user_id):
    # УБРАНА ПРОВЕРКА РОЛИ ВРЕМЕННО:     await callback.message.edit_text(escape_markdown_v2("У вас нет прав для выполнения этой операции."), parse_mode="MarkdownV2")
    # УБРАНА ПРОВЕРКА РОЛИ ВРЕМЕННО:     return

    logger.info(f"Пользователь {user_id} выбрал заказ №{order_id} для редактирования.")

    conn = None
    try:
        conn = await db_pool.acquire()
        # Получаем данные заказа
        order_details = await conn.fetchrow("""
            SELECT
                o.order_id,
                o.order_date,
                o.delivery_date,
                o.employee_id,
                o.client_id,
                c.name AS client_name,
                o.address_id,
                a.address_text,
                o.total_amount,
                o.status AS original_order_status, -- Получаем статус как original_order_status
                o.invoice_number,
                o.confirmation_date,
                o.payment_status,
                o.amount_paid,
                o.due_date,
                o.actual_payment_date
            FROM
                orders o
            JOIN
                clients c ON o.client_id = c.client_id
            JOIN
                addresses a ON o.address_id = a.address_id
            WHERE
                o.order_id = $1 AND o.status IN ('draft', 'confirmed');
        """, order_id)

        if not order_details:
            await callback.message.edit_text(escape_markdown_v2(f"❌ Заказ №{order_id} не найден или его статус не позволяет редактирование."), parse_mode="MarkdownV2")
            return

        # Получаем строки заказа (товары)
        order_lines = await conn.fetch("""
            SELECT
                ol.product_id,
                p.name AS product_name,
                ol.quantity,
                ol.unit_price
            FROM
                order_lines ol
            JOIN
                products p ON ol.product_id = p.product_id
            WHERE
                ol.order_id = $1;
        """, order_id)

        # Загружаем данные заказа в FSM-состояние
        cart_items_for_fsm = []
        for line in order_lines:
            cart_items_for_fsm.append({
                "product_id": line['product_id'],
                "product_name": line['product_name'],
                "quantity": line['quantity'],
                "price": line['unit_price'] # Используем unit_price как price для удобства
            })

        await state.update_data(
            editing_order_id=order_details['order_id'],
            client_id=order_details['client_id'],
            client_name=order_details['client_name'],
            address_id=order_details['address_id'],
            address_text=order_details['address_text'],
            delivery_date=order_details['delivery_date'],
            cart=cart_items_for_fsm,
            original_order_status=order_details['original_order_status'] # Сохраняем исходный статус
        )
        
        # Теперь показываем корзину, но уже для редактирования существующего заказа
        await show_cart_menu(callback.message, state, db_pool)
        await state.set_state(OrderFSM.editing_order_existing) # Новое состояние для админского редактирования

    except Exception as e:
        logger.error(f"Ошибка при загрузке заказа №{order_id} для редактирования: {e}", exc_info=True)
        await callback.message.edit_text(escape_markdown_v2("Произошла ошибка при загрузке заказа для редактирования. Пожалуйста, попробуйте снова."), parse_mode="MarkdownV2")
    finally:
        if conn:
            await db_pool.release(conn)

@router.callback_query(F.data == "back_to_main_menu_from_admin_edit")
async def back_to_main_menu_from_admin_edit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(escape_markdown_v2("Вы вернулись в главное меню."), parse_mode="MarkdownV2")
    await callback.answer()