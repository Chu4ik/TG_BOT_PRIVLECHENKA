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
    choosing_next_action = State()       # <-- ДОБАВЛЕНО ЭТО СОСТОЯНИЕ: Выбор следующего действия (добавить еще товар / завершить заказ)

    # Состояния для редактирования корзины
    editing_order = State()              # Основное меню корзины и действий с ней
    # editing_item = State()             # Это состояние у нас теперь более детально разбито ниже
    change_delivery_date = State()       # Изменение даты доставки
    
    # Новые состояния для редактирования строки (корректные)
    editing_item_selection = State()     # Выбор действия (удалить/изменить количество)
    deleting_item = State()              # Выбор товара для удаления
    selecting_item_for_quantity = State() # Выбор товара для изменения количества
    entering_new_quantity = State()      # Ввод нового количества

    # Дополнительные состояния (если есть, например, для подтверждения заказа)
    confirming_order = State()           # Состояние перед окончательным подтверждением заказа
    # add_new_address = State()          # Пример: если будет функционал добавления нового адреса

