# Copilot instructions

Fennel Billing generates invoices for subscription customers and stores them as PDFs.
It is a Django REST framework service; the apps are `billing/` and `customers/`.

## Rules

This repository uses Poetry. Do not call `pip install`; use `poetry add` instead.
Never push to the remote.
Prefer the Django ORM over raw SQL.

The detailed project rules are in `AGENTS.md`.
