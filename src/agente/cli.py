"""Línea de comandos del agente.

    agente init --empresa "Ferretería Sur" --admin ana@ferreteriasur.ec \\
        [--plataforma http://portal:8000 --enroll ge_…] [--sin-datos-demo]
    agente enroll --plataforma http://portal:8000 --token ge_…
    agente prepare-reminders --limit 10
    agente simulate-payments --days 7
    agente demo-traffic --conversations 20     # tráfico de prueba (modelo simulado)
"""

from __future__ import annotations

import random
from typing import Annotated

import typer
from sqlalchemy import select

from agente import migrations, services
from agente.config import get_settings
from agente.db import Setting, User, session_scope
from agente.domain.erp import seed_erp
from agente.engine import governance, store
from agente.knowledge.seed import seed_documents
from agente.security import generate_password, hash_password

app = typer.Typer(help="Agente de cobranza preventiva", no_args_is_help=True)


@app.command()
def migrate() -> None:
    """Aplica las migraciones pendientes."""
    migrations.upgrade()
    typer.secho("Base de datos al día.", fg=typer.colors.GREEN)


@app.command()
def init(
    empresa: Annotated[str, typer.Option(help="Nombre de la empresa cliente")],
    admin: Annotated[str, typer.Option(help="Correo del primer administrador")],
    nombre: Annotated[str, typer.Option(help="Nombre del administrador")] = "Administrador",
    plataforma: Annotated[
        str | None, typer.Option(help="URL de la API del portal de gobernanza")
    ] = None,
    enroll_token: Annotated[
        str | None, typer.Option("--enroll", help="Token de enrolamiento del portal")
    ] = None,
    datos_demo: Annotated[bool, typer.Option("--datos-demo/--sin-datos-demo")] = True,
) -> None:
    """Crea una instalación nueva para una empresa: base, primer usuario,
    definición del agente con su nombre, conocimiento inicial y (opcional)
    la conexión con el portal de gobernanza."""
    migrations.upgrade()
    with session_scope() as session:
        email = admin.strip().lower()
        password = None
        if session.scalar(select(User).where(User.email == email)) is None:
            password = generate_password()
            session.add(
                User(email=email, name=nombre, role="admin", password_hash=hash_password(password))
            )
        branding = session.get(Setting, "branding") or Setting(key="branding", value={})
        branding.value = {"company": empresa, "color": branding.value.get("color", "#0f766e")}
        session.add(branding)

        base = store.load_file().model_dump(mode="json", by_alias=True)
        base["persona"]["company"] = empresa
        definition = store.publish(session, base, None)
        docs = seed_documents(session)
        customers = seed_erp(session, services.today()) if datos_demo else 0

    typer.secho(
        f"Empresa: {empresa} · agente {definition.name} v{definition.version}",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"Conocimiento inicial: {docs} documentos · clientes de demostración: {customers}")
    if password:
        typer.secho(
            f"Usuario administrador: {email}\nContraseña temporal (se muestra una sola vez, "
            f"se cambia al entrar): {password}",
            fg=typer.colors.YELLOW,
        )
    if enroll_token:
        url = plataforma or get_settings().plataforma_url
        if not url:
            raise typer.BadParameter("Falta --plataforma (o PLATAFORMA_URL)")
        enroll(url, enroll_token)


@app.command()
def enroll(
    plataforma: Annotated[str, typer.Option(help="URL de la API del portal")],
    token: Annotated[str, typer.Option(help="Token de enrolamiento (ge_…)")],
) -> None:
    """Conecta el agente al portal de gobernanza y publica su manifiesto."""
    with session_scope() as session:
        info = governance.enroll(session, plataforma, token, get_settings().environment_name)
    with session_scope() as session:
        definition = store.active(session)
        governance.configure(session, definition.version)
    result = governance.publish_manifest(definition)
    typer.secho(
        f"Conectado al portal: {info['solution_name']} ({info['solution']}) en la empresa {info['tenant']}",
        fg=typer.colors.GREEN,
    )
    if result:
        typer.echo(
            f"Manifiesto v{result['version']} publicado: {result['sources_registered']} fuentes nuevas, "
            f"{result['sources_linked']} asociaciones"
        )
    _flush()


def _startup() -> None:
    with session_scope() as session:
        definition = store.active(session)
        governance.configure(session, definition.version)


def _flush() -> None:
    import plataforma_sdk as gov

    gov.shutdown()


@app.command("prepare-reminders")
def prepare_reminders(limit: int = 10) -> None:
    """Redacta recordatorios para los clientes prioritarios (quedan para aprobar)."""
    _startup()
    with session_scope() as session:
        created = services.prepare_reminders(session, limit)
    typer.secho(f"{created} recordatorios en la bandeja de aprobación", fg=typer.colors.GREEN)
    _flush()


@app.command("simulate-payments")
def simulate_payments(days: int = 7) -> None:
    """SIMULACIÓN: avanza N días y registra los pagos de las promesas cumplidas."""
    _startup()
    with session_scope() as session:
        result = services.simulate_payments(session, days)
    typer.echo(result)
    _flush()


MESSAGES = [
    "Hola, ¿cuánto debo?",
    "¿Cuál es mi saldo pendiente?",
    "Puedo pagar ${amount} el viernes",
    "Les pago ${amount} mañana",
    "¿Cómo puedo pagar por transferencia?",
    "Envíenme la factura por favor",
    "Ya pagué esa factura",
    "No puedo pagar todo, ¿puedo en 3 cuotas?",
    "Quiero hablar con una persona",
    "¿Dónde envío el comprobante de pago?",
]


@app.command("demo-traffic")
def demo_traffic(conversations: int = 20, seed: int = 3) -> None:
    """Genera conversaciones de prueba (útil para ver el recorrido en el portal)."""
    _startup()
    rng = random.Random(seed)  # noqa: S311 - tráfico de prueba
    with session_scope() as session:
        from agente.domain import collections

        items = [i for i in collections.portfolio(session, services.today()) if i.total_balance > 0]
    if not items:
        typer.secho(
            "No hay clientes con saldo pendiente en la base del agente. "
            "Si se borró la base (make reset), ejecuta `make init` con un token nuevo.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    for _ in range(conversations):
        item = rng.choice(items)
        # El monto nunca supera el saldo: la herramienta rechazaría la promesa.
        amount = max(min(rng.randint(40, 400), int(item.total_balance)), 1)
        text = rng.choice(MESSAGES).replace("{amount}", str(amount))
        with session_scope() as session:
            reply = services.chat(session, item.customer.id, text)
        tools = list(reply.tools)
        # Un modelo real pide confirmar monto y fecha antes de registrar la
        # promesa (así lo dicen sus instrucciones): el cliente confirma.
        is_promise = "$" in text and ("pag" in text.lower())
        for _attempt in range(2):
            if not is_promise or "registrar_promesa" in tools or reply.outcome == "escalated":
                break
            with session_scope() as session:
                reply = services.chat(
                    session,
                    item.customer.id,
                    f"Sí, confirmo: pagaré ${amount} en la fecha que le indiqué.",
                    reply.conversation_id,
                )
            tools += reply.tools
        if rng.random() < 0.3:
            with session_scope() as session:
                services.rate(session, reply.message_id, 1 if reply.outcome == "resolved" else -1)
        used = f" [{', '.join(tools)}]" if tools else ""
        typer.echo(f"{item.customer.code}: {text} → {reply.outcome}{used}")
    _flush()


if __name__ == "__main__":
    app()
