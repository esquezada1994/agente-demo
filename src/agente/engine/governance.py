"""Gobierno del agente: todo lo que sale hacia el portal pasa por aquí.

El agente funciona igual conectado o no al portal. Si no está enrolado, las
trazas se generan pero no se envían (procesador nulo) y los eventos de valor
se descartan: así el código de los nodos no tiene condicionales.

Qué sale (y qué no):
- Trazas OpenTelemetry por etapa: modelo, tokens exactos (del campo `usage`
  del proveedor), latencia, fuente, relevancia, herramienta, error,
  resultado, categoría de violación.
- Manifiesto: la definición del agente reducida a lo que el portal gobierna.
- Valor: horas evitadas, promesas y pagos (montos agregados, sin datos de la
  persona).
- Nunca: textos de mensajes, nombres, teléfonos, números de factura.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import plataforma_sdk as gov
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from sqlalchemy.orm import Session

from agente.config import get_settings
from agente.db import Setting, session_scope
from agente.engine.definition import NODE_TYPES, AgentDefinition
from agente.security import read_secret, store_secret
from agente.tools.registry import TOOLS

log = logging.getLogger(__name__)

SECRET_KEY = "plataforma_api_key"  # noqa: S105 - nombre del secreto, no su valor
SETTING_KEY = "plataforma"


class _NullProcessor(SpanProcessor):
    def on_end(self, span: ReadableSpan) -> None:
        return None


class _State:
    enabled = False
    solution = "agente-local"
    version = "0.0.0"


state = _State()


def configure(session: Session, version: str, processor: SpanProcessor | None = None) -> bool:
    """Inicializa el SDK con lo guardado. Devuelve si quedó conectado al portal."""
    settings = get_settings()
    info = session.get(Setting, SETTING_KEY)
    api_key = read_secret(session, SECRET_KEY)
    state.version = version
    if processor is not None:  # pruebas
        state.enabled = True
        state.solution = info.value["solution"] if info else "agente-pruebas"
        gov.init(solution=state.solution, version=version, processor=processor)
        return True
    if info is None or api_key is None:
        state.enabled = False
        gov.init(solution=state.solution, version=version, processor=_NullProcessor())
        return False
    state.enabled = True
    state.solution = info.value["solution"]
    gov.init(
        solution=state.solution,
        endpoint=info.value["url"],
        api_key=api_key,
        version=version,
        environment=settings.environment_name,
    )
    return True


def enroll(session: Session, platform_url: str, token: str, instance: str | None) -> dict[str, Any]:
    """Canjea el token del portal y guarda la llave cifrada."""
    result = gov.enroll(platform_url, token, instance=instance)
    store_secret(session, SECRET_KEY, result.api_key)
    info = {
        "url": platform_url.rstrip("/"),
        "solution": result.solution,
        "solution_name": result.solution_name,
        "tenant": result.tenant,
        "enrolled_at": datetime.now(UTC).isoformat(),
    }
    row = session.get(Setting, SETTING_KEY) or Setting(key=SETTING_KEY, value={})
    row.value = info
    session.add(row)
    return info


def connection_info(session: Session) -> dict[str, Any] | None:
    row = session.get(Setting, SETTING_KEY)
    return dict(row.value) if row else None


def build_manifest(definition: AgentDefinition) -> dict[str, Any]:
    """La definición, reducida a lo que el portal gobierna. Sin instrucciones
    ni textos: solo modelos, fuentes, herramientas, controles y versión."""
    validations = set()
    human = False
    for flow in definition.flows.values():
        for node in flow.nodes:
            if node.type == "input_guard":
                validations.update({"personal_data", "prompt_injection"})
            if node.type == "validate":
                validations.update(node.config.get("checks", []))
            if node.type == "approval":
                human = True
    tools = []
    for spec in definition.tools:
        registered = TOOLS[spec.name]
        requires = (
            spec.requires_approval
            if spec.requires_approval is not None
            else registered.requires_approval
        )
        human = human or requires
        tools.append(
            {
                "name": spec.name,
                "source": spec.source or registered.source,
                "writes": registered.writes,
                "requires_approval": requires,
            }
        )
    models = [m for m in (definition.models.main, definition.models.small) if m]
    return {
        "version": definition.version,
        "name": definition.name,
        "purpose": definition.description,
        "framework": "langgraph",
        "models": models,
        "sources": [s.model_dump() for s in definition.sources],
        "tools": tools,
        "data_categories": definition.policies.data_categories,
        "validation": sorted(validations),
        "human_in_the_loop": human,
        "retention_days": definition.policies.retention_days,
        "value_kinds": ["time_saved", "revenue_promised", "revenue_recovered", "task_completed"],
        "stages": sorted(
            {NODE_TYPES[n.type].stage for f in definition.flows.values() for n in f.nodes}
        ),
    }


def publish_manifest(definition: AgentDefinition) -> dict[str, Any] | None:
    if not state.enabled:
        return None
    try:
        return gov.publish_manifest(build_manifest(definition))
    except Exception as exc:  # el agente sigue aunque el portal no responda
        log.warning("No se pudo publicar el manifiesto: %s", exc)
        return None


def value(kind: str, **kwargs: Any) -> None:
    if state.enabled:
        gov.value(kind, **kwargs)


def feedback(trace_id: str, rating: int) -> None:
    if state.enabled:
        gov.feedback(trace_id, rating)


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def startup(definition: AgentDefinition) -> bool:
    with session_scope() as session:
        connected = configure(session, definition.version)
    if connected:
        publish_manifest(definition)
    return connected
