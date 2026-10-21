"""Configuración por variables de entorno (12-factor).

Todo lo que cambia entre ambientes vive aquí; nada se lee de os.environ en
otro lugar. Los secretos (llave de cifrado, llave del modelo) llegan por
variables de entorno o por el gestor de secretos del ambiente, nunca en el
repositorio.
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class ModelProvider(StrEnum):
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    # Modelo simulado y determinista: permite probar todo el producto sin una
    # cuenta de un proveedor. Nunca se usa en producción (lo impide validate()).
    DEMO = "demo"


DEV_SECRET = "desarrollo-no-usar-en-produccion-0123456789abcdef"  # noqa: S105 - solo local


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Environment = Environment.LOCAL
    app_name: str = "Agente de cobranza"

    database_url: str = "postgresql+psycopg://agente:agente_local@localhost:5433/agente"

    # Firma de sesiones y cifrado de secretos guardados (llave del portal).
    secret_key: SecretStr = SecretStr(DEV_SECRET)

    # Modelo. Sin llave de OpenAI se usa el simulador (solo local).
    model_provider: ModelProvider | None = None
    openai_api_key: SecretStr | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_api_version: str = "2024-10-21"

    # Portal de gobernanza. La llave de ingesta no va aquí: se obtiene con
    # `agente init --enroll <token>` y se guarda cifrada en la base.
    plataforma_url: str | None = None
    environment_name: str = "local"

    # Orígenes del panel web (lista separada por comas).
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5180"])
    # Simulador de cliente en el panel (elegir un deudor y conversar como él).
    # En producción el canal (WhatsApp, web con sesión) identifica al cliente.
    chat_simulator: bool = True

    @field_validator(
        "model_provider",
        "openai_api_key",
        "azure_openai_endpoint",
        "azure_openai_api_key",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        # docker compose pasa "" cuando la variable no está definida.
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @property
    def effective_model_provider(self) -> ModelProvider:
        if self.model_provider is not None:
            return self.model_provider
        if self.openai_api_key:
            return ModelProvider.OPENAI
        if self.azure_openai_api_key and self.azure_openai_endpoint:
            return ModelProvider.AZURE_OPENAI
        return ModelProvider.DEMO

    def validate_for_runtime(self) -> None:
        if self.app_env == Environment.PRODUCTION:
            if self.secret_key.get_secret_value() == DEV_SECRET:
                raise RuntimeError("SECRET_KEY de desarrollo en producción")
            if self.effective_model_provider == ModelProvider.DEMO:
                raise RuntimeError("El modelo simulado no se usa en producción")
            if self.chat_simulator:
                raise RuntimeError("CHAT_SIMULATOR debe ser false en producción")
        if len(self.secret_key.get_secret_value()) < 32:
            raise RuntimeError("SECRET_KEY debe tener al menos 32 caracteres")


@lru_cache
def get_settings() -> Settings:
    return Settings()
