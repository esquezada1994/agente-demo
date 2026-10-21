"""API de la consola: sesión, simulador, aprobaciones y definición."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from agente.api.app import create_app
from agente.db import User, session_scope
from agente.engine import store
from agente.security import hash_password


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    with session_scope() as s:
        s.add(
            User(
                email="ana@empresa.com",
                name="Ana",
                role="admin",
                password_hash=hash_password("clave-inicial-1"),
            )
        )
        s.add(
            User(
                email="gestor@empresa.com",
                name="Gus",
                role="gestor",
                password_hash=hash_password("clave-gestor-1"),
                must_change_password=False,
            )
        )
    with TestClient(create_app()) as c:
        yield c


def _login(
    client: TestClient, email: str = "ana@empresa.com", password: str = "clave-inicial-1"
) -> dict[str, Any]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def test_login_cookie_and_password_change(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"email": "ana@empresa.com", "password": "x"}
        ).status_code
        == 401
    )
    user = _login(client)
    assert user["must_change_password"] is True
    weak = client.post("/api/auth/password", json={"current": "clave-inicial-1", "new": "corta"})
    assert weak.status_code == 422
    assert (
        client.post(
            "/api/auth/password", json={"current": "clave-inicial-1", "new": "Nueva-clave-2026"}
        ).status_code
        == 204
    )
    assert client.get("/api/auth/me").json()["must_change_password"] is False


def test_simulator_feedback_and_conversation(client: TestClient) -> None:
    _login(client)
    customer = client.get("/api/customers").json()[0]
    reply = client.post(
        "/api/simulator/chat", json={"customer_id": customer["id"], "message": "¿Cuánto debo?"}
    ).json()
    assert reply["tools"] == ["consultar_estado_cuenta"]
    again = client.post(
        "/api/simulator/chat",
        json={
            "customer_id": customer["id"],
            "message": "Quiero hablar con una persona",
            "conversation_id": reply["conversation_id"],
        },
    ).json()
    assert again["conversation_id"] == reply["conversation_id"] and again["outcome"] == "escalated"
    assert (
        client.post(f"/api/messages/{reply['message_id']}/feedback", json={"rating": 1}).status_code
        == 204
    )
    messages = client.get(f"/api/conversations/{reply['conversation_id']}").json()
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[1]["feedback"] == 1
    listed = client.get("/api/conversations").json()
    assert listed[0]["outcome"] == "escalated"


def test_reminders_approval_flow(client: TestClient) -> None:
    _login(client, "gestor@empresa.com", "clave-gestor-1")
    assert client.post("/api/portfolio/reminders", json={"limit": 2}).json() == {"created": 2}
    pending = client.get("/api/approvals").json()
    assert len(pending) == 2 and pending[0]["payload"]["texto"]
    first, second = pending
    assert client.post(f"/api/approvals/{first['id']}/decision", json={"approve": True}).json() == {
        "status": "approved"
    }
    assert client.post(
        f"/api/approvals/{second['id']}/decision",
        json={"approve": False, "note": "cliente en negociación"},
    ).json() == {"status": "rejected"}
    assert (
        client.post(f"/api/approvals/{first['id']}/decision", json={"approve": True}).status_code
        == 409
    )
    portfolio = client.get("/api/portfolio").json()
    assert portfolio[0]["action"] in {"overdue", "promise_followup", "preventive"}
    dash = client.get("/api/dashboard").json()
    assert dash["pending_approvals"] == 0 and dash["connected"] is False
    # Simular pagos es solo para administradores.
    assert client.post("/api/simulation/payments", json={"days_ahead": 7}).status_code == 403


def test_definition_validate_and_publish(client: TestClient) -> None:
    _login(client)
    current = client.get("/api/definition").json()
    assert current["manifest"]["framework"] == "langgraph"
    broken = current["active"] | {"flows": {"chat": {"nodes": [], "edges": []}}}
    check = client.post("/api/definition/validate", json={"content": broken}).json()
    assert check["valid"] is False and check["errors"]
    assert client.put("/api/definition", json={"content": broken}).status_code == 422

    changed = current["active"] | {"persona": {**current["active"]["persona"], "name": "Valeria"}}
    first = client.put("/api/definition", json={"content": changed}).json()
    second = client.put("/api/definition", json={"content": changed}).json()
    assert first["version"] == "1.0.0" and second["version"] == "1.0.1"
    with session_scope() as s:
        assert store.active(s).persona.name == "Valeria"
    catalog = client.get("/api/catalog").json()
    assert catalog["node_types"]["llm"]["stage"] == "model"
    assert "monto" in catalog["tools"]["registrar_promesa"]["parameters"]["properties"]


def test_gestor_cannot_admin(client: TestClient) -> None:
    _login(client, "gestor@empresa.com", "clave-gestor-1")
    assert client.get("/api/users").status_code == 403
    assert (
        client.put(
            "/api/settings/branding", json={"company": "X S.A.", "color": "#112233"}
        ).status_code
        == 403
    )
