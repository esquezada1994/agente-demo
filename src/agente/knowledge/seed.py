"""Base de conocimiento inicial (políticas de ejemplo). La empresa las edita
desde la consola: cada cambio actualiza la fecha de la fuente, que el portal
usa para avisar si la información quedó desactualizada."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agente.db import Document

DOCUMENTS = [
    (
        "Formas de pago",
        "Puede pagar por transferencia o depósito a la cuenta corriente de la empresa en "
        "Banco Pichincha o Produbanco, en efectivo en nuestras oficinas, o con tarjeta en "
        "el enlace de pago que enviamos por correo. Indique siempre el número de factura.",
    ),
    (
        "Comprobante de pago",
        "Después de transferir o depositar, envíe el comprobante respondiendo a este chat "
        "o al correo de cobranzas. El pago se refleja en su estado de cuenta en un máximo "
        "de 48 horas laborables.",
    ),
    (
        "Horario de atención",
        "Atendemos de lunes a viernes de 08:00 a 19:00 y sábados de 09:00 a 13:00. Fuera "
        "de ese horario el asistente registra su pedido y un gestor lo contacta.",
    ),
    (
        "Intereses por mora",
        "Las facturas vencidas generan interés por mora según la tasa máxima vigente del "
        "Banco Central del Ecuador, desde el día siguiente al vencimiento.",
    ),
    (
        "Acuerdos de pago",
        "Si no puede pagar el total, puede pedir un acuerdo de pago en cuotas. Un gestor "
        "revisa cada pedido y responde en un máximo de dos días laborables.",
    ),
    (
        "Protección de datos",
        "Sus datos se tratan conforme a la Ley Orgánica de Protección de Datos Personales. "
        "Nunca le pediremos claves, números completos de tarjeta ni códigos por chat.",
    ),
]


def seed_documents(session: Session) -> int:
    if session.scalar(select(func.count()).select_from(Document)):
        return 0
    session.add_all(Document(title=t, body=b) for t, b in DOCUMENTS)
    session.flush()
    return len(DOCUMENTS)
