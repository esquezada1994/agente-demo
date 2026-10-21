"""Modelo de datos del agente.

El agente es un producto independiente: sus datos (usuarios, conversaciones,
cartera, aprobaciones) viven en SU base, en la infraestructura del cliente.
Al portal de gobernanza solo salen hechos medibles (ver engine/governance.py).

Tres grupos de tablas:

- Operación del agente: usuarios, definiciones versionadas, conocimiento,
  conversaciones, mensajes, aprobaciones, ajustes y secretos.
- Dominio de cobranza: promesas de pago y casos (disputas, acuerdos).
- ERP simulado (erp_*): en una implementación real se reemplaza por el
  adaptador del ERP del cliente (domain/erp.py); el agente no cambia.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from agente.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


# --- Operación ---------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))  # admin | gestor
    password_hash: Mapped[str] = mapped_column(String(300))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentDefinitionRow(Base):
    """Cada versión publicada de la definición del agente. Una sola activa."""

    __tablename__ = "agent_definitions"

    id: Mapped[uuid.UUID] = _id()
    agent_id: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(40))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class Document(Base):
    """Base de conocimiento (políticas, preguntas frecuentes). Búsqueda de
    texto completo de Postgres: sin servicio externo de embeddings."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_tsv", "tsv", postgresql_using="gin"),)

    id: Mapped[uuid.UUID] = _id()
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('spanish', coalesce(title, '') || ' ' || coalesce(body, ''))",
            persisted=True,
        ),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _id()
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("erp_customers.id"))
    channel: Mapped[str] = mapped_column(String(30), default="web")
    outcome: Mapped[str | None] = mapped_column(String(20))  # resolved | escalated | abandoned
    started_at: Mapped[datetime] = _created()
    last_message_at: Mapped[datetime] = _created()


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _id()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    feedback: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()


class Approval(Base):
    """Una acción que el agente propone y una persona decide (aprobación humana)."""

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = _id()
    kind: Mapped[str] = mapped_column(String(30))  # reminder | payment_plan
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("erp_customers.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(String(300))  # por qué lo propone
    trace_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = _created()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decision_note: Mapped[str | None] = mapped_column(String(300))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)


class StoredSecret(Base):
    """Secretos cifrados con SECRET_KEY (p. ej. la llave de ingesta del portal)."""

    __tablename__ = "secrets"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value_encrypted: Mapped[str] = mapped_column(Text)
    hint: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime] = _created()


# --- Dominio de cobranza --------------------------------------------------------------


class PaymentPromise(Base):
    __tablename__ = "payment_promises"

    id: Mapped[uuid.UUID] = _id()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("erp_customers.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    promised_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|kept|broken
    trace_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = _created()


class Case(Base):
    """Algo que requiere a una persona: disputa, pedido de acuerdo, derivación."""

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = _id()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("erp_customers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # dispute | handoff | payment_plan
    category: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="open")
    trace_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = _created()


# --- ERP simulado ----------------------------------------------------------------------


class ErpCustomer(Base):
    __tablename__ = "erp_customers"

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    segment: Mapped[str] = mapped_column(String(30))  # empresa | persona
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(320))
    broken_promises: Mapped[int] = mapped_column(Integer, default=0)


class ErpInvoice(Base):
    __tablename__ = "erp_invoices"

    id: Mapped[uuid.UUID] = _id()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("erp_customers.id"), index=True)
    number: Mapped[str] = mapped_column(String(40), unique=True)
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class ErpPayment(Base):
    __tablename__ = "erp_payments"

    id: Mapped[uuid.UUID] = _id()
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("erp_invoices.id"), index=True)
    paid_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    promise_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_promises.id"))
    created_at: Mapped[datetime] = _created()


# --- Sesiones ----------------------------------------------------------------------------


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def _factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Una transacción: confirma si todo termina bien, revierte si hay error."""
    with _factory()() as session, session.begin():
        yield session
