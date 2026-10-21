"""Definiciones versionadas: la activa vive en la base; la inicial, en un archivo.

Publicar una versión nueva valida el grafo completo antes de activarla (un
flujo roto nunca llega a producción) y vuelve a publicar el manifiesto en el
portal, que registra el cambio de versión.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from agente.db import AgentDefinitionRow
from agente.engine.definition import AgentDefinition


def _definitions_dir() -> Path:
    """`definitions/` del directorio de trabajo (contenedor) o del repositorio."""
    configured = os.environ.get("DEFINITIONS_DIR")
    if configured:
        return Path(configured)
    local = Path.cwd() / "definitions"
    return local if local.is_dir() else Path(__file__).resolve().parents[3] / "definitions"


DEFINITIONS_DIR = _definitions_dir()


def load_file(name: str = "cobranza-preventiva") -> AgentDefinition:
    path = DEFINITIONS_DIR / f"{name}.json"
    return AgentDefinition.model_validate(json.loads(path.read_text(encoding="utf-8")))


def active(session: Session) -> AgentDefinition:
    row = session.scalar(select(AgentDefinitionRow).where(AgentDefinitionRow.active.is_(True)))
    if row is None:
        return load_file()
    return AgentDefinition.model_validate(row.content)


def history(session: Session) -> list[AgentDefinitionRow]:
    return list(
        session.scalars(
            select(AgentDefinitionRow).order_by(AgentDefinitionRow.created_at.desc()).limit(20)
        )
    )


def _bump(version: str) -> str:
    major, minor, patch = (int(p) for p in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def publish(
    session: Session, content: dict[str, Any], user_id: uuid.UUID | None, bump: bool = True
) -> AgentDefinition:
    """Valida y activa una definición. Si la versión ya existe, sube el parche."""
    definition = AgentDefinition.model_validate(content)
    existing = {
        v
        for v in session.scalars(
            select(AgentDefinitionRow.version).where(AgentDefinitionRow.agent_id == definition.id)
        )
    }
    if bump:
        while definition.version in existing:
            definition = definition.model_copy(update={"version": _bump(definition.version)})
    session.execute(update(AgentDefinitionRow).values(active=False))
    session.add(
        AgentDefinitionRow(
            agent_id=definition.id,
            version=definition.version,
            content=definition.model_dump(mode="json", by_alias=True),
            active=True,
            published_by=user_id,
        )
    )
    session.flush()
    return definition
