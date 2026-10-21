"""La definición se valida como lo haría un canvas antes de publicar."""

import copy
import json

import pytest
from pydantic import ValidationError

from agente.engine import governance
from agente.engine.definition import AgentDefinition
from agente.engine.store import DEFINITIONS_DIR, load_file


def _raw() -> dict:
    return json.loads((DEFINITIONS_DIR / "cobranza-preventiva.json").read_text(encoding="utf-8"))


def test_shipped_definition_is_valid() -> None:
    d = load_file()
    assert d.flows["chat"].nodes[0].type == "input_guard"
    assert {t.name for t in d.tools} >= {"registrar_promesa", "consultar_estado_cuenta"}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["flows"]["chat"]["edges"].pop(2), "debe conectar las salidas"),
        (
            lambda d: d["flows"]["chat"]["edges"].append({"from": "buscar", "to": "nadie"}),
            "inexistente",
        ),
        (lambda d: d["tools"].append({"name": "borrar_deuda"}), "no registradas"),
        (
            lambda d: d["flows"]["chat"]["nodes"][2]["config"]["tools"].append("enviar_sms"),
            "no está en la lista",
        ),
        (lambda d: d["flows"]["chat"]["edges"].pop(0), "exactamente una conexión desde START"),
        (
            lambda d: d["flows"]["chat"]["nodes"].append({"id": "suelto", "type": "respond"}),
            "salida",
        ),
    ],
)
def test_broken_graphs_are_rejected(mutate, message) -> None:  # type: ignore[no-untyped-def]
    raw = copy.deepcopy(_raw())
    mutate(raw)
    with pytest.raises(ValidationError, match=message):
        AgentDefinition.model_validate(raw)


def test_manifest_has_no_instructions_and_declares_controls() -> None:
    manifest = governance.build_manifest(load_file())
    assert "instructions" not in manifest and "Eres" not in json.dumps(manifest)
    assert manifest["human_in_the_loop"] is True
    assert {"personal_data", "prompt_injection", "grounding", "policy"} <= set(
        manifest["validation"]
    )
    approval = {t["name"]: t for t in manifest["tools"]}["solicitar_acuerdo_pago"]
    assert approval["requires_approval"] and approval["writes"]
    assert manifest["models"] == ["gpt-4.1-mini", "gpt-4.1-nano"]
