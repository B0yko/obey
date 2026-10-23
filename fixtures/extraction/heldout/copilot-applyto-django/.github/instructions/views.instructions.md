---
applyTo: "**/views.py,**/views/*.py"
---

Views are thin wrappers around the service layer in `services/`. Templates are in
`templates/<app>/`.

- Never use `csrf_exempt`.
- Each new module under a `views/` package starts with a module docstring.
- Keep views free of business logic.
