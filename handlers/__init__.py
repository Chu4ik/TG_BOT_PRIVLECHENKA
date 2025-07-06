from .orders.client_selection import router as client_router
from .orders.addresses_selection import router as address_router
from .orders.product_selection import router as product_router
from .orders.order_editor import router as editor_router
from .main_menu import router as main_menu_router
from .reports.order_confirmation_report import router as order_confirmation_report_router 
from .reports.my_orders_report import router as my_orders_report_router
from .reports.client_payments_report import router as client_payments_report_router

# Собираем все router-ы в список
order_routers = [
    client_router,
    address_router,
    product_router,
    editor_router,
    main_menu_router,
    order_confirmation_report_router, 
    my_orders_report_router,
    client_payments_report_router
]