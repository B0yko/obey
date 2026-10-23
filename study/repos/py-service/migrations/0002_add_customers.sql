-- Customers, and a link from invoices to the customer they were issued to.

CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

ALTER TABLE invoices ADD COLUMN customer_id INTEGER REFERENCES customers(id);

CREATE INDEX idx_invoices_customer ON invoices(customer_id);
