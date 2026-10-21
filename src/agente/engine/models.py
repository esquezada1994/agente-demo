"""Modelos de lenguaje.

El motor habla con una sola interfaz (BaseChatModel de langchain-core), así
que cambiar de proveedor es configuración:

- openai:        ChatOpenAI (OPENAI_API_KEY)
- azure_openai:  AzureChatOpenAI (el nombre del modelo es el del deployment)
- demo:          un simulador determinista para probar el producto completo sin
                 cuenta de proveedor. Responde con reglas simples y reporta
                 tokens aproximados. Se llama "demo-simulado" en las trazas para
                 que nadie lo confunda con un modelo real. Prohibido en producción.

Los tokens se leen de `usage_metadata`, que cada proveedor llena con lo que
factura: es el dato exacto, no una estimación.
"""

from __future__ import annotations

import contextlib
import json
import random
import re
import time
import unicodedata
import uuid
from collections.abc import Sequence
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

from agente.config import ModelProvider, get_settings

DEMO_MODEL = "demo-simulado"


def model_name(configured: str) -> str:
    """Nombre que se reporta en las trazas."""
    return (
        DEMO_MODEL if get_settings().effective_model_provider == ModelProvider.DEMO else configured
    )


@lru_cache(maxsize=8)
def get_model(name: str) -> BaseChatModel:
    settings = get_settings()
    provider = settings.effective_model_provider
    if provider == ModelProvider.OPENAI:
        from langchain_openai import ChatOpenAI

        assert settings.openai_api_key is not None
        return ChatOpenAI(
            model=name,
            api_key=settings.openai_api_key,
            temperature=0.2,
            timeout=30,
            max_retries=2,
        )
    if provider == ModelProvider.AZURE_OPENAI:
        from langchain_openai import AzureChatOpenAI

        assert settings.azure_openai_api_key is not None
        return AzureChatOpenAI(
            azure_deployment=name,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            temperature=0.2,
            timeout=30,
            max_retries=2,
        )
    return DemoChatModel(latency=settings.app_env != "test")


# --- Simulador ------------------------------------------------------------------------------


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


_WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5}
_AMOUNT = re.compile(
    r"(?:\$|usd|dolares|por)\s*(\d{1,6}(?:[.,]\d{1,2})?)|(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:\$|usd|dolares)"
)


def parse_date(text: str, today: date) -> date | None:
    t = _plain(text)
    if "pasado manana" in t:
        return today + timedelta(days=2)
    if "manana" in t:
        return today + timedelta(days=1)
    if "hoy" in t:
        return today
    match = re.search(r"en (\d{1,2}) dias", t)
    if match:
        return today + timedelta(days=int(match.group(1)))
    for name, weekday in _WEEKDAYS.items():
        if name in t:
            delta = (weekday - today.weekday()) % 7 or 7
            return today + timedelta(days=delta)
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", t)
    if match:
        try:
            return date(today.year, int(match.group(2)), int(match.group(1)))
        except ValueError:
            return None
    return None


def parse_amount(text: str) -> str | None:
    match = _AMOUNT.search(_plain(text))
    if not match:
        return None
    return (match.group(1) or match.group(2)).replace(",", ".")


def _human_date(value: Any) -> str:
    try:
        return date.fromisoformat(str(value)).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def _approx_tokens(messages: Sequence[BaseMessage]) -> int:
    return max(sum(len(str(m.content)) for m in messages) // 4, 1)


class DemoChatModel(BaseChatModel):
    """Simulador con reglas. Suficiente para recorrer todo el producto."""

    tool_names: list[str] = []
    today: date | None = None
    latency: bool = True

    @property
    def _llm_type(self) -> str:
        return DEMO_MODEL

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> DemoChatModel:
        names = [t.name if isinstance(t, BaseTool) else t["function"]["name"] for t in tools]
        return self.model_copy(update={"tool_names": names})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self._respond(messages)
        if self.latency:
            # Latencia simulada (120-350 ms) para que el recorrido muestre cifras
            # plausibles en las demos; las pruebas la desactivan.
            time.sleep(random.uniform(0.12, 0.35))  # noqa: S311
        out = max(len(str(message.content)) // 4, 1) + 20 * len(message.tool_calls)
        message.usage_metadata = {
            "input_tokens": _approx_tokens(messages),
            "output_tokens": out,
            "total_tokens": _approx_tokens(messages) + out,
        }
        message.response_metadata = {"model_name": DEMO_MODEL}
        return ChatResult(generations=[ChatGeneration(message=message)])

    # -- lógica ---------------------------------------------------------------------

    def _call(self, name: str, args: dict[str, Any]) -> AIMessage:
        if name not in self.tool_names:
            return AIMessage(content="Un gestor revisará tu caso y te contactará.")
        return AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}],
        )

    def _respond(self, messages: list[BaseMessage]) -> AIMessage:
        system = next((str(m.content) for m in messages if isinstance(m, SystemMessage)), "")
        today = self.today or date.today()
        last_human = max(
            (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1
        )
        human = str(messages[last_human].content) if last_human >= 0 else ""
        results = [m for m in messages[last_human + 1 :] if isinstance(m, ToolMessage)]

        if "[recordatorio]" in system:
            return AIMessage(content=self._reminder(human))
        if results:
            return self._after_tools(human, results, today)
        return self._first_step(human, system, today)

    def _first_step(self, human: str, system: str, today: date) -> AIMessage:
        t = _plain(human)
        if any(k in t for k in ("persona", "humano", "asesor", "gestor", "hablar con alguien")):
            return self._call("derivar_a_persona", {"motivo": "pide_persona"})
        if any(k in t for k in ("ya pague", "ya cancele", "ya hice el pago")):
            return self._call("reportar_disputa", {"categoria": "ya_pague"})
        if any(k in t for k in ("no reconozco", "no es mia", "esta mal", "incorrecto", "error en")):
            return self._call("reportar_disputa", {"categoria": "monto_incorrecto"})
        if any(k in t for k in ("cuotas", "acuerdo", "no puedo pagar todo", "plazo", "partes")):
            n = re.search(r"(\d{1,2})\s*cuotas", t)
            return self._call(
                "solicitar_acuerdo_pago",
                {"cuotas": int(n.group(1)) if n else 3, "motivo": "liquidez"},
            )
        when = parse_date(human, today)
        if when is not None and any(k in t for k in ("pag", "deposit", "transfer", "cancel")):
            amount = parse_amount(human)
            if amount:
                return self._call("registrar_promesa", {"monto": amount, "fecha": when.isoformat()})
            return self._call("consultar_estado_cuenta", {})
        if "factura" in t:
            return self._call("consultar_estado_cuenta", {})
        if any(
            k in t
            for k in ("cuanto debo", "saldo", "deuda", "estado de cuenta", "pendiente", "debo")
        ):
            return self._call("consultar_estado_cuenta", {})
        if any(
            k in t
            for k in ("donde", "como pago", "formas de pago", "banco", "transferencia", "cuenta")
        ):
            context = re.search(r"\[contexto\](.*?)\[/contexto\]", system, re.S)
            if context and context.group(1).strip():
                first = context.group(1).strip().split("\n")[0]
                return AIMessage(content=f"Según nuestras políticas: {first}")
            return AIMessage(content="Puedo ayudarte con tu saldo, una fecha de pago o un acuerdo.")
        return AIMessage(
            content=(
                "Hola, soy el asistente de cobranza. Puedo decirte tu saldo, registrar una "
                "fecha de pago, enviarte una factura o pasarte con un gestor. ¿Qué necesitas?"
            )
        )

    def _after_tools(self, human: str, results: list[ToolMessage], today: date) -> AIMessage:
        last = results[-1]
        try:
            data = json.loads(str(last.content))
        except json.JSONDecodeError:
            data = {}
        if "error" in data:
            return AIMessage(content=f"No pude completarlo: {data['error']}. ¿Lo revisamos?")
        name = last.name or ""
        t = _plain(human)
        if name == "consultar_estado_cuenta":
            invoices = data.get("facturas", [])
            when = parse_date(human, today)
            if when is not None and "registrar_promesa" in self.tool_names:
                return self._call(
                    "registrar_promesa",
                    {"monto": data.get("total_pendiente", "0"), "fecha": when.isoformat()},
                )
            if "factura" in t and invoices and "enviar_factura" in self.tool_names:
                return self._call("enviar_factura", {"numero": invoices[0]["numero"]})
            if not invoices:
                return AIMessage(content="No tienes saldos pendientes. ¡Gracias por estar al día!")
            overdue = [i for i in invoices if i["dias_vencida"] > 0]
            lines = [f"Tu saldo pendiente es de ${data['total_pendiente']}"]
            if overdue:
                lines.append(f"{len(overdue)} factura(s) están vencidas")
            lines.append("¿Quieres indicarme una fecha de pago?")
            return AIMessage(content=". ".join(lines) + "")
        if name == "registrar_promesa":
            return AIMessage(
                content=(
                    f"Listo, registré tu compromiso de pago de ${data['monto']} para el "
                    f"{_human_date(data['fecha'])}. Te enviaremos un recordatorio. ¡Gracias!"
                )
            )
        if name == "solicitar_acuerdo_pago":
            return AIMessage(
                content="Registré tu pedido de pago en cuotas. Un gestor lo revisará y te responderá."
            )
        if name == "reportar_disputa":
            return AIMessage(
                content="Entiendo. Registré tu caso y un gestor lo revisará con el comprobante."
            )
        if name == "derivar_a_persona":
            return AIMessage(content="Te paso con un gestor, que te contactará en breve.")
        if name == "enviar_factura":
            return AIMessage(content="Te envié la factura a tu correo registrado.")
        return AIMessage(content="Listo.")

    def _reminder(self, facts: str) -> str:
        data: dict[str, Any] = {}
        with contextlib.suppress(json.JSONDecodeError):
            data = json.loads(facts)
        name = str(data.get("nombre", "")).split(" ")[0] or "Hola"
        amount = data.get("saldo", "")
        if data.get("tipo") == "preventive":
            return (
                f"{name}, te recordamos que tu factura por ${amount} vence el "
                f"{_human_date(data.get('vence', 'próximamente'))}. Si ya la pagaste, ignora este mensaje."
            )
        return (
            f"{name}, tienes un saldo vencido de ${amount}. Responde a este mensaje para "
            "indicarnos una fecha de pago o pedir un acuerdo. Estamos para ayudarte."
        )
