"""API del agente (FastAPI).

La consola web y el simulador de cliente la usan. Endpoints síncronos a
propósito: el motor (LangGraph) y la base se usan de forma síncrona y FastAPI
los ejecuta en su grupo de hilos.
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from agente import services
from agente.config import get_settings
from agente.db import (
    Approval,
    Conversation,
    Document,
    ErpCustomer,
    Message,
    Setting,
    User,
    session_scope,
)
from agente.domain import collections
from agente.engine import governance, store
from agente.engine.definition import NODE_TYPES
from agente.security import (
    COOKIE,
    SESSION_HOURS,
    check_password_policy,
    create_session_token,
    generate_password,
    hash_password,
    read_session_token,
    verify_password,
)
from agente.tools.registry import TOOLS

log = logging.getLogger("agente")


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    settings = get_settings()
    settings.validate_for_runtime()
    with session_scope() as session:
        definition = store.active(session)
    connected = governance.startup(definition)
    log.info("agente_iniciado version=%s portal=%s", definition.version, connected)
    yield


def get_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def current_user(
    session: SessionDep, agente_sesion: Annotated[str | None, Cookie()] = None
) -> User:
    claims = read_session_token(agente_sesion) if agente_sesion else None
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "auth.required")
    user = session.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "auth.required")
    return user


UserDep = Annotated[User, Depends(current_user)]


def admin_user(user: UserDep) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "auth.admin_required")
    return user


AdminDep = Annotated[User, Depends(admin_user)]


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Agente de cobranza", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(services.NotFound)
    async def _not_found(_: Request, exc: services.NotFound) -> Response:
        return _json(404, {"detail": str(exc)})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # --- Sesión ---------------------------------------------------------------------

    class LoginIn(BaseModel):
        email: EmailStr
        password: str

    class UserOut(BaseModel):
        id: uuid.UUID
        email: str
        name: str
        role: str
        must_change_password: bool

    @app.post("/api/auth/login", response_model=UserOut)
    def login(body: LoginIn, response: Response, session: SessionDep) -> User:
        user = session.scalar(select(User).where(User.email == body.email.lower()))
        if (
            user is None
            or not user.active
            or not verify_password(body.password, user.password_hash)
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "auth.invalid_credentials")
        user.last_login_at = datetime.now(UTC)
        response.set_cookie(
            COOKIE,
            create_session_token(user.id, user.role),
            max_age=SESSION_HOURS * 3600,
            httponly=True,
            samesite="lax",
            secure=settings.app_env == "production",
        )
        return user

    @app.post("/api/auth/logout", status_code=204)
    def logout(response: Response) -> None:
        response.delete_cookie(COOKIE)

    @app.get("/api/auth/me", response_model=UserOut)
    def me(user: UserDep) -> User:
        return user

    class PasswordIn(BaseModel):
        current: str
        new: str

    @app.post("/api/auth/password", status_code=204)
    def change_password(body: PasswordIn, user: UserDep) -> None:
        if not verify_password(body.current, user.password_hash):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "auth.wrong_password")
        try:
            check_password_policy(body.new)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        user.password_hash = hash_password(body.new)
        user.must_change_password = False

    # --- Inicio y cartera ---------------------------------------------------------------

    @app.get("/api/dashboard")
    def dashboard(_: UserDep, session: SessionDep) -> dict[str, Any]:
        return services.dashboard(session)

    @app.get("/api/portfolio")
    def portfolio(_: UserDep, session: SessionDep) -> list[dict[str, Any]]:
        return [
            {
                "customer_id": str(i.customer.id),
                "code": i.customer.code,
                "name": i.customer.name,
                "segment": i.customer.segment,
                "total_balance": str(i.total_balance),
                "overdue_balance": str(i.overdue_balance),
                "max_days_overdue": i.max_days_overdue,
                "next_due_in": i.next_due_in,
                "invoices": len(i.invoices),
                "action": i.action,
                "score": i.score,
                "reasons": i.reasons,
                "pending_approval": i.pending_approval,
                "open_promise": {
                    "amount": str(i.open_promise.amount),
                    "date": i.open_promise.promised_date.isoformat(),
                }
                if i.open_promise
                else None,
            }
            for i in collections.portfolio(session, services.today())
        ]

    class RemindersIn(BaseModel):
        limit: int = Field(default=10, ge=1, le=50)

    @app.post("/api/portfolio/reminders")
    def prepare_reminders(body: RemindersIn, _: UserDep, session: SessionDep) -> dict[str, int]:
        return {"created": services.prepare_reminders(session, body.limit)}

    class SimulateIn(BaseModel):
        days_ahead: int = Field(default=7, ge=0, le=30)

    @app.post("/api/simulation/payments")
    def simulate(body: SimulateIn, _: AdminDep, session: SessionDep) -> dict[str, Any]:
        if not settings.chat_simulator:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return services.simulate_payments(session, body.days_ahead)

    # --- Aprobaciones -----------------------------------------------------------------------

    @app.get("/api/approvals")
    def approvals(
        _: UserDep,
        session: SessionDep,
        state: Literal["pending", "approved", "rejected"] = "pending",
    ) -> list[dict[str, Any]]:
        rows = session.execute(
            select(Approval, ErpCustomer.name, ErpCustomer.code)
            .join(ErpCustomer, ErpCustomer.id == Approval.customer_id)
            .where(Approval.status == state)
            .order_by(Approval.created_at.desc())
            .limit(100)
        ).all()
        return [
            {
                "id": str(a.id),
                "kind": a.kind,
                "status": a.status,
                "customer": name,
                "customer_code": code,
                "payload": a.payload,
                "reason": a.reason,
                "created_at": a.created_at.isoformat(),
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
            }
            for a, name, code in rows
        ]

    class DecisionIn(BaseModel):
        approve: bool
        text: str | None = Field(default=None, max_length=1000)
        note: str | None = Field(default=None, max_length=300)

    @app.post("/api/approvals/{approval_id}/decision")
    def decide(
        approval_id: uuid.UUID, body: DecisionIn, user: UserDep, session: SessionDep
    ) -> dict[str, str]:
        try:
            approval = services.decide(
                session, approval_id, body.approve, user.id, body.text, body.note
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return {"status": approval.status}

    # --- Simulador de cliente y conversaciones -----------------------------------------------

    @app.get("/api/customers")
    def customers(_: UserDep, session: SessionDep) -> list[dict[str, str]]:
        return [
            {"id": str(c.id), "code": c.code, "name": c.name}
            for c in session.scalars(select(ErpCustomer).order_by(ErpCustomer.name))
        ]

    class ChatIn(BaseModel):
        customer_id: uuid.UUID
        message: str = Field(min_length=1, max_length=2000)
        conversation_id: uuid.UUID | None = None

    @app.post("/api/simulator/chat")
    def simulator_chat(body: ChatIn, _: UserDep, session: SessionDep) -> dict[str, Any]:
        if not settings.chat_simulator:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        reply = services.chat(
            session, body.customer_id, body.message, body.conversation_id, channel="web"
        )
        return {
            "conversation_id": str(reply.conversation_id),
            "message_id": str(reply.message_id),
            "answer": reply.answer,
            "outcome": reply.outcome,
            "trace_id": reply.trace_id,
            "tools": reply.tools,
            "violations": reply.violations,
        }

    class RatingIn(BaseModel):
        rating: Literal[1, -1]

    @app.post("/api/messages/{message_id}/feedback", status_code=204)
    def feedback(message_id: uuid.UUID, body: RatingIn, _: UserDep, session: SessionDep) -> None:
        services.rate(session, message_id, body.rating)

    @app.get("/api/conversations")
    def conversations(_: UserDep, session: SessionDep) -> list[dict[str, Any]]:
        rows = session.execute(
            select(Conversation, ErpCustomer.name)
            .join(ErpCustomer, ErpCustomer.id == Conversation.customer_id, isouter=True)
            .order_by(Conversation.last_message_at.desc())
            .limit(100)
        ).all()
        return [
            {
                "id": str(c.id),
                "customer": name,
                "channel": c.channel,
                "outcome": c.outcome,
                "started_at": c.started_at.isoformat(),
                "last_message_at": c.last_message_at.isoformat(),
            }
            for c, name in rows
        ]

    @app.get("/api/conversations/{conversation_id}")
    def conversation(
        conversation_id: uuid.UUID, _: UserDep, session: SessionDep
    ) -> list[dict[str, Any]]:
        rows = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "trace_id": m.trace_id,
                "feedback": m.feedback,
                "meta": m.meta,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ]

    # --- Definición del agente (lo que mañana edita el canvas) --------------------------------

    @app.get("/api/definition")
    def definition(_: UserDep, session: SessionDep) -> dict[str, Any]:
        active = store.active(session)
        return {
            "active": active.model_dump(mode="json", by_alias=True),
            "history": [
                {"version": r.version, "active": r.active, "created_at": r.created_at.isoformat()}
                for r in store.history(session)
            ],
            "manifest": governance.build_manifest(active),
        }

    @app.get("/api/catalog")
    def catalog(_: UserDep) -> dict[str, Any]:
        """Lo que se puede usar al armar un agente: tipos de nodo y herramientas."""
        return {
            "node_types": {
                k: {"stage": v.stage, "routes": list(v.routes), "description": v.description}
                for k, v in NODE_TYPES.items()
            },
            "tools": {
                k: {
                    "description": t.description,
                    "writes": t.writes,
                    "requires_approval": t.requires_approval,
                    "source": t.source,
                    "parameters": t.args.model_json_schema(),
                }
                for k, t in TOOLS.items()
            },
        }

    class DefinitionIn(BaseModel):
        content: dict[str, Any]

    @app.post("/api/definition/validate")
    def validate_definition(body: DefinitionIn, _: UserDep) -> dict[str, Any]:
        from agente.engine.definition import AgentDefinition

        try:
            AgentDefinition.model_validate(body.content)
        except ValidationError as exc:
            return {"valid": False, "errors": [e["msg"] for e in exc.errors()]}
        return {"valid": True, "errors": []}

    @app.put("/api/definition")
    def publish_definition(
        body: DefinitionIn, user: AdminDep, session: SessionDep
    ) -> dict[str, Any]:
        try:
            definition = store.publish(session, body.content, user.id)
        except ValidationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, [e["msg"] for e in exc.errors()]
            ) from exc
        governance.state.version = definition.version
        session.flush()
        manifest = governance.publish_manifest(definition)
        return {"version": definition.version, "manifest_published": manifest is not None}

    # --- Conocimiento ------------------------------------------------------------------------

    class DocumentIn(BaseModel):
        title: str = Field(min_length=2, max_length=200)
        body: str = Field(min_length=10, max_length=20000)

    def _doc(d: Document) -> dict[str, Any]:
        return {
            "id": str(d.id),
            "title": d.title,
            "body": d.body,
            "updated_at": d.updated_at.isoformat(),
        }

    @app.get("/api/documents")
    def documents(_: UserDep, session: SessionDep) -> list[dict[str, Any]]:
        return [_doc(d) for d in session.scalars(select(Document).order_by(Document.title))]

    @app.post("/api/documents", status_code=201)
    def create_document(body: DocumentIn, _: AdminDep, session: SessionDep) -> dict[str, Any]:
        document = Document(title=body.title, body=body.body)
        session.add(document)
        session.flush()
        session.refresh(document)
        return _doc(document)

    @app.put("/api/documents/{document_id}")
    def update_document(
        document_id: uuid.UUID, body: DocumentIn, _: AdminDep, session: SessionDep
    ) -> dict[str, Any]:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        document.title, document.body = body.title, body.body
        document.updated_at = datetime.now(UTC)
        session.flush()
        return _doc(document)

    @app.delete("/api/documents/{document_id}", status_code=204)
    def delete_document(document_id: uuid.UUID, _: AdminDep, session: SessionDep) -> None:
        document = session.get(Document, document_id)
        if document is not None:
            session.delete(document)

    # --- Ajustes ------------------------------------------------------------------------------

    @app.get("/api/settings")
    def get_settings_(_: UserDep, session: SessionDep) -> dict[str, Any]:
        branding = session.get(Setting, "branding")
        return {
            "branding": branding.value
            if branding
            else {"company": "Mi empresa", "color": "#0f766e"},
            "governance": governance.connection_info(session),
            "connected": governance.state.enabled,
            "model_provider": settings.effective_model_provider.value,
            "simulator": settings.chat_simulator,
            "platform_url": settings.plataforma_url,
        }

    class BrandingIn(BaseModel):
        company: str = Field(min_length=2, max_length=120)
        color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")

    @app.put("/api/settings/branding")
    def set_branding(body: BrandingIn, _: AdminDep, session: SessionDep) -> dict[str, Any]:
        row = session.get(Setting, "branding") or Setting(key="branding", value={})
        row.value = body.model_dump()
        session.add(row)
        return row.value

    class EnrollIn(BaseModel):
        url: str = Field(pattern=r"^https?://")
        token: str = Field(min_length=10, max_length=200)

    @app.post("/api/settings/governance/enroll")
    def enroll(body: EnrollIn, _: AdminDep, session: SessionDep) -> dict[str, Any]:
        try:
            info = governance.enroll(session, body.url, body.token, settings.environment_name)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No se pudo enrolar: {exc}") from exc
        session.flush()
        definition = store.active(session)
        governance.configure(session, definition.version)
        governance.publish_manifest(definition)
        return info

    class UserIn(BaseModel):
        email: EmailStr
        name: str = Field(min_length=2, max_length=120)
        role: Literal["admin", "gestor"] = "gestor"

    @app.get("/api/users")
    def users(_: AdminDep, session: SessionDep) -> list[dict[str, Any]]:
        return [
            {"id": str(u.id), "email": u.email, "name": u.name, "role": u.role, "active": u.active}
            for u in session.scalars(select(User).order_by(User.name))
        ]

    @app.post("/api/users", status_code=201)
    def create_user(body: UserIn, _: AdminDep, session: SessionDep) -> dict[str, Any]:
        if session.scalar(select(User).where(User.email == body.email.lower())):
            raise HTTPException(status.HTTP_409_CONFLICT, "user.exists")
        password = generate_password()
        session.add(
            User(
                email=body.email.lower(),
                name=body.name,
                role=body.role,
                password_hash=hash_password(password),
            )
        )
        return {"email": body.email.lower(), "temporary_password": password}

    return app


def _json(code: int, body: dict[str, Any]) -> Response:
    import json

    return Response(content=json.dumps(body), status_code=code, media_type="application/json")


app = create_app()
