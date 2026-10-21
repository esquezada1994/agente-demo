# Arquitectura

## Componentes

| Componente | Tecnología | Responsabilidad |
|---|---|---|
| Consola (`web/`) | React 19, Vite, Tailwind, TanStack Query | Bandeja de aprobación, cartera, simulador de cliente, conversaciones, definición, conocimiento, ajustes |
| API (`agente.api`) | FastAPI | Sesión, casos de uso, publicación de definiciones |
| Motor (`agente.engine`) | LangGraph + langchain-core | Compila la definición a un grafo y lo ejecuta, con un span por nodo |
| Herramientas (`agente.tools`) | Python, Pydantic | Contratos tipados; reglas del negocio |
| Dominio (`agente.domain`) | Python | Priorización de cartera, seguimiento de promesas, adaptador del ERP |
| Base | PostgreSQL 17 | Usuarios, definiciones, conversaciones, aprobaciones, promesas, conocimiento (texto completo), ERP simulado |
| Gobierno (`engine/governance.py`) | plataforma-sdk (OpenTelemetry) | Enrolamiento, manifiesto, trazas, valor, valoración |

## Una conversación, paso a paso

```mermaid
sequenceDiagram
    participant C as Cliente
    participant API as API del agente
    participant G as Motor (LangGraph)
    participant M as Modelo (OpenAI / Azure)
    participant ERP as ERP del cliente
    participant P as Portal de gobernanza

    C->>API: "Puedo pagar $150 el viernes"
    API->>G: run_chat (traza nueva)
    G->>G: input_guard: inyección / datos personales
    G->>M: llm + herramientas permitidas
    M-->>G: tool_call registrar_promesa(150, viernes)
    G->>ERP: saldo del cliente (la herramienta valida monto y plazo)
    G->>M: llm con el resultado
    M-->>G: respuesta
    G->>G: validate: datos personales, ofertas, montos con respaldo
    G-->>API: respuesta + resultado (resuelta)
    API-->>C: "Registré tu compromiso…"
    G--)P: OTLP: 6 etapas, tokens, herramienta, fuente, resultado
    API--)P: valor: promesa $150, 0,2 h evitadas
    Note over API,P: Días después: pago cumplido → valor recuperado ligado a la misma traza
```

## Datos: qué queda dónde

| Dato | Base del agente (cliente) | Portal |
|---|---|---|
| Texto de las conversaciones | Sí (datos personales ocultos, retención definida) | No |
| Cartera, facturas, nombres | Sí (o en el ERP) | No |
| Etapas, tokens, latencia, herramientas, fuentes | — | Sí |
| Categoría de un control aplicado | Sí | Sí (solo la categoría) |
| Promesas y pagos | Sí (detalle) | Sí (monto por evento, sin persona) |
| Definición del agente | Sí (completa, con instrucciones) | Manifiesto (sin instrucciones ni textos) |
