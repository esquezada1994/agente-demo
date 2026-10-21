"""Reglas de cobranza: priorización de la cartera y seguimiento de promesas.

La priorización NO la hace el modelo: es una fórmula explícita y explicable
(el gestor ve por qué un cliente está primero). El modelo solo redacta y
conversa. Así el resultado es auditable y no depende del proveedor de IA.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from agente.db import Approval, ErpCustomer, PaymentPromise
from agente.domain.erp import ZERO, Customer, Invoice, SimulatedErp

PREVENTIVE_WINDOW_DAYS = 5


@dataclass
class PortfolioItem:
    customer: Customer
    invoices: list[Invoice]
    total_balance: Decimal
    overdue_balance: Decimal
    max_days_overdue: int
    next_due_in: int | None
    action: str  # preventive | overdue | promise_followup | none
    score: float
    reasons: list[str] = field(default_factory=list)
    open_promise: PaymentPromise | None = None
    pending_approval: bool = False


def _score(overdue: Decimal, days: int, broken: int) -> float:
    # Monto vencido, ponderado por antigüedad (cada 30 días suma 1x) y por
    # promesas incumplidas antes (cada una suma 25 %).
    return float(overdue) * (1 + days / 30) * (1 + 0.25 * broken)


def portfolio(session: Session, today: date) -> list[PortfolioItem]:
    erp = SimulatedErp(session)
    promises = {
        p.customer_id: p
        for p in session.scalars(select(PaymentPromise).where(PaymentPromise.status == "open"))
    }
    pending = set(session.scalars(select(Approval.customer_id).where(Approval.status == "pending")))
    items = []
    for customer in erp.customers():
        invoices = erp.open_invoices(customer.id)
        if not invoices:
            continue
        overdue = [i for i in invoices if i.due_date < today]
        upcoming = [i for i in invoices if i.due_date >= today]
        overdue_balance = sum((i.balance for i in overdue), ZERO)
        max_days = max((i.days_overdue(today) for i in overdue), default=0)
        next_due = min(((i.due_date - today).days for i in upcoming), default=None)
        promise = promises.get(customer.id)
        reasons: list[str] = []
        if promise is not None:
            action = "promise_followup" if promise.promised_date < today else "none"
            reasons.append("promise_broken" if action == "promise_followup" else "promise_open")
        elif overdue:
            action = "overdue"
            reasons.append("overdue")
            if max_days > 30:
                reasons.append("over_30_days")
            if customer.broken_promises:
                reasons.append("broken_before")
        elif next_due is not None and next_due <= PREVENTIVE_WINDOW_DAYS:
            action = "preventive"
            reasons.append("due_soon")
        else:
            action = "none"
        score = _score(overdue_balance, max_days, customer.broken_promises)
        if action == "preventive":
            score = float(sum((i.balance for i in upcoming), ZERO)) * 0.2
        items.append(
            PortfolioItem(
                customer=customer,
                invoices=invoices,
                total_balance=sum((i.balance for i in invoices), ZERO),
                overdue_balance=overdue_balance,
                max_days_overdue=max_days,
                next_due_in=next_due,
                action=action,
                score=round(score, 2),
                reasons=reasons,
                open_promise=promise,
                pending_approval=customer.id in pending,
            )
        )
    items.sort(key=lambda i: (i.action == "none", -i.score))
    return items


@dataclass(frozen=True)
class PaymentResult:
    promise_id: uuid.UUID
    customer_id: uuid.UUID
    amount: Decimal
    trace_id: str | None
    kept: bool


def settle_due_promises(
    session: Session, today: date, rng: random.Random | None = None
) -> list[PaymentResult]:
    """SIMULACIÓN: decide si cada promesa vencida se cumplió y registra el pago
    en el ERP simulado. En una implementación real esto lo detecta la
    conciliación con los pagos que registra el ERP."""
    rng = rng or random.Random()  # noqa: S311 - simulación
    erp = SimulatedErp(session)
    results = []
    for promise in session.scalars(
        select(PaymentPromise).where(
            PaymentPromise.status == "open", PaymentPromise.promised_date <= today
        )
    ):
        kept = rng.random() < 0.7
        if kept:
            remaining = promise.amount
            for invoice in erp.open_invoices(promise.customer_id):
                if remaining <= 0:
                    break
                payment = erp.register_payment(
                    invoice.id, min(remaining, invoice.balance), today, promise.id
                )
                remaining -= payment.amount
            promise.status = "kept"
        else:
            promise.status = "broken"
            customer = session.get(ErpCustomer, promise.customer_id)
            if customer is not None:
                customer.broken_promises += 1
        results.append(
            PaymentResult(promise.id, promise.customer_id, promise.amount, promise.trace_id, kept)
        )
    session.flush()
    return results
