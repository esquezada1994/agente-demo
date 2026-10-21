/** Textos de la interfaz para valores que llegan de la API. */

export const ACTION_LABEL: Record<string, string> = {
  preventive: 'Preventivo',
  overdue: 'Vencido',
  promise_followup: 'Promesa incumplida',
  none: 'Sin acción',
}

export const REASON_LABEL: Record<string, string> = {
  overdue: 'Saldo vencido',
  over_30_days: 'Más de 30 días',
  broken_before: 'Incumplió antes',
  due_soon: 'Vence pronto',
  promise_open: 'Promesa vigente',
  promise_broken: 'Promesa vencida',
}

export const TOOL_LABEL: Record<string, string> = {
  consultar_estado_cuenta: 'Consultó el estado de cuenta',
  registrar_promesa: 'Registró una promesa de pago',
  solicitar_acuerdo_pago: 'Pidió un acuerdo (a aprobación)',
  reportar_disputa: 'Registró una disputa',
  derivar_a_persona: 'Derivó a un gestor',
  enviar_factura: 'Envió la factura',
}

export const VIOLATION_LABEL: Record<string, string> = {
  prompt_injection: 'Instrucción maliciosa bloqueada',
  personal_data: 'Datos personales ocultados',
  unauthorized_offer: 'Oferta no autorizada bloqueada',
  ungrounded_amount: 'Monto sin respaldo bloqueado',
}

export const STAGE_LABEL: Record<string, string> = {
  input: 'Entrada',
  retrieval: 'Recuperación',
  model: 'Modelo',
  tool: 'Herramientas',
  validation: 'Validación',
  response: 'Respuesta',
}

export const OUTCOME_LABEL: Record<string, string> = {
  resolved: 'Resuelta',
  escalated: 'Derivada',
  abandoned: 'Abandonada',
}
