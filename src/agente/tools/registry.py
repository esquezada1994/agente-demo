"""Herramientas que el agente puede usar.

Cada herramienta se registra en código con su contrato (parámetros tipados,
si escribe datos, si requiere aprobación, qué fuente toca). La definición del
agente (JSON o canvas) elige cuáles habilitar; no puede inventar una nueva:
así una persona que arma un agente no puede darle al modelo un poder que el
equipo técnico no revisó.

Reglas de diseño:
- Las herramientas reciben al cliente desde el contexto de la conversación,
  NUNCA como parámetro del modelo: el modelo no puede consultar a otro cliente.
- Las que modifican algo sensible (acuerdos de pago) no lo hacen: dejan una
  propuesta en la bandeja de aprobación.
- Devuelven datos mínimos y estructurados; el texto lo arma el modelo.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agente.db import Approval, Case, PaymentPromise
from agente.domain.erp import ZERO, SimulatedErp


@dataclass
class ToolContext:
    session: Session
    customer_id: uuid.UUID
    today: date
    trace_id: str | None
    max_promise_days: int = 15
    # Efectos que el motor necesita conocer (resultado de la solicitud y valor).
    escalated: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)


class ToolError(ValueError):
    """Error que el modelo debe ver (para corregir o explicar), no un fallo técnico."""


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Callable[[ToolContext, Any], dict[str, Any]]
    source: str
    writes: bool = False
    requires_approval: bool = False


TOOLS: dict[str, RegisteredTool] = {}


def register(tool: RegisteredTool) -> None:
    TOOLS[tool.name] = tool


# --- Estado de cuenta --------------------------------------------------------------------


class NoArgs(BaseModel):
    pass


def _statement(ctx: ToolContext, _: NoArgs) -> dict[str, Any]:
    erp = SimulatedErp(ctx.session)
    invoices = erp.open_invoices(ctx.customer_id)
    return {
        "total_pendiente": str(sum((i.balance for i in invoices), ZERO)),
        "facturas": [
            {
                "numero": i.number,
                "vence": i.due_date.isoformat(),
                "saldo": str(i.balance),
                "dias_vencida": i.days_overdue(ctx.today),
            }
            for i in invoices
        ],
        "moneda": "USD",
    }


register(
    RegisteredTool(
        name="consultar_estado_cuenta",
        description="Facturas pendientes del cliente de esta conversación, con saldo y vencimiento.",
        args=NoArgs,
        handler=_statement,
        source="erp://cartera/facturas",
    )
)


# --- Promesa de pago ----------------------------------------------------------------------


class PromiseArgs(BaseModel):
    monto: str = Field(
        description="Monto que el cliente se compromete a pagar, en USD (ej. 250.00)"
    )
    fecha: str = Field(description="Fecha en que pagará, formato AAAA-MM-DD")


def _promise(ctx: ToolContext, args: PromiseArgs) -> dict[str, Any]:
    try:
        amount = Decimal(args.monto).quantize(Decimal("0.01"))
        when = date.fromisoformat(args.fecha)
    except (InvalidOperation, ValueError) as exc:
        raise ToolError("Monto o fecha con formato inválido") from exc
    erp = SimulatedErp(ctx.session)
    total = sum((i.balance for i in erp.open_invoices(ctx.customer_id)), ZERO)
    if amount <= 0 or amount > total:
        raise ToolError(f"El monto debe ser mayor a 0 y no superar el saldo ({total})")
    limit = ctx.today + timedelta(days=ctx.max_promise_days)
    if when < ctx.today or when > limit:
        raise ToolError(f"La fecha debe estar entre hoy y {limit.isoformat()}")
    promise = PaymentPromise(
        customer_id=ctx.customer_id, amount=amount, promised_date=when, trace_id=ctx.trace_id
    )
    ctx.session.add(promise)
    ctx.session.flush()
    ctx.events.append(
        {
            "kind": "revenue_promised",
            "amount": amount,
            "label": "promesa_pago",
            "event_id": f"promesa-{promise.id}",
        }
    )
    return {"registrada": True, "monto": str(amount), "fecha": when.isoformat()}


register(
    RegisteredTool(
        name="registrar_promesa",
        description=(
            "Registra la promesa de pago del cliente (monto y fecha). Usar solo cuando el "
            "cliente confirma explícitamente cuánto y cuándo pagará."
        ),
        args=PromiseArgs,
        handler=_promise,
        source="agente://cobranza/promesas",
        writes=True,
    )
)


# --- Acuerdo de pago (requiere aprobación) -------------------------------------------------


class PlanReason(StrEnum):
    LIQUIDEZ = "liquidez"
    MONTO_ALTO = "monto_alto"
    OTRO = "otro"


class PlanArgs(BaseModel):
    cuotas: int = Field(ge=2, le=12, description="Número de cuotas que pide el cliente")
    motivo: PlanReason


def _plan(ctx: ToolContext, args: PlanArgs) -> dict[str, Any]:
    approval = Approval(
        kind="payment_plan",
        customer_id=ctx.customer_id,
        payload={"cuotas": args.cuotas, "motivo": args.motivo.value},
        reason="Pedido del cliente en la conversación",
        trace_id=ctx.trace_id,
    )
    ctx.session.add(approval)
    ctx.session.flush()
    return {"en_revision": True, "mensaje": "Un gestor revisará el pedido y responderá."}


register(
    RegisteredTool(
        name="solicitar_acuerdo_pago",
        description="Propone un acuerdo de pago en cuotas. No lo aprueba: queda para un gestor.",
        args=PlanArgs,
        handler=_plan,
        source="agente://cobranza/acuerdos",
        writes=True,
        requires_approval=True,
    )
)


# --- Disputa y derivación -------------------------------------------------------------------


class DisputeKind(StrEnum):
    YA_PAGUE = "ya_pague"
    MONTO_INCORRECTO = "monto_incorrecto"
    NO_RECONOCE = "no_reconoce"
    CALIDAD = "calidad"
    OTRO = "otro"


class DisputeArgs(BaseModel):
    categoria: DisputeKind


def _dispute(ctx: ToolContext, args: DisputeArgs) -> dict[str, Any]:
    ctx.session.add(
        Case(
            customer_id=ctx.customer_id,
            kind="dispute",
            category=args.categoria.value,
            trace_id=ctx.trace_id,
        )
    )
    ctx.escalated = True
    return {"caso_creado": True, "mensaje": "Un gestor revisará el caso."}


register(
    RegisteredTool(
        name="reportar_disputa",
        description="Registra que el cliente no está de acuerdo con una deuda (ya pagó, monto, etc.).",
        args=DisputeArgs,
        handler=_dispute,
        source="agente://cobranza/casos",
        writes=True,
    )
)


class HandoffReason(StrEnum):
    PIDE_PERSONA = "pide_persona"
    FUERA_DE_ALCANCE = "fuera_de_alcance"
    MOLESTO = "molesto"


class HandoffArgs(BaseModel):
    motivo: HandoffReason


def _handoff(ctx: ToolContext, args: HandoffArgs) -> dict[str, Any]:
    ctx.session.add(
        Case(
            customer_id=ctx.customer_id,
            kind="handoff",
            category=args.motivo.value,
            trace_id=ctx.trace_id,
        )
    )
    ctx.escalated = True
    return {"derivado": True}


register(
    RegisteredTool(
        name="derivar_a_persona",
        description="Pasa la conversación a un gestor humano.",
        args=HandoffArgs,
        handler=_handoff,
        source="agente://cobranza/casos",
        writes=True,
    )
)


# --- Factura ----------------------------------------------------------------------------------


class InvoiceArgs(BaseModel):
    numero: str = Field(description="Número de la factura, tal como aparece en el estado de cuenta")


def _send_invoice(ctx: ToolContext, args: InvoiceArgs) -> dict[str, Any]:
    erp = SimulatedErp(ctx.session)
    numbers = {i.number for i in erp.open_invoices(ctx.customer_id)}
    if args.numero not in numbers:
        raise ToolError("La factura no corresponde a este cliente")
    customer = erp.customer(ctx.customer_id)
    if customer is None or not customer.has_email:
        raise ToolError("El cliente no tiene correo registrado")
    # Simulado: en producción, el servicio de correo del cliente.
    return {"enviada": True, "destino": "correo registrado"}


register(
    RegisteredTool(
        name="enviar_factura",
        description="Envía una copia de la factura al correo registrado del cliente.",
        args=InvoiceArgs,
        handler=_send_invoice,
        source="erp://cartera/facturas",
    )
)
