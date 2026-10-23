-- Initial schema: invoices, their lines, and tracked stock items.

CREATE TABLE invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL UNIQUE,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    issued_at TEXT NOT NULL
);

CREATE TABLE invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    sku TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price TEXT NOT NULL
);

CREATE INDEX idx_invoice_lines_invoice ON invoice_lines(invoice_id);

CREATE TABLE stock_items (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    on_hand INTEGER NOT NULL DEFAULT 0
);
