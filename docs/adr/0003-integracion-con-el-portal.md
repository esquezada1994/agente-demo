# 0003. Integración con el portal de gobernanza

**Estado:** Aceptada · **Fecha:** 2026-10-20

## Decisión

El agente es un producto independiente: se instala por cliente, tiene su base y
sus usuarios, y funciona sin el portal. La integración usa solo
`plataforma-sdk` y cuatro llamadas:

| Momento | Llamada | Qué viaja |
|---|---|---|
| `agente init --enroll` | `POST /v1/enroll` | Token de un solo uso (24 h) → llave limitada a esta solución, guardada cifrada |
| Arranque y cada versión | `PUT /v1/manifest` | Modelos, fuentes, herramientas (escribe / requiere aprobación), controles, retención, versión |
| Cada solicitud | `POST /v1/traces` (OTLP) | Etapas, tokens, herramienta, fuente, relevancia, error, resultado, versión |
| Resultado de negocio | `POST /v1/value` | Horas evitadas, promesa y pago (monto), ligados a la traza |
| Valoración | `POST /v1/feedback` | 👍/👎 de una solicitud ya respondida |

- La llave **solo sirve para esta solución**: el portal descarta lo que llegue
  con otra clave.
- El agente **no crea empresas** en el portal. Eso lo hace el consultor.
- Si el portal no responde, el agente sigue: el SDK envía en segundo plano y
  solo registra un aviso.
- **Minimización:** ningún texto, nombre ni número de factura sale del agente.
  Los montos van agregados por evento, sin identificar a la persona.

## Consecuencias

El portal obtiene el nivel de gobierno 2–3 desde el primer día (trazas,
validación, aprobación humana declarada) y el retorno con evidencia: cada dólar
cobrado se puede rastrear hasta la conversación que lo originó.
