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

        # Состояния для редактирования существующего заказа
    editing_order_selection_admin = State() # Выбор заказа из списка для админа
    editing_order_existing = State()       # Пользователь (админ) редактирует существующий заказ

        # --- НОВЫЕ СОСТОЯНИЯ ДЛЯ КОРРЕКТИРОВОК И ВОЗВРАТОВ ---
    waiting_for_adjustment_type = State()       # Выбор типа корректировки (возврат, списание, оприходование)
    waiting_for_adjustment_product = State()    # Выбор продукта для корректировки
    waiting_for_adjustment_quantity = State()   # Ввод количества для корректировки
    waiting_for_adjustment_description = State()# Ввод описания/причины
    confirm_adjustment_data = State()           # Подтверждение данных корректировки


    # --- Существующие состояния для корректировок и возвратов ---
    waiting_for_adjustment_type = State()       # Выбор типа корректировки (возврат, списание, оприходование)
    # --- Состояния для расширенного возврата от клиента ---
    waiting_for_return_client_name = State()    # Ожидание ввода имени клиента для возврата
    # selecting_return_client_from_list - Это состояние будет удалено/изменено
    waiting_for_return_invoice_number = State() # НОВОЕ СОСТОЯНИЕ: ожидание номера накладной для возврата
    # waiting_for_return_invoice_selection - Это состояние будет удалено/изменено
    waiting_for_return_product = State()        # Выбор продукта для возврата (после выбора клиента и/или накладной)
    waiting_for_return_quantity = State()       # Ввод количества для возврата
    waiting_for_return_description = State()    # Ввод описания/причины возврата
    confirm_return_data = State()               # Подтверждение данных возврата

      # --- СОСТОЯНИЯ ДЛЯ ДОБАВЛЕНИЯ НОВОЙ ПОСТАВКИ (СУПЕР-ПОСТАВКИ) ---
    waiting_for_new_supplier_invoice_date = State() # Дата накладной от поставщика
    waiting_for_new_supplier_invoice_supplier = State() # Выбор поставщика
    waiting_for_new_supplier_invoice_number = State() # Ввод номера накладной
    waiting_for_new_supplier_invoice_due_date = State() # Срок оплаты накладной
    adding_new_supplier_invoice_items = State() # Меню добавления позиций в новую накладную поставщика
    waiting_for_new_supplier_invoice_product_selection = State() # Выбор продукта для новой накладной
    waiting_for_new_supplier_invoice_quantity = State() # Количество для новой накладной
    waiting_for_new_supplier_invoice_unit_cost = State() # Себестоимость для новой накладной
    confirm_new_supplier_invoice_data = State() # Подтверждение и сохранение новой накладной поставщика

    # --- СОСТОЯНИЯ ДЛЯ ВОЗВРАТА ПОСТАВЩИКУ ---
    waiting_for_supplier_name = State() # Ввод имени поставщика для возврата
    waiting_for_incoming_delivery_selection = State() # Выбор конкретной поставки от поставщика
    waiting_for_return_to_supplier_product = State() # Выбор продукта для возврата поставщику
    waiting_for_return_to_supplier_quantity = State()
    waiting_for_return_to_supplier_description = State()
    confirm_return_to_supplier_data = State()
    # --- КОНЕЦ НОВЫХ СОСТОЯНИЙ ---