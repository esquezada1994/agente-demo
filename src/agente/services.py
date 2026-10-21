"""Casos de uso del agente. La API y la línea de comandos solo llaman aquí."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agente.db import (
    Approval,
    Case,
    Conversation,
    ErpCustomer,
    ErpPayment,
    Message,
    PaymentPromise,
    utcnow,
)
from agente.domain import collections
from agente.engine import governance, guards, runtime, store

HISTORY_TURNS = 10


class NotFound(LookupError):
    pass


def today() -> date:
    return datetime.now(UTC).date()


# --- Conversación ------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatReply:
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    outcome: str
    trace_id: str
    tools: list[str]
    violations: list[str]


def _history(session: Session, conversation_id: uuid.UUID) -> list[BaseMessage]:
    rows = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(HISTORY_TURNS * 2)
        )
    )
    return [
        HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        for m in reversed(rows)
    ]


def chat(
    session: Session,
    customer_id: uuid.UUID,
    message: str,
    conversation_id: uuid.UUID | None = None,
    channel: str = "web",
) -> ChatReply:
    if session.get(ErpCustomer, customer_id) is None:
        raise NotFound("Cliente no encontrado")
    conversation = session.get(Conversation, conversation_id) if conversation_id else None
    if conversation is None or conversation.customer_id != customer_id:
        conversation = Conversation(customer_id=customer_id, channel=channel)
        session.add(conversation)
        session.flush()
    definition = store.active(session)
    result = runtime.run_chat(
        session,
        definition,
        customer_id,
        _history(session, conversation.id),
        message,
        today(),
        channel,
    )
    # Se guarda la conversación (dato del cliente, en su base) sin datos personales sueltos.
    session.add(
        Message(
            conversation_id=conversation.id, role="user", content=guards.mask_personal_data(message)
        )
    )
    reply = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result.answer,
        trace_id=result.trace_id,
        meta={"tools": result.tools, "violations": result.violations, "outcome": result.outcome},
    )
    session.add(reply)
    conversation.outcome = (
        "escalated" if result.outcome == "escalated" else (conversation.outcome or "resolved")
    )
    conversation.last_message_at = utcnow()
    session.flush()
    return ChatReply(
        conversation.id,
        reply.id,
        result.answer,
        result.outcome,
        result.trace_id,
        result.tools,
        result.violations,
    )


def rate(session: Session, message_id: uuid.UUID, rating: int) -> None:
    message = session.get(Message, message_id)
    if message is None or message.role != "assistant":
        raise NotFound("Mensaje no encontrado")
    message.feedback = 1 if rating > 0 else -1
    if message.trace_id:
        governance.feedback(message.trace_id, message.feedback)


# --- Cartera y recordatorios ----------------------------------------------------------------


def prepare_reminders(session: Session, limit: int = 10) -> int:
    """Redacta recordatorios para los clientes prioritarios y los deja en la bandeja."""
    definition = store.active(session)
    created = 0
    for item in collections.portfolio(session, today()):
        if created >= limit:
            break
        if item.action == "none" or item.pending_approval:
            continue
        upcoming = [i for i in item.invoices if i.due_date >= today()]
        facts: dict[str, Any] = {
            "nombre": item.customer.name,
            "tipo": item.action,
            "saldo": str(
                item.overdue_balance
                if item.action != "preventive"
                else sum(i.balance for i in upcoming)
            ),
            "dias_vencida": item.max_days_overdue,
            "vence": min((i.due_date for i in upcoming), default=None),
            "razones": item.reasons,
        }
        if runtime.run_reminder(session, definition, item.customer.id, facts, today()):
            created += 1
    return created


def decide(
    session: Session,
    approval_id: uuid.UUID,
    approve: bool,
    user_id: uuid.UUID,
    text: str | None,
    note: str | None,
) -> Approval:
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise NotFound("Aprobación no encontrada")
    if approval.status != "pending":
        raise ValueError("Esta propuesta ya fue decidida")
    approval.status = "approved" if approve else "rejected"
    approval.decided_at = utcnow()
    approval.decided_by = user_id
    approval.decision_note = note
    if approve and text and approval.kind == "reminder":
        approval.payload = {**approval.payload, "texto": text.strip()[:1000], "editado": True}
    if approve and approval.kind == "reminder":
        sent_trace = runtime.send_approved(session, store.active(session), approval)
        approval.payload = {**approval.payload, "envio_trace": sent_trace}
    if approve and approval.kind == "payment_plan":
        session.add(
            Case(
                customer_id=approval.customer_id,
                kind="payment_plan",
                category="aprobado",
                trace_id=approval.trace_id,
            )
        )
    session.flush()
    return approval


def simulate_payments(
    session: Session, days_ahead: int = 0, seed: int | None = None
) -> dict[str, Any]:
    """SIMULACIÓN: avanza el reloj de las promesas y registra los pagos cumplidos.
    Cada pago cumplido sale al portal como valor recuperado, ligado a la
    conversación que produjo la promesa."""
    on = today() + timedelta(days=days_ahead)
    results = collections.settle_due_promises(session, on, random.Random(seed))  # noqa: S311 - simulación
    recovered = Decimal(0)
    for r in results:
        if r.kept:
            recovered += r.amount
            governance.value(
                "revenue_recovered",
                amount=r.amount,
                label="pago",
                event_id=f"pago-{r.promise_id}",
                trace_id=r.trace_id,
            )
    return {
        "promesas": len(results),
        "cumplidas": sum(1 for r in results if r.kept),
        "recuperado": str(recovered),
    }


# --- Indicadores locales ----------------------------------------------------------------------


def dashboard(session: Session) -> dict[str, Any]:
    since = utcnow() - timedelta(days=30)
    conversations = (
        session.scalar(
            select(func.count()).select_from(Conversation).where(Conversation.started_at >= since)
        )
        or 0
    )
    escalated = (
        session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.started_at >= since, Conversation.outcome == "escalated")
        )
        or 0
    )
    promised = session.scalar(
        select(func.coalesce(func.sum(PaymentPromise.amount), 0)).where(
            PaymentPromise.created_at >= since
        )
    )
    recovered = session.scalar(
        select(func.coalesce(func.sum(ErpPayment.amount), 0)).where(
            ErpPayment.promise_id.is_not(None), ErpPayment.created_at >= since
        )
    )
    pending = (
        session.scalar(
            select(func.count()).select_from(Approval).where(Approval.status == "pending")
        )
        or 0
    )
    open_cases = (
        session.scalar(select(func.count()).select_from(Case).where(Case.status == "open")) or 0
    )
    items = collections.portfolio(session, today())
    return {
        "conversations": conversations,
        "escalation_share": round(escalated / conversations, 3) if conversations else 0,
        "promised": str(promised),
        "recovered": str(recovered),
        "pending_approvals": pending,
        "open_cases": open_cases,
        "overdue_total": str(sum((i.overdue_balance for i in items), Decimal(0))),
        "customers_overdue": sum(1 for i in items if i.overdue_balance > 0),
        "actionable": sum(1 for i in items if i.action != "none" and not i.pending_approval),
        "governance": governance.connection_info(session),
        "connected": governance.state.enabled,
    }
