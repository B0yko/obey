# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from ledgerline.db import Database
from ledgerline.service import InvoiceService

FIXED_NOW = datetime(2026, 3, 4, 9, 30, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return FIXED_NOW


@pytest.fixture
def db() -> Iterator[Database]:
    database = Database(":memory:")
    database.migrate()
    yield database
    database.close()


@pytest.fixture
def service(db: Database) -> InvoiceService:
    return InvoiceService(db, clock=lambda: FIXED_NOW)
