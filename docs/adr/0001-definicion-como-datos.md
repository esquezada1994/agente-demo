# 0001. El agente es una definición que el motor ejecuta

**Estado:** Aceptada · **Fecha:** 2026-10-20

## Contexto

Hoy el agente lo arma el equipo técnico. Mañana el cliente debería poder armar
sus propios agentes en un canvas visual, como en Langflow, Flowise o Copilot
Studio. Si el agente fuera código fijo, ese paso obligaría a reescribirlo.

## Decisión

El agente es un documento JSON (`AgentDefinition`) que tiene persona, modelos,
instrucciones, herramientas, fuentes, políticas, valor por resultado y uno o
más **flujos**. Cada flujo es un grafo de nodos tipados con conexiones
condicionales. El motor lo compila a un `StateGraph` de LangGraph al arrancar.

- **Tipos de nodo cerrados** (`input_guard`, `retrieve`, `llm`, `tools`,
  `validate`, `approval`, `respond`). Cada uno declara su etapa de gobierno y
  sus salidas.
- **Herramientas registradas en código.** La definición elige cuáles usar,
  pero no puede crear una nueva.
- **Validación al publicar:** salidas cubiertas, nodos alcanzables desde START,
  camino a END y herramientas existentes. Un grafo roto no se activa.
- **Versionado:** cada publicación es una versión nueva. La activa vive en la
  base y se publica en el portal como manifiesto.
- Cada nodo guarda `position`. El motor la ignora; la usará el canvas.

## Consecuencias

- El canvas es una pantalla nueva sobre la misma API (`GET /api/catalog` da los
  tipos de nodo y las herramientas con su esquema; `PUT /api/definition` publica).
- Todo agente armado así nace gobernado: el span de cada etapa lo abre el nodo.
- La lógica que no cabe en un nodo genérico se agrega como un tipo de nodo nuevo
  en código, revisado por el equipo técnico.
