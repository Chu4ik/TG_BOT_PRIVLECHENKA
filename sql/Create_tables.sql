CREATE TABLE suppliers (
    supplier_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE categories (
    category_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(category_id),
    supplier_id INTEGER REFERENCES suppliers(supplier_id),
    price NUMERIC(10,2)
);

CREATE TABLE clients (
    client_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE addresses (
    address_id SERIAL PRIMARY KEY,
    client_id INTEGER REFERENCES clients(client_id) ON DELETE CASCADE,
    address_text TEXT NOT NULL
);

CREATE TABLE employees (
    employee_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    id_telegram BIGINT UNIQUE NOT NULL
);

CREATE TABLE orders (
    order_id SERIAL PRIMARY KEY,
    invoice_number TEXT UNIQUE,
    order_date DATE NOT NULL,
    delivery_date DATE NOT NULL,
    employee_id INTEGER REFERENCES employees(employee_id),
    client_id INTEGER REFERENCES clients(client_id),
    address_id INTEGER REFERENCES addresses(address_id),
    total_amount NUMERIC(12, 2),
    status TEXT CHECK (status IN ('draft', 'confirmed', 'shipped', 'cancelled'))
);

CREATE TABLE order_lines (
    order_line_id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL,
    line_total NUMERIC(12, 2) GENERATED ALWAYS AS (quantity * unit_price) STORED
);

CREATE TABLE incoming_deliveries (
    delivery_id SERIAL PRIMARY KEY,
    delivery_date DATE NOT NULL,
    supplier_id INTEGER REFERENCES suppliers(supplier_id),
    product_id INTEGER REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    unit_cost NUMERIC(10, 2),
    total_cost NUMERIC(12, 2) GENERATED ALWAYS AS (quantity * unit_cost) STORED
);

CREATE TABLE client_payments (
    payment_id SERIAL PRIMARY KEY,
    payment_date DATE NOT NULL,
    client_id INTEGER REFERENCES clients(client_id),
    order_id INTEGER REFERENCES orders(order_id),
    amount NUMERIC(12, 2) NOT NULL,
    payment_method TEXT
);

CREATE TABLE supplier_payments (
    payment_id SERIAL PRIMARY KEY,
    payment_date DATE NOT NULL,
    supplier_id INTEGER REFERENCES suppliers(supplier_id),
    delivery_id INTEGER REFERENCES incoming_deliveries(delivery_id),
    amount NUMERIC(12, 2) NOT NULL,
    payment_method TEXT
);

-- Шаг 1.2: Создаем новую таблицу inventory_movements для хранения всех движений товара
CREATE TABLE inventory_movements (
    movement_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    movement_type VARCHAR(50) NOT NULL, -- Тип движения: 'in' (поступление), 'out' (продажа), 'adjustment_in', 'adjustment_out', 'return_in', 'return_out' и т.д.
    quantity_change INTEGER NOT NULL,   -- Изменение количества: положительное для прихода, отрицательное для расхода
    movement_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, -- Дата и время движения
    source_document_type VARCHAR(50),   -- Тип документа-источника (например, 'order', 'delivery', 'inventory_adjustment')
    source_document_id INTEGER,         -- ID документа-источника (например, order_id, delivery_id)
    description TEXT,                   -- Описание движения (например, "Продажа по заказу #123", "Поступление от поставщика X")
    CONSTRAINT chk_quantity_change_not_zero CHECK (quantity_change != 0) -- Количество изменения не может быть 0
);

-- Шаг 1.3: Добавляем индексы для ускорения запросов
CREATE INDEX idx_inventory_movements_product_id ON inventory_movements (product_id);
CREATE INDEX idx_inventory_movements_movement_date ON inventory_movements (movement_date);
CREATE INDEX idx_inventory_movements_source_document ON inventory_movements (source_document_type, source_document_id);

CREATE TABLE IF NOT EXISTS stock (
    product_id INT PRIMARY KEY,
    quantity DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    -- Добавляем внешний ключ, который ссылается на таблицу products
    CONSTRAINT fk_product
        FOREIGN KEY (product_id)
        REFERENCES products (product_id)
        ON DELETE CASCADE -- Если продукт удаляется, его запись в stock тоже удаляется
);

-- Опционально: Добавьте индекс для быстрого поиска по product_id
CREATE INDEX IF NOT EXISTS idx_stock_product_id ON stock (product_id);