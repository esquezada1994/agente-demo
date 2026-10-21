"""Pruebas contra PostgreSQL real (la búsqueda usa texto completo de Postgres).

Variable TEST_DATABASE_URL; por defecto, la base local de desarrollo. Si no
hay base disponible, las pruebas que la necesitan se saltan.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL", "postgresql+psycopg://agente:agente_local@localhost:5432/agente_test"
    ),
)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("MODEL_PROVIDER", "demo")

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import text
from sqlalchemy.orm import Session

from agente import db
from agente.domain.erp import seed_erp
from agente.engine import governance
from agente.knowledge.seed import seed_documents

TODAY = date.today()


@pytest.fixture(scope="session")
def engine() -> Iterator[Any]:
    engine = db.get_engine()
    try:
        with engine.connect():
            pass
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PostgreSQL no disponible: {type(exc).__name__}")
    db.Base.metadata.drop_all(engine)
    db.Base.metadata.create_all(engine)
    yield engine


@pytest.fixture
def session(engine: Any) -> Iterator[Session]:
    with engine.begin() as conn:
        tables = ", ".join(t.name for t in reversed(db.Base.metadata.sorted_tables))
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    with db.session_scope() as s:
        seed_erp(s, TODAY)
        seed_documents(s)
    with db.session_scope() as s:
        yield s


class Captured:
    def __init__(self) -> None:
        self.exporter = InMemorySpanExporter()
        self.rest: list[tuple[str, dict[str, Any]]] = []

    def spans(self) -> list[Any]:
        return list(self.exporter.get_finished_spans())

    def values(self) -> list[dict[str, Any]]:
        return [e for path, body in self.rest if path == "/v1/value" for e in body["events"]]


@pytest.fixture
def captured(session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[Captured]:
    """Gobierno conectado a un exportador en memoria: se ve lo que saldría al portal."""
    import plataforma_sdk as gov
    from plataforma_sdk import platform

    cap = Captured()
    governance.configure(session, "1.0.0", processor=SimpleSpanProcessor(cap.exporter))
    monkeypatch.setattr(
        platform, "_post", lambda method, path, body, key=None: cap.rest.append((path, body))
    )
    gov.set_synchronous(True)
    yield cap
    gov.set_synchronous(False)
    governance.state.enabled = False
