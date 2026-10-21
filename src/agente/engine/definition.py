"""Definición del agente: un documento JSON que el motor ejecuta.

Este es el contrato que permite reemplazar mañana la edición del JSON por un
canvas visual: el canvas edita EXACTAMENTE esta estructura (nodos, conexiones
y configuración) y el motor no cambia. Ver docs/adr/0001-definicion-como-datos.md.

Cada tipo de nodo declara:
- a qué etapa del recorrido de gobierno pertenece (así todo agente armado
  aquí, o en el canvas, nace gobernado);
- qué salidas tiene (rutas): las conexiones deben cubrirlas todas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Id = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,40}$")]
START, END = "START", "END"


@dataclass(frozen=True)
class NodeType:
    stage: str  # etapa del recorrido: input | retrieval | model | tool | validation | response
    routes: tuple[str, ...]
    description: str


NODE_TYPES: dict[str, NodeType] = {
    "input_guard": NodeType(
        "validation",
        ("ok", "blocked"),
        "Revisa la entrada: datos personales y señales de instrucciones maliciosas.",
    ),
    "retrieve": NodeType(
        "retrieval", ("next",), "Busca en la base de conocimiento y registra la relevancia."
    ),
    "llm": NodeType(
        "model",
        ("tool_calls", "final"),
        "Llama al modelo con las herramientas permitidas.",
    ),
    "tools": NodeType("tool", ("next",), "Ejecuta las herramientas que pidió el modelo."),
    "validate": NodeType(
        "validation", ("next",), "Valida la respuesta antes de enviarla (políticas, datos)."
    ),
    "approval": NodeType(
        "tool", ("next",), "Deja la acción propuesta en la bandeja para que una persona decida."
    ),
    "respond": NodeType("response", ("next",), "Cierra la solicitud y registra el resultado."),
}


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Id
    type: Literal["input_guard", "retrieve", "llm", "tools", "validate", "approval", "respond"]
    label: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    # Posición en el canvas (la ignora el motor; la usa el editor visual).
    position: dict[str, float] | None = None


class EdgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str = Field(alias="from")
    target: str = Field(alias="to")
    when: str | None = None


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Id
    description: str | None = None  # si no, la del registro de herramientas
    requires_approval: bool | None = None
    source: str | None = None


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str
    name: str
    kind: str = "other"
    usage: str = "retrieval"
    refresh_frequency: str | None = None
    data_categories: list[str] = Field(default_factory=list)


class ModelsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    main: str = "gpt-4.1-mini"
    small: str | None = "gpt-4.1-nano"


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "Asistente"
    company: str = "la empresa"
    tone: str = "cordial y directo"


class Policies(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_days: int = 180
    contact_hours: str = "08:00-19:00"
    max_promise_days: int = 15
    data_categories: list[str] = Field(default_factory=lambda: ["personal", "financial"])


class ValueSpec(BaseModel):
    """Cuánto trabajo humano reemplaza cada resultado (lo define la empresa)."""

    model_config = ConfigDict(extra="forbid")

    hours_per_resolved_conversation: float = 0.2
    hours_per_reminder: float = 0.08


class Flow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[NodeSpec]
    edges: list[EdgeSpec]

    @model_validator(mode="after")
    def _check_graph(self) -> Flow:
        validate_flow(self)
        return self


class AgentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Id
    version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
    name: str
    description: str
    language: str = "es"
    persona: Persona = Field(default_factory=Persona)
    models: ModelsSpec = Field(default_factory=ModelsSpec)
    instructions: str
    tools: list[ToolSpec] = Field(default_factory=list)
    sources: list[SourceSpec] = Field(default_factory=list)
    policies: Policies = Field(default_factory=Policies)
    value: ValueSpec = Field(default_factory=ValueSpec)
    # Flujos: "chat" atiende a un cliente; "reminder" redacta un recordatorio.
    flows: dict[str, Flow]

    @model_validator(mode="after")
    def _check_tools(self) -> AgentDefinition:
        from agente.tools.registry import TOOLS  # registro en código (evita ciclos)

        names = [t.name for t in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("Herramienta repetida en la definición")
        unknown = [n for n in names if n not in TOOLS]
        if unknown:
            raise ValueError(f"Herramientas no registradas: {', '.join(unknown)}")
        for flow_name, flow in self.flows.items():
            for node in flow.nodes:
                for tool in node.config.get("tools", []):
                    if tool not in names:
                        raise ValueError(
                            f"{flow_name}.{node.id} usa la herramienta {tool}, "
                            "que no está en la lista de herramientas"
                        )
        if "chat" not in self.flows:
            raise ValueError("Falta el flujo 'chat'")
        return self

    def tool(self, name: str) -> ToolSpec:
        return next(t for t in self.tools if t.name == name)


def validate_flow(flow: Flow) -> None:
    """Reglas que hacen que un grafo dibujado en un canvas sea ejecutable."""
    ids = [n.id for n in flow.nodes]
    if len(set(ids)) != len(ids):
        raise ValueError("Hay nodos con el mismo id")
    known = set(ids) | {START, END}
    for edge in flow.edges:
        if edge.source not in known or edge.target not in known:
            raise ValueError(f"Conexión con un nodo inexistente: {edge.source} → {edge.target}")
        if edge.target == START or edge.source == END:
            raise ValueError("START no recibe conexiones y END no tiene salidas")
    starts = [e for e in flow.edges if e.source == START]
    if len(starts) != 1:
        raise ValueError("El flujo debe tener exactamente una conexión desde START")
    by_id = {n.id: n for n in flow.nodes}
    for node in flow.nodes:
        routes = NODE_TYPES[node.type].routes
        outgoing = [e for e in flow.edges if e.source == node.id]
        if routes == ("next",):
            if len(outgoing) != 1 or outgoing[0].when not in (None, "next"):
                raise ValueError(f"{node.id} necesita exactamente una salida")
        else:
            covered = {e.when for e in outgoing}
            if covered != set(routes):
                raise ValueError(
                    f"{node.id} ({node.type}) debe conectar las salidas {', '.join(routes)}"
                )
    # Todo nodo alcanzable desde START y con camino a END.
    graph: dict[str, list[str]] = {}
    for e in flow.edges:
        graph.setdefault(e.source, []).append(e.target)
    seen, stack = set(), [START]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(graph.get(current, []))
    unreachable = set(by_id) - seen
    if unreachable:
        raise ValueError(f"Nodos sin camino desde START: {', '.join(sorted(unreachable))}")
    if END not in seen:
        raise ValueError("El flujo no llega a END")


def stages_in(definition: AgentDefinition) -> set[str]:
    return {NODE_TYPES[n.type].stage for f in definition.flows.values() for n in f.nodes}
