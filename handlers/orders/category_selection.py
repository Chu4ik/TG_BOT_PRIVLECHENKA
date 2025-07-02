# from aiogram import Router, F
# from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
# from aiogram.fsm.context import FSMContext
# from aiogram.filters import StateFilter
# from states.order import OrderFSM
# from db_operations.db import get_connection
# from handlers.orders.product_selection import show_products  # следующий шаг

# router = Router()

# @router.message(StateFilter(OrderFSM.selecting_category))
# async def show_categories(message: Message, state: FSMContext):
#     conn = get_connection()
#     cur = conn.cursor()
#     cur.execute("SELECT category_id, name FROM categories ORDER BY name")
#     rows = cur.fetchall()
#     cur.close()
#     conn.close()

#     if not rows:
#         await message.answer("❌ В базе нет категорий товаров.")
#         return

#     keyboard = ReplyKeyboardMarkup(resize_keyboard=True).add(
#         *[KeyboardButton(text=row[1]) for row in rows]
#     )

#     # сохраняем id-шки категорий по названию для последующего шага
#     await state.update_data(category_map={row[1]: row[0] for row in rows})
#     await message.answer("📂 Выберите категорию товара:", reply_markup=keyboard)

# @router.message(StateFilter(OrderFSM.selecting_category))
# async def category_chosen(message: Message, state: FSMContext):
#     selected_text = message.text
#     state_data = await state.get_data()
#     category_map = state_data.get("category_map", {})

#     category_id = category_map.get(selected_text)

#     if not category_id:
#         await message.answer("⚠️ Категория не распознана. Пожалуйста, выберите из списка.")
#         return

#     await message.answer(f"✅ Категория выбрана: {selected_text}", reply_markup=ReplyKeyboardRemove())
#     await state.set_state(OrderFSM.selecting_product)
#     await show_products(message, state, category_id)