"""Acceso al ERP del cliente.

El agente nunca consulta tablas directamente: usa esta interfaz. La versión
incluida (`SimulatedErp`) lee las tablas erp_* con datos sintéticos. Para un
cliente real se escribe otro adaptador (Odoo, SAP Business One, Contífico,
una API propia) con los mismos métodos, de SOLO LECTURA salvo registrar un
pago en la simulación. El resto del agente no cambia.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agente.db import ErpCustomer, ErpInvoice, ErpPayment

ZERO = Decimal(0)


@dataclass(frozen=True)
class Invoice:
    id: uuid.UUID
    number: str
    due_date: date
    amount: Decimal
    balance: Decimal

    def days_overdue(self, today: date) -> int:
        return max((today - self.due_date).days, 0)


@dataclass(frozen=True)
class Customer:
    id: uuid.UUID
    code: str
    name: str
    segment: str
    has_email: bool
    has_phone: bool
    broken_promises: int


class Erp(Protocol):
    def customer(self, customer_id: uuid.UUID) -> Customer | None: ...
    def customer_by_code(self, code: str) -> Customer | None: ...
    def customers(self) -> list[Customer]: ...
    def open_invoices(self, customer_id: uuid.UUID) -> list[Invoice]: ...


def _customer(row: ErpCustomer) -> Customer:
    return Customer(
        id=row.id,
        code=row.code,
        name=row.name,
        segment=row.segment,
        has_email=bool(row.email),
        has_phone=bool(row.phone),
        broken_promises=row.broken_promises,
    )


class SimulatedErp:
    def __init__(self, session: Session) -> None:
        self.session = session

    def customer(self, customer_id: uuid.UUID) -> Customer | None:
        row = self.session.get(ErpCustomer, customer_id)
        return _customer(row) if row else None

    def customer_by_code(self, code: str) -> Customer | None:
        row = self.session.scalar(select(ErpCustomer).where(ErpCustomer.code == code))
        return _customer(row) if row else None

    def customers(self) -> list[Customer]:
        rows = self.session.scalars(select(ErpCustomer).order_by(ErpCustomer.name))
        return [_customer(r) for r in rows]

    def open_invoices(self, customer_id: uuid.UUID) -> list[Invoice]:
        rows = self.session.scalars(
            select(ErpInvoice)
            .where(ErpInvoice.customer_id == customer_id, ErpInvoice.balance > 0)
            .order_by(ErpInvoice.due_date)
        )
        return [Invoice(r.id, r.number, r.due_date, r.amount, r.balance) for r in rows]

    # Solo existe en la simulación: en un ERP real el pago lo registra el ERP.
    def register_payment(
        self, invoice_id: uuid.UUID, amount: Decimal, paid_on: date, promise_id: uuid.UUID | None
    ) -> ErpPayment:
        invoice = self.session.get(ErpInvoice, invoice_id)
        if invoice is None:
            raise ValueError("Factura inexistente")
        applied = min(amount, invoice.balance)
        invoice.balance -= applied
        payment = ErpPayment(
            invoice_id=invoice_id, paid_on=paid_on, amount=applied, promise_id=promise_id
        )
        self.session.add(payment)
        self.session.flush()
        return payment


# --- Datos sintéticos ---------------------------------------------------------------------

_COMPANIES = [
    "Ferretería El Tornillo",
    "Distribuidora Andina",
    "Farmacia San Rafael",
    "Panadería La Espiga",
    "Constructora Ríos & Hijos",
    "Agroinsumos del Valle",
    "Textiles Imbabura",
    "Clínica Dental Sonrisa",
    "Librería Montalvo",
    "Taller Mecánico Rápido",
    "Restaurante El Fogón",
    "Importadora Pacífico",
    "Colegio Nuevo Horizonte",
    "Hotel Mirador",
    "Bodega Central",
    "Lácteos La Pradera",
    "Transportes Cotopaxi",
    "Óptica Visión Clara",
]
_PEOPLE = [
    "María Fernanda López",
    "Carlos Andrade",
    "Lucía Paredes",
    "Jorge Villacís",
    "Daniela Herrera",
    "Andrés Cevallos",
]


def seed_erp(session: Session, today: date, seed: int = 11) -> int:
    """Clientes y facturas sintéticas: al día, por vencer y vencidas."""
    if session.scalar(select(func.count()).select_from(ErpCustomer)):
        return 0
    rng = random.Random(seed)  # noqa: S311 - datos sintéticos
    names = [(n, "empresa") for n in _COMPANIES] + [(n, "persona") for n in _PEOPLE]
    invoice_no = 1000
    for index, (name, segment) in enumerate(names):
        slug = "".join(c for c in name.lower() if c.isalnum())[:12]
        customer = ErpCustomer(
            code=f"C-{101 + index}",
            name=name,
            segment=segment,
            phone=f"+5939{rng.randint(80000000, 99999999)}",
            email=f"pagos@{slug}.ec" if segment == "empresa" else f"{slug}@correo.ec",
            broken_promises=rng.choice([0, 0, 0, 1, 2]),
        )
        session.add(customer)
        session.flush()
        for _ in range(rng.randint(1, 4)):
            invoice_no += 1
            # De -60 (vencida hace 60 días) a +12 (vence en 12 días).
            due_in = rng.choice([-60, -45, -32, -20, -12, -6, -2, 2, 4, 7, 12, 25])
            issue = today + timedelta(days=due_in - 30)
            amount = Decimal(rng.randint(80, 4200)) + Decimal(rng.randint(0, 99)) / 100
            paid = rng.random() < 0.2
            session.add(
                ErpInvoice(
                    customer_id=customer.id,
                    number=f"001-002-{invoice_no:09d}",
                    issue_date=issue,
                    due_date=today + timedelta(days=due_in),
                    amount=amount,
                    balance=ZERO if paid else amount,
                )
            )
    session.flush()
    return len(names)


def refresh_demo_invoices(session: Session, today: date, seed: int | None = None) -> int:
    """SIMULACIÓN: si la cartera quedó sin saldo (todo pagado), emite facturas
    nuevas para los clientes de prueba, con vencimientos alrededor de hoy."""
    rng = random.Random(seed)  # noqa: S311 - datos sintéticos
    customers = list(session.scalars(select(ErpCustomer)))
    last = session.scalar(select(func.count()).select_from(ErpInvoice)) or 0
    created = 0
    for customer in customers:
        for _ in range(rng.randint(1, 3)):
            last += 1
            due_in = rng.choice([-45, -30, -20, -10, -5, 2, 4, 7])
            amount = Decimal(rng.randint(80, 4200)) + Decimal(rng.randint(0, 99)) / 100
            session.add(
                ErpInvoice(
                    customer_id=customer.id,
                    number=f"001-003-{last:09d}",
                    issue_date=today + timedelta(days=due_in - 30),
                    due_date=today + timedelta(days=due_in),
                    amount=amount,
                    balance=amount,
                )
            )
            created += 1
    session.flush()
    return created
