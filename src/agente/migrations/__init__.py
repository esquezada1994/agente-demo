"""Aplicar migraciones desde código (sin alembic.ini en el directorio de trabajo)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

HERE = Path(__file__).resolve().parent


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(HERE))
    return config


def upgrade() -> None:
    command.upgrade(alembic_config(), "head")
