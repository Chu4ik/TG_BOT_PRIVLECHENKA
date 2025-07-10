# handlers/__init__.py

# handlers/__init__.py

from .orders.client_selection import router as client_router
from .orders.addresses_selection import router as address_router
from .orders.product_selection import router as product_router
from .orders.order_editor import router as editor_router
from .main_menu import router as main_menu_router # <--- Этот импорт вызывает ошибку
from .reports.order_confirmation_report import router as order_confirmation_report_router 
from .reports.my_orders_report import router as my_orders_report_router
from .reports.client_payments_report import router as client_payments_report_router
from .reports.supplier_reports import router as supplier_reports_router
from .reports.inventory_report import router as inventory_report_router 
from .reports.add_delivery_handler import router as add_delivery_handler_router
from .admin_orders.admin_order_editor import router as admin_order_editor_router
from .inventory_adjustments.adjustment_handler import router as adjustment_router

# Собираем все router-ы в список
order_routers = [
    client_router,
    address_router,
    product_router,
    editor_router,
    main_menu_router,
    order_confirmation_report_router, 
    my_orders_report_router,
    client_payments_report_router,
    supplier_reports_router,
    inventory_report_router,    
    add_delivery_handler_router,
    admin_order_editor_router,
    adjustment_router
]
