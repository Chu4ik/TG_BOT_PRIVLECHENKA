from aiogram.fsm.state import State, StatesGroup

class OrderFSM(StatesGroup):
    selecting_client = State()
    client_selected = State()
    selecting_product = State()
    awaiting_quantity = State()
    editing_order = State()
    change_delivery_date = State()
    confirming_order = State()
    editing_product_line = State()
    selecting_address = State()
    choosing_next_action = State()
    

