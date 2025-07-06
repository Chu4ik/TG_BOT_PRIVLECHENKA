# handlers/order_confirmation_report.py

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Optional, List, Dict # Убедитесь, что все импорты на месте

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

# Импортируем все необходимое из db_operations/report_order_confirmation
from db_operations.report_order_confirmation import (
    get_unconfirmed_orders,
    confirm_order_in_db,
    cancel_order_in_db,
    confirm_all_orders_in_db,
    cancel_all_orders_in_db,
    get_unconfirmed_order_full_details, # Новая функция для деталей
    UnconfirmedOrder, # Используем namedtuple для сводки
    OrderDetail # Используем namedtuple для деталей товаров
)

# keyboards.inline_keyboards - пока не используем, но оставим импорт
# Если create_confirm_report_keyboard создавала бы кнопки для индивидуального просмотра,
# мы бы ее переписали. Пока будем генерировать клавиатуру прямо здесь.
# from keyboards.inline_keyboards import create_confirm_report_keyboard


router = Router()
logger = logging.getLogger(__name__)

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for MarkdownV2."""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)

def build_order_list_keyboard(orders: List[UnconfirmedOrder]) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру со списком неподтвержденных заказов.
    Каждая кнопка ведет на детали конкретного заказа.
    Также добавляет кнопки массовых действий.
    """
    buttons = []
    
    # Кнопки для просмотра индивидуальных заказов
    for order in orders:
        escaped_client_name = escape_markdown_v2(order.client_name)
        buttons.append([
            InlineKeyboardButton(
                text=f"Заказ №{order.order_id} ({escaped_client_name}) - {order.total_amount:.2f}₴",
                callback_data=f"view_unconfirmed_order_details_{order.order_id}" # Изменили callback_data
            )
        ])
    
    # Кнопки массовых действий, если есть заказы
    if orders:
        buttons.append([InlineKeyboardButton(text="✅ Подтвердить все заказы", callback_data="confirm_all_orders")])
        buttons.append([InlineKeyboardButton(text="❌ Отменить все заказы", callback_data="cancel_all_orders")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(F.text == "/show_unconfirmed_orders")
@router.callback_query(F.data == "show_unconfirmed_orders_report_list") # Изменили callback_data для возврата к списку
async def show_unconfirmed_orders_report(callback_or_message, state: FSMContext, db_pool):
    """
    Показывает отчет о неподтвержденных заказах за сегодняшний день в виде кнопок.
    """
    message_object: Message | None = None
    is_callback = isinstance(callback_or_message, CallbackQuery)

    if is_callback:
        await callback_or_message.answer()
        message_object = callback_or_message.message
    else:
        message_object = callback_or_message

    if message_object is None:
        logger.error("Не удалось получить объект сообщения из 'callback_or_message'.")
        if is_callback and callback_or_message.message:
            await callback_or_message.message.answer("Произошла ошибка при отображении отчета. Пожалуйста, попробуйте еще раз.")
        elif isinstance(callback_or_message, Message):
            await callback_or_message.answer("Произошла ошибка при отображении отчета. Пожалуйста, попробуйте еще раз.")
        return

    logger.info("Показ отчета о неподтвержденных заказов.")
    
    unconfirmed_orders = await get_unconfirmed_orders(db_pool)

    if not unconfirmed_orders:
        report_text = escape_markdown_v2("На сегодня нет неподтвержденных заказов.")
        
        # Если это колбэк, пытаемся отредактировать предыдущее сообщение
        if is_callback:
            try:
                await message_object.edit_text(report_text, parse_mode="MarkdownV2")
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение для пустого отчета (вероятно, сообщение слишком старое): {e}")
                await message_object.answer(report_text, parse_mode="MarkdownV2")
        else:
            await message_object.answer(report_text, parse_mode="MarkdownV2")
        return

    initial_text = escape_markdown_v2("Выберите неподтвержденный заказ для просмотра деталей или выполните массовое действие:")
    keyboard = build_order_list_keyboard(unconfirmed_orders) # Используем нашу новую функцию

    if is_callback:
        try:
            await message_object.edit_text(initial_text, reply_markup=keyboard, parse_mode="MarkdownV2")
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение (вероятно, слишком старое) при возврате к списку: {e}")
            await message_object.answer(initial_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    else:
        await message_object.answer(initial_text, reply_markup=keyboard, parse_mode="MarkdownV2")


@router.callback_query(F.data.startswith("view_unconfirmed_order_details_")) # Изменили F.data
async def view_unconfirmed_order_details(callback: CallbackQuery, state: FSMContext, db_pool):
    """
    Показывает полную сводку по выбранному неподтвержденному заказу и кнопки действий.
    """
    await callback.answer()
    
    order_id = int(callback.data.split("_")[-1])
    logger.info(f"Администратор {callback.from_user.id} запросил детали неподтвержденного заказа №{order_id}.")

    order_details = await get_unconfirmed_order_full_details(db_pool, order_id) # Используем новую функцию

    if not order_details:
        await callback.message.edit_text(escape_markdown_v2(f"❌ Не удалось найти детали для неподтвержденного заказа №{order_id}. Возможно, он уже был обработан или удален."), parse_mode="MarkdownV2")
        return

    # Формируем текст сводки заказа
    summary_lines = []
    summary_lines.append(f"*{escape_markdown_v2(f'Сводка неподтвержденного заказа №{order_details["order_id"]}:')}*\n")
    summary_lines.append(f"Дата заказа: *{escape_markdown_v2(order_details['order_date'].strftime('%d.%m.%Y'))}*")
    summary_lines.append(f"Дата доставки: *{escape_markdown_v2(order_details['delivery_date'].strftime('%d.%m.%Y'))}*")
    summary_lines.append(f"Клиент: *{escape_markdown_v2(order_details['client_name'])}*")
    summary_lines.append(f"Адрес: *{escape_markdown_v2(order_details['address_text'])}*")
    summary_lines.append(f"Статус: *{escape_markdown_v2(order_details['status'])}*")
    summary_lines.append(escape_markdown_v2("--- ТОВАРЫ ---"))

    if order_details["items"]:
        for i, item in enumerate(order_details["items"]):
            item_line = (
                f"{i+1}\\. {escape_markdown_v2(item.product_name)} "
                f"\\({escape_markdown_v2(f'{item.quantity:.2f}')} ед\\. x "
                f"{escape_markdown_v2(f'{item.unit_price:.2f}')} грн\\.\\) \\= "
                f"*{escape_markdown_v2(f'{item.total_item_amount:.2f}')}* грн\\."
            )
            summary_lines.append(item_line)
    else:
        summary_lines.append(escape_markdown_v2("  В этом заказе нет товаров."))

    summary_lines.append(escape_markdown_v2("----------------------------------"))
    summary_lines.append(f"*{escape_markdown_v2(f'ИТОГО: {order_details["total_amount"]:.2f} грн')}*")

    final_summary_text = "\n".join(summary_lines)

    # Кнопки для подтверждения/отмены/назад ДЛЯ ОДНОГО ЗАКАЗА
    action_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить этот заказ", callback_data=f"confirm_single_order_{order_id}"),
            InlineKeyboardButton(text="❌ Отменить этот заказ", callback_data=f"cancel_single_order_{order_id}")
        ],
        [
            InlineKeyboardButton(text="↩️ Назад к списку заказов", callback_data="show_unconfirmed_orders_report_list") # Изменили callback_data
        ]
    ])

    try:
        await callback.message.edit_text(
            final_summary_text,
            parse_mode="MarkdownV2",
            reply_markup=action_keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения с деталями неподтвержденного заказа {order_id}: {e}", exc_info=True)
        await callback.message.answer(escape_markdown_v2("Произошла ошибка при отображении деталей заказа. Пожалуйста, попробуйте снова."), parse_mode="MarkdownV2")

@router.callback_query(F.data.startswith("confirm_single_order_")) # Новый callback для одного заказа
async def handle_confirm_single_order(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    order_id = int(callback.data.split("_")[-1])
    logger.info(f"Администратор {callback.from_user.id} подтверждает один заказ №{order_id}.")

    success = await confirm_order_in_db(db_pool, order_id) # Используем confirm_order_in_db
    if success:
        message_text = escape_markdown_v2(f"✅ Заказ №{order_id} успешно подтвержден.")
    else:
        message_text = escape_markdown_v2(f"❌ Не удалось подтвердить заказ №{order_id}. Возможно, он уже был обработан.")
    
    await callback.message.edit_text(message_text, parse_mode="MarkdownV2")
    # После подтверждения/отмены, обновите отчет
    await show_unconfirmed_orders_report(callback, state, db_pool)


@router.callback_query(F.data.startswith("cancel_single_order_")) # Новый callback для одного заказа
async def handle_cancel_single_order(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    order_id = int(callback.data.split("_")[-1])
    logger.info(f"Администратор {callback.from_user.id} отменяет один заказ №{order_id}.")

    success = await cancel_order_in_db(db_pool, order_id) # Используем cancel_order_in_db
    if success:
        message_text = escape_markdown_v2(f"🗑️ Заказ №{order_id} успешно отменен и удален.")
    else:
        message_text = escape_markdown_v2(f"❌ Не удалось отменить заказ №{order_id}. Возможно, он уже был обработан.")
    
    await callback.message.edit_text(message_text, parse_mode="MarkdownV2")
    # После подтверждения/отмены, обновите отчет
    await show_unconfirmed_orders_report(callback, state, db_pool)


# Существующие обработчики для массовых действий (без изменений, но перепроверим)
@router.callback_query(F.data == "confirm_all_orders")
async def handle_confirm_all_orders(callback: CallbackQuery, state: FSMContext, db_pool):
    """
    Обрабатывает нажатие на кнопку "Подтвердить все заказы".
    """
    orders_to_confirm = await get_unconfirmed_orders(db_pool)
    order_ids = [order.order_id for order in orders_to_confirm] # Теперь order.order_id, так как UnconfirmedOrder - namedtuple

    if not order_ids:
        await callback.answer("Нет заказов для подтверждения.", show_alert=True)
        # Если нет заказов, можно отредактировать сообщение, чтобы оно было актуальным
        try:
            await callback.message.edit_text(escape_markdown_v2("Нет неподтвержденных заказов."), parse_mode="MarkdownV2")
        except Exception:
            pass # Игнорируем ошибку, если сообщение уже исчезло или не может быть отредактировано
        return

    success = await confirm_all_orders_in_db(db_pool, order_ids)
    if success:
        await callback.answer(f"✅ Все {len(order_ids)} заказов успешно подтверждены!", show_alert=False)
        try:
            await callback.message.edit_text(escape_markdown_v2(f"✅ Все {len(order_ids)} неподтвержденных заказов успешно подтверждены!"), parse_mode="MarkdownV2")
        except Exception:
            pass
    else:
        await callback.answer("❌ Произошла ошибка при подтверждении всех заказов.", show_alert=True)
        try:
            await callback.message.edit_text(escape_markdown_v2("❌ Произошла ошибка при подтверждении всех заказов."), parse_mode="MarkdownV2")
        except Exception:
            pass
    
    # После подтверждения/отмены, обновите отчет
    await show_unconfirmed_orders_report(callback, state, db_pool)


@router.callback_query(F.data == "cancel_all_orders")
async def handle_cancel_all_orders(callback: CallbackQuery, state: FSMContext, db_pool):
    """
    Обрабатывает нажатие на кнопку "Отменить все заказы".
    """
    orders_to_cancel = await get_unconfirmed_orders(db_pool)
    order_ids = [order.order_id for order in orders_to_cancel] # Теперь order.order_id

    if not order_ids:
        await callback.answer("Нет заказов для отмены.", show_alert=True)
        try:
            await callback.message.edit_text(escape_markdown_v2("Нет неподтвержденных заказов."), parse_mode="MarkdownV2")
        except Exception:
            pass
        return

    success = await cancel_all_orders_in_db(db_pool, order_ids)
    if success:
        await callback.answer(f"🗑️ Все {len(order_ids)} заказов успешно отменены!", show_alert=False)
        try:
            await callback.message.edit_text(escape_markdown_v2(f"🗑️ Все {len(order_ids)} неподтвержденных заказов успешно отменены и удалены."), parse_mode="MarkdownV2")
        except Exception:
            pass
    else:
        await callback.answer("❌ Произошла ошибка при отмене всех заказов.", show_alert=True)
        try:
            await callback.message.edit_text(escape_markdown_v2("❌ Произошла ошибка при отмене всех заказов."), parse_mode="MarkdownV2")
        except Exception:
            pass
    
    # После подтверждения/отмены, обновите отчет
    await show_unconfirmed_orders_report(callback, state, db_pool)