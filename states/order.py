from aiogram.fsm.state import StatesGroup, State

class OrderFSM(StatesGroup):
    # Состояния для выбора клиента и адреса
    entering_client_name = State()       # Ввод имени/названия клиента для поиска
    selecting_multiple_clients = State() # Выбор клиента из списка, если найдено несколько
    selecting_address = State()          # Выбор адреса доставки для клиента

    # Состояния для выбора товара и количества
    selecting_product = State()          # Выбор товара из общего списка
    entering_quantity = State()          # Ввод количества выбранного товара
    choosing_next_action = State()       # Выбор следующего действия (добавить еще товар / завершить заказ)

    # Состояния для редактирования корзины
    editing_order = State()              # Основное меню корзины и действий с ней
    editing_item = State()               # Редактирование конкретной строки товара в корзине (увеличение/уменьшение/удаление)
    change_delivery_date = State()       # Изменение даты доставки

    # Дополнительные состояния (если есть, например, для подтверждения заказа)
    confirming_order = State()           # Состояние перед окончательным подтверждением заказа
    # add_new_address = State() # Пример: если будет функционал добавления нового адреса

