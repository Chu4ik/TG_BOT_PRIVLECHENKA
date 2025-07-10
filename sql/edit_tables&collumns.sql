ALTER TABLE orders
ADD COLUMN confirmation_date TIMESTAMP WITH TIME ZONE;

ALTER TABLE orders
ADD COLUMN payment_status VARCHAR(50) NOT NULL DEFAULT 'unpaid', -- Статус оплаты: 'unpaid', 'partially_paid', 'paid', 'overdue'. По умолчанию 'unpaid'.
ADD COLUMN amount_paid NUMERIC(10, 2) NOT NULL DEFAULT 0.00, -- Сумма, которая уже была оплачена по этой накладной. По умолчанию 0.00.
ADD COLUMN due_date DATE DEFAULT NULL; -- Дата, к которой должна быть произведена оплата. Изначально NULL.

-- Опционально: Добавление CHECK ограничения для payment_status, если хотите ограничить возможные значения
ALTER TABLE orders
ADD CONSTRAINT chk_payment_status CHECK (payment_status IN ('unpaid', 'partially_paid', 'paid', 'overdue'));

-- Опционально: Добавление индексов для ускорения запросов по новым полям (особенно для аналитики)
CREATE INDEX idx_orders_payment_status ON orders (payment_status);
CREATE INDEX idx_orders_due_date ON orders (due_date);

UPDATE orders
SET confirmation_date = delivery_date
WHERE confirmation_date != delivery_date;

ALTER TABLE orders
ADD COLUMN actual_payment_date TIMESTAMP DEFAULT NULL;

-- Добавляем столбец cost_per_unit, если его нет
ALTER TABLE products
ADD COLUMN cost_per_unit DECIMAL(10, 2) NOT NULL DEFAULT 0.00;

-- Добавляем столбец description, если его нет
ALTER TABLE products
ADD COLUMN description TEXT;

ALTER TABLE inventory_movements
ADD COLUMN unit_cost DECIMAL(10, 2);

SELECT SUM(quantity)
FROM order_lines;

SELECT SUM(quantity)
FROM stock;

SELECT product_id, quantity FROM stock;
