"""Motor: convierte una definición (JSON) en un grafo de LangGraph y lo ejecuta.

Cada tipo de nodo tiene una implementación aquí y abre el span de su etapa
con el SDK de gobierno. Por eso cualquier flujo que se arme con estos nodos,
en JSON hoy o en un canvas mañana, reporta su recorrido completo al portal
sin que nadie escriba código de telemetría.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from functools import wraps
from typing import Annotated, Any, TypedDict

import plataforma_sdk as gov
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.graph import END as LG_END
from langgraph.graph import START as LG_START
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from opentelemetry import context as otel_context
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from agente.db import Approval, Document
from agente.engine import governance, guards
from agente.engine.definition import END, START, AgentDefinition, Flow, NodeSpec
from agente.engine.models import DemoChatModel, get_model, model_name
from agente.tools.registry import TOOLS, ToolContext, ToolError

FALLBACK = "Para darte una respuesta exacta, te paso con un gestor que revisará tu caso."
BLOCKED = "No puedo ayudarte con eso. Puedo informarte tu saldo, registrar una fecha de pago o pasarte con un gestor."


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    route: str
    context: str
    steps: int
    final: str
    violations: list[str]


@dataclass
class RunContext:
    session: Session
    definition: AgentDefinition
    today: date
    tools: ToolContext
    trace: otel_context.Context
    flow: str = "chat"
    reminder: dict[str, Any] = field(default_factory=dict)
    approval_id: uuid.UUID | None = None


NodeFn = Callable[[State, RunnableConfig], dict[str, Any]]


def _ctx(config: RunnableConfig) -> RunContext:
    return config["configurable"]["run"]  # type: ignore[no-any-return]


def _in_trace(fn: NodeFn) -> NodeFn:
    """Cada nodo corre dentro de la traza de la solicitud, aunque LangGraph lo
    ejecute en otro hilo: el contexto se adjunta explícitamente."""

    @wraps(fn)
    def wrapper(state: State, config: RunnableConfig) -> dict[str, Any]:
        token = otel_context.attach(_ctx(config).trace)
        try:
            return fn(state, config)
        finally:
            otel_context.detach(token)

    return wrapper


def _last_human(state: State) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


# --- Nodos ------------------------------------------------------------------------------------


def input_guard(node: NodeSpec) -> NodeFn:
    @_in_trace
    def run(state: State, config: RunnableConfig) -> dict[str, Any]:
        text_in = _last_human(state)
        with gov.validation("input_guard") as v:
            if node.config.get("block_injection", True) and guards.looks_like_injection(text_in):
                v.violation("prompt_injection")
                return {"route": "blocked", "final": BLOCKED, "violations": ["prompt_injection"]}
            found = guards.find_personal_data(text_in)
            if found:
                v.violation("personal_data_input")
                if node.config.get("pii", "mask") == "mask":
                    last = state["messages"][-1]
                    masked = HumanMessage(content=guards.mask_personal_data(text_in), id=last.id)
                    return {"route": "ok", "messages": [masked]}
        return {"route": "ok"}

    return run


# Búsqueda de texto completo. La relevancia que se reporta es la proporción de
# términos de la pregunta (ya normalizados: sin tildes ni palabras vacías y en
# su raíz) que aparecen en el documento: 0 a 1, comparable entre consultas.
SEARCH = text(
    """
    WITH q AS (SELECT tsvector_to_array(to_tsvector('spanish', :q)) AS lex)
    SELECT d.title, d.body,
           (SELECT count(*) FROM unnest(q.lex) l WHERE l = ANY(tsvector_to_array(d.tsv)))::float
             / greatest(cardinality(q.lex), 1) AS score
    FROM documents d, q
    WHERE cardinality(q.lex) > 0
      AND d.tsv @@ to_tsquery('simple',
            array_to_string(ARRAY(SELECT quote_literal(l) FROM unnest(q.lex) l), ' | '))
    ORDER BY score DESC, d.updated_at DESC
    LIMIT :k
    """
)


def retrieve(node: NodeSpec) -> NodeFn:
    source = node.config.get("source", "kb://conocimiento")
    keywords = [k.lower() for k in node.config.get("only_if_keywords", [])]
    top_k = int(node.config.get("top_k", 3))

    @_in_trace
    def run(state: State, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        question = _last_human(state)
        plain = guards._plain(question)
        if keywords and not any(k in plain for k in keywords):
            return {"route": "next", "context": ""}  # no hace falta buscar: sin span
        spec = next((s for s in ctx.definition.sources if s.identifier == source), None)
        updated = ctx.session.scalar(select(func.max(Document.updated_at)))
        with gov.retrieval(
            source=source,
            source_name=spec.name if spec else None,
            source_kind=spec.kind if spec else "document_library",
            source_updated_at=updated,
        ) as r:
            rows = ctx.session.execute(SEARCH, {"q": question, "k": top_k}).all()
            r.record(scores=[float(row.score) for row in rows], documents=len(rows))
        context = "\n".join(f"{row.title}: {row.body}" for row in rows)
        return {"route": "next", "context": context}

    return run


def _system_prompt(ctx: RunContext, context: str, instructions: str | None = None) -> str:
    d = ctx.definition
    base = (instructions or d.instructions).format(
        persona=d.persona.name,
        empresa=d.persona.company,
        tono=d.persona.tone,
        hoy=ctx.today.isoformat(),
        max_dias_promesa=d.policies.max_promise_days,
    )
    if ctx.flow == "reminder":
        base = "[recordatorio]\n" + base
    if context:
        base += (
            f"\n\n[contexto]\n{context}\n[/contexto]\nResponde con este contexto cuando aplique."
        )
    return base


def _tools_for(ctx: RunContext, names: list[str]) -> list[StructuredTool]:
    tools = []
    for name in names:
        registered = TOOLS[name]
        spec = ctx.definition.tool(name)
        tools.append(
            StructuredTool.from_function(
                func=lambda **_: None,  # el nodo "tools" ejecuta; aquí solo el contrato
                name=name,
                description=spec.description or registered.description,
                args_schema=registered.args,
            )
        )
    return tools


def llm(node: NodeSpec) -> NodeFn:
    key = node.config.get("model", "main")
    tool_names: list[str] = list(node.config.get("tools", []))
    max_steps = int(node.config.get("max_steps", 4))

    @_in_trace
    def run(state: State, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        configured = getattr(ctx.definition.models, key) or ctx.definition.models.main
        model = get_model(configured)
        if isinstance(model, DemoChatModel):
            model = model.model_copy(update={"today": ctx.today})
        bound = model.bind_tools(_tools_for(ctx, tool_names)) if tool_names else model
        system = _system_prompt(ctx, state.get("context", ""), node.config.get("instructions"))
        prompt: list[BaseMessage] = [SystemMessage(system)]
        prompt += state.get("messages", [])
        steps = state.get("steps", 0) + 1
        with gov.model_call(model_name(configured)) as m:
            response = bound.invoke(prompt)
            usage = getattr(response, "usage_metadata", None) or {}
            details = usage.get("input_token_details") or {}
            m.record(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_read_tokens=details.get("cache_read", 0) or 0,
                response_model=(response.response_metadata or {}).get("model_name"),
            )
        calls = getattr(response, "tool_calls", None) or []
        if calls and steps < max_steps:
            return {"route": "tool_calls", "messages": [response], "steps": steps}
        content = str(response.content) if not calls else FALLBACK
        return {
            "route": "final",
            "messages": [AIMessage(content=content)],
            "steps": steps,
            "final": content,
        }

    return run


def tools(node: NodeSpec) -> NodeFn:
    @_in_trace
    def run(state: State, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        last = state["messages"][-1]
        results: list[ToolMessage] = []
        for call in getattr(last, "tool_calls", []) or []:
            name = call["name"]
            registered = TOOLS.get(name)
            allowed = registered is not None and any(t.name == name for t in ctx.definition.tools)
            source = None
            if registered is not None and allowed:
                source = ctx.definition.tool(name).source or registered.source
            with gov.tool(name if allowed else "desconocida", source=source) as t:
                try:
                    if registered is None or not allowed:
                        raise ToolError("Herramienta no permitida")
                    args = registered.args.model_validate(call.get("args") or {})
                    with ctx.session.begin_nested():  # si falla, no deja cambios a medias
                        output = registered.handler(ctx.tools, args)
                except (ToolError, ValidationError) as exc:
                    t.error("tool_error")
                    message = str(exc) if isinstance(exc, ToolError) else "Parámetros inválidos"
                    output = {"error": message}
            results.append(
                ToolMessage(
                    content=json.dumps(output, ensure_ascii=False),
                    tool_call_id=call["id"],
                    name=name,
                )
            )
        return {"route": "next", "messages": results}

    return run


def validate(node: NodeSpec) -> NodeFn:
    checks = set(node.config.get("checks", ["personal_data", "policy", "grounding"]))

    @_in_trace
    def run(state: State, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        answer = state.get("final") or ""
        violations: list[str] = []
        with gov.validation("output_guard") as v:
            if "personal_data" in checks and guards.find_personal_data(answer):
                violations.append("personal_data")
                answer = guards.mask_personal_data(answer)
            if "policy" in checks and guards.unauthorized_offer(answer):
                violations.append("unauthorized_offer")
                answer = FALLBACK
                ctx.tools.escalated = True
            if "grounding" in checks and ctx.flow == "chat":
                evidence = (
                    " ".join(
                        str(m.content)
                        for m in state.get("messages", [])
                        if isinstance(m, ToolMessage)
                    )
                    + " "
                    + " ".join(
                        str(m.content)
                        for m in state.get("messages", [])
                        if isinstance(m, HumanMessage)
                    )
                )
                if guards.ungrounded_amounts(answer, evidence):
                    violations.append("ungrounded_amount")
                    answer = FALLBACK
                    ctx.tools.escalated = True
            for category in violations:
                v.violation(category)
        update: dict[str, Any] = {"route": "next", "final": answer, "violations": violations}
        if violations:
            update["messages"] = [AIMessage(content=answer)]
        return update

    return run


def approval(node: NodeSpec) -> NodeFn:
    @_in_trace
    def run(state: State, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        with gov.tool("solicitar_aprobacion", source="agente://cobranza/recordatorios"):
            row = Approval(
                kind=node.config.get("kind", "reminder"),
                customer_id=ctx.tools.customer_id,
                payload={
                    "texto": state.get("final", ""),
                    "canal": node.config.get("channel", "whatsapp"),
                    **{
                        k: ctx.reminder[k]
                        for k in ("tipo", "saldo", "razones")
                        if k in ctx.reminder
                    },
                },
                reason=",".join(ctx.reminder.get("razones", [])) or None,
                trace_id=ctx.tools.trace_id,
            )
            ctx.session.add(row)
            ctx.session.flush()
            ctx.approval_id = row.id
        return {"route": "next"}

    return run


def respond(node: NodeSpec) -> NodeFn:
    def run(state: State, config: RunnableConfig) -> dict[str, Any]:
        return {"route": "next", "final": state.get("final") or FALLBACK}

    return run


IMPLEMENTATIONS: dict[str, Callable[[NodeSpec], NodeFn]] = {
    "input_guard": input_guard,
    "retrieve": retrieve,
    "llm": llm,
    "tools": tools,
    "validate": validate,
    "approval": approval,
    "respond": respond,
}


def compile_flow(flow: Flow) -> Any:
    graph = StateGraph(State)
    for node in flow.nodes:
        graph.add_node(node.id, IMPLEMENTATIONS[node.type](node))  # type: ignore[call-overload]

    def target(name: str) -> str:
        return LG_END if name == END else name

    for source in {e.source for e in flow.edges}:
        outgoing = [e for e in flow.edges if e.source == source]
        if source == START:
            graph.add_edge(LG_START, target(outgoing[0].target))
        elif len(outgoing) == 1:
            graph.add_edge(source, target(outgoing[0].target))
        else:
            mapping = {e.when or "next": target(e.target) for e in outgoing}
            graph.add_conditional_edges(source, lambda s: s["route"], mapping)  # type: ignore[arg-type]
    return graph.compile()


_compiled: dict[tuple[str, str, str], Any] = {}


def compiled(definition: AgentDefinition, flow: str) -> Any:
    key = (definition.id, definition.version, flow)
    if key not in _compiled:
        _compiled[key] = compile_flow(definition.flows[flow])
    return _compiled[key]


# --- Ejecución -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatResult:
    answer: str
    trace_id: str
    outcome: str
    violations: list[str]
    tools: list[str]


def _emit_value(
    definition: AgentDefinition, tool_ctx: ToolContext, trace_id: str, outcome: str
) -> None:
    for event in tool_ctx.events:
        governance.value(
            event["kind"],
            amount=event.get("amount"),
            quantity=event.get("quantity"),
            label=event.get("label"),
            event_id=event.get("event_id"),
            trace_id=trace_id,
        )
    if outcome == "resolved":
        governance.value(
            "time_saved",
            quantity=definition.value.hours_per_resolved_conversation,
            label="conversacion_resuelta",
            event_id=f"conversacion-{trace_id}",
            trace_id=trace_id,
        )
        governance.value(
            "task_completed", quantity=1, event_id=f"tarea-{trace_id}", trace_id=trace_id
        )


def run_chat(
    session: Session,
    definition: AgentDefinition,
    customer_id: uuid.UUID,
    history: list[BaseMessage],
    message: str,
    today: date,
    channel: str = "web",
) -> ChatResult:
    with gov.request("chat", channel=channel) as req:
        tool_ctx = ToolContext(
            session=session,
            customer_id=customer_id,
            today=today,
            trace_id=req.trace_id,
            max_promise_days=definition.policies.max_promise_days,
        )
        run = RunContext(session, definition, today, tool_ctx, otel_context.get_current())
        state = compiled(definition, "chat").invoke(
            {"messages": [*history, HumanMessage(content=message)], "steps": 0},
            config={"configurable": {"run": run}, "recursion_limit": 25},
        )
        outcome = "escalated" if tool_ctx.escalated else "resolved"
        req.outcome(outcome)
        used = [
            m.name or ""
            for m in state.get("messages", [])
            if isinstance(m, ToolMessage) and m not in history
        ]
        result = ChatResult(
            answer=state.get("final") or FALLBACK,
            trace_id=req.trace_id,
            outcome=outcome,
            violations=state.get("violations", []),
            tools=used,
        )
    _emit_value(definition, tool_ctx, result.trace_id, outcome)
    return result


def run_reminder(
    session: Session,
    definition: AgentDefinition,
    customer_id: uuid.UUID,
    facts: dict[str, Any],
    today: date,
) -> uuid.UUID | None:
    """Redacta un recordatorio y lo deja en la bandeja de aprobación."""
    if "reminder" not in definition.flows:
        return None
    with gov.request("reminder", channel="batch") as req:
        tool_ctx = ToolContext(
            session=session, customer_id=customer_id, today=today, trace_id=req.trace_id
        )
        run = RunContext(
            session,
            definition,
            today,
            tool_ctx,
            otel_context.get_current(),
            flow="reminder",
            reminder=facts,
        )
        compiled(definition, "reminder").invoke(
            {
                "messages": [
                    HumanMessage(content=json.dumps(facts, ensure_ascii=False, default=str))
                ],
                "steps": 0,
            },
            config={"configurable": {"run": run}, "recursion_limit": 10},
        )
        req.outcome("resolved")
        return run.approval_id


def send_approved(session: Session, definition: AgentDefinition, approval_row: Approval) -> str:
    """Envía (simulado) un recordatorio aprobado y registra el trabajo evitado."""
    with gov.request("send_reminder", channel=approval_row.payload.get("canal", "whatsapp")) as req:
        with gov.tool(
            "enviar_recordatorio", source=f"canal://{approval_row.payload.get('canal', 'whatsapp')}"
        ):
            pass  # en producción: API del canal (Meta Cloud API para WhatsApp, correo…)
        req.outcome("resolved")
        trace_id = req.trace_id
    governance.value(
        "time_saved",
        quantity=definition.value.hours_per_reminder,
        label="recordatorio",
        event_id=f"recordatorio-{approval_row.id}",
        trace_id=trace_id,
    )
    return trace_id
