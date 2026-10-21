# agente-base · Agente de cobranza preventiva

Un producto que se instala **para una empresa**, en su infraestructura, y que
reporta sus métricas al portal de gobernanza de IA. Funciona igual sin el portal;
conectado, el portal ve su costo, su recorrido por etapas, sus controles y su retorno.

**Qué hace.** Toda empresa que factura a crédito tiene cartera vencida. El agente:

1. **Prioriza la cartera** con una fórmula explícita (monto vencido × antigüedad ×
   promesas incumplidas). El modelo no decide a quién cobrar.
2. **Redacta recordatorios** (preventivos y de mora) que **una persona aprueba**
   antes de enviarlos.
3. **Atiende al cliente**: saldo, factura, fecha de pago. Registra **promesas de
   pago**, pide **acuerdos en cuotas** (a aprobación), registra **disputas** y
   **deriva** a un gestor lo que no puede resolver.
4. **Da seguimiento** a las promesas: las cumplidas se registran como valor
   recuperado, ligado a la conversación que las produjo.

Por qué este caso: el retorno se mide en dinero (cobrado, horas de gestión
evitadas) y sirve igual para una ferretería, un colegio o una distribuidora.

```
Cliente ─► Consola / canal ─► API del agente ─► Motor (LangGraph) ─► ERP · Conocimiento
                                                     │
                                       plataforma-sdk│ trazas · manifiesto · valor
                                                     ▼
                                          Portal de gobernanza
```

Arquitectura y decisiones: [docs/arquitectura.md](docs/arquitectura.md) y [docs/adr](docs/adr).

---

## Probarlo en local (con el portal)

Requisitos: Docker. El portal de gobernanza levantado (`make up && make seed` en
su repositorio). Su `make seed` imprime un **token de enrolamiento** para este agente:

```
Token de enrolamiento del agente de cobranza (vence en 7 días): ge_…
```

También se genera desde el portal: *Soluciones de IA → Agente de cobranza
preventiva → Integración → Generar token de enrolamiento*.

```bash
git clone https://github.com/esquezada1994/agente-base.git && cd agente-base
cp .env.example .env            # poner ENROLL_TOKEN=ge_… (opcional)
make up                         # base (5433), API (8100), consola (5180)
make init                       # empresa, primer usuario y conexión al portal
```

`make init` imprime el **usuario administrador y una contraseña temporal** (se
muestra una sola vez y se cambia al entrar). Abrir **http://localhost:5180**.

Para ver datos en el portal:

```bash
make demo-traffic               # 30 conversaciones de prueba
make reminders                  # 10 recordatorios en la bandeja de aprobación
make payments                   # simula 7 días: promesas cumplidas → valor recuperado
```

En el portal (Demo Andes → *Agente de cobranza preventiva*): **Recorrido**,
**Inversión y valor** (retorno), **Integración** (manifiesto) y, en *Consumo y
costos*, **Facturado frente a trazado**.

**Sin cuenta de OpenAI** el agente usa un **modelo simulado** (`demo-simulado`):
reglas deterministas que recorren todas las herramientas. Para un modelo real,
poner `OPENAI_API_KEY` en `.env` y `make up` de nuevo. El simulador está
prohibido en producción (`APP_ENV=production` no arranca con él).

## Actualizar una instalación

```bash
git pull
make up          # reconstruye la imagen y aplica migraciones al arrancar; los datos se conservan
```

Si cambió el SDK en el repositorio del portal, primero:

```bash
make vendor-sdk PORTAL=../gobernance-app   # reconstruye vendor/*.whl y uv.lock
git add vendor uv.lock && git commit -m "SDK actualizado"
make up
```

`make reset` borra los datos del agente (usuarios, conversaciones, conexión al portal): después hay que repetir `make init` con un token nuevo.

## Desarrollo sin Docker

```bash
make setup
# Postgres en localhost:5433 (make up levanta uno), luego:
uv run agente init --empresa "Mi empresa" --admin yo@empresa.com
make dev-api    # http://localhost:8100/docs
make dev-web    # http://localhost:5180
make test       # TEST_DATABASE_URL=postgresql+psycopg://…/agente_test
```

---

## Cómo funciona

### El agente es una definición

[`definitions/cobranza-preventiva.json`](definitions/cobranza-preventiva.json)
describe todo: persona, modelos, instrucciones, herramientas habilitadas,
fuentes, políticas, cuánto trabajo reemplaza cada resultado y dos **flujos**
(grafos de nodos y conexiones):

| Flujo | Nodos |
|---|---|
| `chat` | revisar entrada → buscar en políticas → razonar ⇄ ejecutar herramientas → validar → responder |
| `reminder` | redactar (modelo económico) → validar → aprobación del gestor → cerrar |

El motor ([`engine/runtime.py`](src/agente/engine/runtime.py)) convierte cada
flujo en un grafo de **LangGraph**. Un **canvas visual** editaría esta misma
estructura (cada nodo ya trae `position`) sin cambiar el motor:
[ADR 0001](docs/adr/0001-definicion-como-datos.md).

Antes de publicar una versión se valida el grafo completo: salidas cubiertas,
nodos alcanzables, herramientas registradas. Cada versión publicada se envía al
portal como un manifiesto nuevo.

### Gobierno incluido en cada nodo

Cada tipo de nodo pertenece a una etapa del portal y abre su span con
`plataforma-sdk`. Todo agente armado con estos nodos nace gobernado.

| Tipo de nodo | Etapa | Qué registra |
|---|---|---|
| `input_guard` | Validación | Instrucciones maliciosas (bloquea), datos personales (oculta) |
| `retrieve` | Recuperación | Fuente, fecha de actualización, relevancia (0–1), documentos |
| `llm` | Modelo | Modelo, tokens exactos del proveedor (incluye caché) |
| `tools` | Herramientas | Herramienta, fuente que toca, error |
| `validate` | Validación | Datos personales, ofertas no autorizadas, montos sin respaldo |
| `approval` | Herramientas | Propuesta enviada a la bandeja |
| `respond` + solicitud | Entrada / Respuesta | Resultado (resuelta o derivada) y valoración 👍/👎 |

**Qué sale al portal:** hechos (etapas, tokens, herramientas, fuentes,
controles, resultados) y valor (horas evitadas, montos prometidos y cobrados).
**Qué no sale:** textos de conversación, nombres, teléfonos, números de factura.
Las conversaciones se guardan solo en la base del agente, con los datos
personales ocultos y la retención que defina la empresa.

### Herramientas: el modelo no puede inventar poderes

Las herramientas se registran en código
([`tools/registry.py`](src/agente/tools/registry.py)) con su contrato:
parámetros tipados, si escriben, si requieren aprobación y qué fuente tocan.
La definición elige cuáles habilitar. Reglas:

- El cliente sale del contexto de la conversación, **nunca de un parámetro del
  modelo**: no puede consultar a otro cliente.
- Las reglas del negocio las valida la herramienta, no el modelo (monto ≤ saldo,
  fecha dentro del plazo de la política).
- Lo sensible no se ejecuta: el acuerdo de pago queda en la bandeja.

### Integrar el ERP real

[`domain/erp.py`](src/agente/domain/erp.py) define la interfaz (`customer`,
`open_invoices`…) y una implementación simulada con datos sintéticos. Para un
cliente se escribe el adaptador de su ERP (Odoo, SAP Business One, Contífico o
una API propia), **de solo lectura**. El resto del agente no cambia.

---

## Producción

| Tema | Cómo |
|---|---|
| Secretos | `SECRET_KEY` (≥ 32 caracteres) y `OPENAI_API_KEY` desde el gestor de secretos del ambiente. La llave del portal se guarda cifrada en la base. |
| Arranque seguro | Con `APP_ENV=production` no arranca con la llave de desarrollo, el modelo simulado ni el simulador de cliente. |
| Sesiones | Cookie httpOnly, `SameSite=Lax`, `Secure` en producción. Contraseñas con scrypt. Cambio obligatorio en el primer ingreso. |
| HTTPS y MFA | Detrás de un proxy con TLS. Para MFA, reemplazar el inicio de sesión local por OIDC (Entra ID o Keycloak). |
| Base | Postgres administrado con respaldos cifrados. Migraciones con Alembic (`agente migrate`). |
| Canal | El simulador se desactiva (`CHAT_SIMULATOR=false`). WhatsApp vía Meta Cloud API es el siguiente paso. |
| Una instalación por cliente | Aísla sus datos. El portal es el lugar multiempresa. |

## Límites conocidos

- El canal de WhatsApp y el envío de correo están simulados (se registran, no se envían).
- La búsqueda es de texto completo de Postgres, suficiente para decenas de
  documentos de políticas. Para bases grandes, el siguiente paso es pgvector con
  embeddings del proveedor.
- El inicio de sesión es local (usuario y contraseña). OIDC queda para la integración con el cliente.
- El SDK se instala desde `vendor/` hasta publicarlo en un registro de paquetes (`make vendor-sdk`).
