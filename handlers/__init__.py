from .orders.client_selection import router as client_router
from .orders.addresses_selection import router as address_router
from .orders.product_selection import router as product_router
from .orders.order_editor import router as editor_router
from .orders.confirm_order import router as confirm_router
from .main_menu import router as main_menu_router

# Собираем все router-ы в список
order_routers = [
    client_router,
    address_router,
    product_router,
    editor_router,
    confirm_router,
    main_menu_router
]