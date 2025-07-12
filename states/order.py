# states/order.py
from aiogram.fsm.state import State, StatesGroup

class OrderFSM(StatesGroup):
    # --- Состояния для создания/редактирования клиентского заказа ---
    entering_client_name = State()       # Ввод имени/названия клиента для поиска
    selecting_multiple_clients = State() # Выбор клиента из списка, если найдено несколько
    selecting_address = State()          # Выбор адреса доставки для клиента

    selecting_product_category = State() # Выбор категории товара (если есть)
    selecting_product = State()          # Выбор товара из общего списка
    entering_quantity = State()          # Ввод количества выбранного товара
    choosing_next_action = State()       # Выбор следующего действия (добавить еще товар / завершить заказ)

    editing_order = State()              # Основное меню корзины и действий с ней (для нового заказа)
    change_delivery_date = State()       # Изменение даты доставки
    
    editing_item_selection = State()     # Выбор действия (удалить/изменить количество)
    deleting_item = State()              # Выбор товара для удаления
    selecting_item_for_quantity = State() # Выбор товара для изменения количества
    entering_new_quantity = State()      # Ввод нового количества

    confirming_order = State()           # Состояние перед окончательным подтверждением заказа
    
    editing_order_selection_admin = State() # Выбор существующего заказа для админского редактирования
    editing_order_existing = State()       # Администратор редактирует существующий заказ

    # --- Состояния для управления платежами клиентов ---
    viewing_unpaid_invoices_list = State()
    entering_partial_payment_amount = State()

    # --- Состояния для создания НОВОЙ НАКЛАДНОЙ ПОСТАВЩИКА (`/add_delivery`) ---
    waiting_for_new_supplier_invoice_date = State()          # Ввод даты накладной поставщика
    waiting_for_new_supplier_invoice_supplier = State()      # Выбор поставщика для новой накладной
    waiting_for_new_supplier_invoice_number = State()        # Ввод номера накладной поставщика
    waiting_for_new_supplier_invoice_due_date = State()      # Срок оплаты накладной
    adding_new_supplier_invoice_items = State()              # Меню добавления позиций в новую накладную
    waiting_for_new_supplier_invoice_product_selection = State() # Выбор продукта для новой накладной
    waiting_for_new_supplier_invoice_quantity = State()      # Количество для новой накладной
    waiting_for_new_supplier_invoice_unit_cost = State()     # Себестоимость для новой накладной
    confirm_new_supplier_invoice_data = State()              # Подтверждение и создание новой накладной

    # --- Состояния для ОБЩЕГО МЕНЮ КОРРЕКТИРОВОК (`/adjust_inventory`) ---
    main_adjustment_menu = State()          # Главное меню выбора типа корректировки

    # --- Состояния для ВОЗВРАТА ОТ КЛИЕНТА (`/client_return`) ---
    client_return_waiting_for_client_name = State()       # Ввод имени клиента для возврата
    client_return_selecting_client_from_list = State()    # Выбор клиента из списка найденных
    client_return_waiting_for_invoice_number = State()    # Ожидание номера накладной
    client_return_waiting_for_product = State()           # Выбор продукта для возврата
    client_return_waiting_for_quantity = State()          # Ввод количества для возврата
    client_return_waiting_for_description = State()       # Ввод описания/причины
    client_return_confirm_data = State()                  # Подтверждение данных возврата

    # Состояния для возврата поставщику
    supplier_return_waiting_for_supplier_name = State() 
    supplier_return_waiting_for_delivery_selection = State() 
    supplier_return_waiting_for_product = State()         
    supplier_return_waiting_for_quantity = State()        
    supplier_return_waiting_for_description = State()     
    supplier_return_confirm_data = State()

    # --- Состояния для КОРРЕКТИРОВОК ИНВЕНТАРИЗАЦИИ (`/stock_adjustment`) ---
    stock_adjustment_waiting_for_product = State()        # Выбор продукта
    stock_adjustment_waiting_for_quantity = State()       # Ввод количества
    stock_adjustment_waiting_for_description = State()    # Ввод описания/причины
    stock_adjustment_confirm_data = State()               # Подтверждение данных