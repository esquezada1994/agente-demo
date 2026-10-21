# 0002. LangGraph como motor y modelos detrás de una interfaz común

**Estado:** Aceptada · **Fecha:** 2026-10-20

## Decisión

- **LangGraph** (MIT) ejecuta los flujos. Es el marco de agentes más usado en
  producción y modela bien lo que este agente necesita: grafos con ciclos
  (modelo ⇄ herramientas), rutas condicionales y estado explícito.
- **langchain-core** da la interfaz `BaseChatModel`. OpenAI, Azure OpenAI u
  otro proveedor es configuración, no código.
- **Tokens desde `usage_metadata`**, que el proveedor llena con lo que factura.
  Es el dato exacto que se reporta al portal.
- **Dos modelos por definición:** el principal para conversar y uno
  económico para redactar recordatorios.
- **Modelo simulado** (`demo-simulado`) para probar sin cuenta de proveedor:
  reglas deterministas, latencia y tokens aproximados. Prohibido en producción.

## Alternativas

- **PydanticAI:** más simple y tipado, pero con menos adopción. Se puede
  agregar como otro motor porque la definición no depende de LangGraph.
- **Checkpointer de LangGraph para pausar el grafo en la aprobación humana:**
  se descartó para el MVP. La aprobación es un registro en la base y la acción
  aprobada se ejecuta como una solicitud nueva. Es más simple de operar y de
  auditar, y no deja grafos esperando días.
