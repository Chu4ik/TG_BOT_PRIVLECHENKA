# states/order.py
from aiogram.fsm.state import State, StatesGroup

class OrderFSM(StatesGroup):
    # Состояния для выбора клиента и адреса
    entering_client_name = State()       # Ввод имени/названия клиента для поиска
    selecting_multiple_clients = State() # Выбор клиента из списка, если найдено несколько
    selecting_address = State()          # Выбор адреса доставки для клиента

    # Состояния для выбора товара и количества
    selecting_product_category = State() # Выбор категории товара (если есть)
    selecting_product = State()          # Выбор товара из общего списка
    entering_quantity = State()          # Ввод количества выбранного товара
    choosing_next_action = State()       # Выбор следующего действия (добавить еще товар / завершить заказ)

    # Состояния для редактирования корзины
    editing_order = State()              # Основное меню корзины и действий с ней
    change_delivery_date = State()       # Изменение даты доставки
    
    # Новые состояния для редактирования строки (корректные)
    editing_item_selection = State()     # Выбор действия (удалить/изменить количество)
    deleting_item = State()              # Выбор товара для удаления
    selecting_item_for_quantity = State() # Выбор товара для изменения количества
    entering_new_quantity = State()      # Ввод нового количества

    # Дополнительные состояния (если есть, например, для подтверждения заказа)
    confirming_order = State()           # Состояние перед окончательным подтверждением заказа
    viewing_unpaid_invoices_list = State()
    entering_partial_payment_amount = State()

    # --- НОВЫЕ СОСТОЯНИЯ ДЛЯ ДОБАВЛЕНИЯ ПОСТУПЛЕНИЯ ТОВАРА (МНОГОПОЗИЦИОННОЕ) ---
    waiting_for_delivery_date = State()          # Ввод даты поступления
    waiting_for_supplier_selection = State()     # Выбор поставщика
    
    adding_delivery_items = State()              # Меню для добавления/редактирования позиций поступления
    
    waiting_for_delivery_product_selection = State() # Выбор продукта для поступления
    waiting_for_delivery_quantity = State()      # Ввод количества для поступления
    waiting_for_delivery_unit_cost = State()     # Ввод стоимости за единицу для поступления

    editing_delivery_item_selection = State()    # Выбор позиции для редактирования
    editing_delivery_item_action = State()       # Выбор действия (изменить кол-во/цену)
    entering_new_delivery_quantity = State()     # Ввод нового количества для позиции
    entering_new_delivery_unit_cost = State()    # Ввод новой цены для позиции
    confirm_delivery_data = State()              # <--- УБЕДИТЕСЬ, ЧТО ЭТО СОСТОЯНИЕ ПРИСУТСТВУЕТ И НАПИСАНО ПРАВИЛЬНО

