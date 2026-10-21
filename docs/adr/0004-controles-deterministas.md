# 0004. Controles deterministas y aprobación humana

**Estado:** Aceptada · **Fecha:** 2026-10-20

## Decisión

La primera línea de control no depende del modelo:

- **Entrada:** se bloquean instrucciones maliciosas antes de llamar al modelo
  y se ocultan datos personales (cédula, tarjeta validada con Luhn, correo,
  teléfono).
- **Salida:** se ocultan datos personales; las ofertas no autorizadas
  (descuento, condonación) y los montos que no aparecen en lo que devolvieron
  las herramientas se reemplazan por una derivación a un gestor.
- **Herramientas:** validan las reglas del negocio (monto ≤ saldo, plazo
  máximo de la promesa). El cliente sale del contexto, no del modelo.
- **Aprobación humana** para los mensajes que salen a un cliente y para los
  acuerdos de pago.
- **Priorización con una fórmula visible,** no con el modelo.

Cada control se registra en el portal como una categoría de violación, nunca
con el texto que la originó.

## Consecuencias

Los controles se prueban con pruebas unitarias y son auditables. Un validador
basado en modelo (por ejemplo, para el tono) se puede agregar como otro nodo
`validate` sin quitar estas reglas.
