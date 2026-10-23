-- Payment terms: every invoice gets a due date (existing rows are due on the issue date).

ALTER TABLE invoices ADD COLUMN due_date TEXT;

UPDATE invoices SET due_date = issued_at WHERE due_date IS NULL;

CREATE INDEX idx_invoices_status_due ON invoices(status, due_date);
