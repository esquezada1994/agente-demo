/** Cliente de la API del agente. La sesión viaja en una cookie httpOnly. */

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(`/api${path}`, { ...init, headers, credentials: 'include' })
  if (!response.ok) {
    let message = `Error ${response.status}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map(String).join(' · ')
    } catch {
      // sin cuerpo JSON
    }
    throw new ApiError(response.status, message)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
})

export interface User {
  id: string
  email: string
  name: string
  role: 'admin' | 'gestor'
  must_change_password: boolean
}

export interface Dashboard {
  conversations: number
  escalation_share: number
  promised: string
  recovered: string
  pending_approvals: number
  open_cases: number
  overdue_total: string
  customers_overdue: number
  actionable: number
  connected: boolean
  governance: GovernanceInfo | null
}

export interface GovernanceInfo {
  url: string
  solution: string
  solution_name: string
  tenant: string
  enrolled_at: string
}

export interface PortfolioItem {
  customer_id: string
  code: string
  name: string
  segment: string
  total_balance: string
  overdue_balance: string
  max_days_overdue: number
  next_due_in: number | null
  invoices: number
  action: 'preventive' | 'overdue' | 'promise_followup' | 'none'
  score: number
  reasons: string[]
  pending_approval: boolean
  open_promise: { amount: string; date: string } | null
}

export interface ApprovalItem {
  id: string
  kind: 'reminder' | 'payment_plan'
  status: string
  customer: string
  customer_code: string
  payload: Record<string, unknown> & {
    texto?: string
    canal?: string
    cuotas?: number
    motivo?: string
  }
  reason: string | null
  created_at: string
}

export interface ChatReply {
  conversation_id: string
  message_id: string
  answer: string
  outcome: 'resolved' | 'escalated'
  trace_id: string
  tools: string[]
  violations: string[]
}

export interface ConversationRow {
  id: string
  customer: string | null
  channel: string
  outcome: string | null
  started_at: string
  last_message_at: string
}

export interface MessageRow {
  id: string
  role: 'user' | 'assistant'
  content: string
  trace_id: string | null
  feedback: number | null
  meta: { tools?: string[]; violations?: string[]; outcome?: string }
  created_at: string
}

export interface FlowNode {
  id: string
  type: string
  label?: string | null
  config?: Record<string, unknown>
  position?: { x: number; y: number } | null
}

export interface FlowEdge {
  from: string
  to: string
  when?: string | null
}

export interface Definition {
  id: string
  version: string
  name: string
  description: string
  persona: { name: string; company: string; tone: string }
  models: { main: string; small: string | null }
  tools: { name: string }[]
  flows: Record<string, { nodes: FlowNode[]; edges: FlowEdge[] }>
  [key: string]: unknown
}

export interface DefinitionResponse {
  active: Definition
  history: { version: string; active: boolean; created_at: string }[]
  manifest: Record<string, unknown>
}

export interface Catalog {
  node_types: Record<string, { stage: string; routes: string[]; description: string }>
  tools: Record<
    string,
    { description: string; writes: boolean; requires_approval: boolean; source: string }
  >
}

export interface DocumentRow {
  id: string
  title: string
  body: string
  updated_at: string
}

export interface SettingsResponse {
  branding: { company: string; color: string }
  governance: GovernanceInfo | null
  connected: boolean
  model_provider: string
  simulator: boolean
  platform_url: string | null
}

export const api = {
  login: (email: string, password: string) =>
    request<User>('/auth/login', json('POST', { email, password })),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  me: () => request<User>('/auth/me'),
  changePassword: (current: string, next: string) =>
    request<void>('/auth/password', json('POST', { current, new: next })),

  dashboard: () => request<Dashboard>('/dashboard'),
  portfolio: () => request<PortfolioItem[]>('/portfolio'),
  prepareReminders: (limit: number) =>
    request<{ created: number }>('/portfolio/reminders', json('POST', { limit })),
  simulatePayments: (days_ahead: number) =>
    request<{ promesas: number; cumplidas: number; recuperado: string }>(
      '/simulation/payments',
      json('POST', { days_ahead }),
    ),

  approvals: (state = 'pending') => request<ApprovalItem[]>(`/approvals?state=${state}`),
  decide: (id: string, body: { approve: boolean; text?: string; note?: string }) =>
    request<{ status: string }>(`/approvals/${id}/decision`, json('POST', body)),

  customers: () => request<{ id: string; code: string; name: string }[]>('/customers'),
  chat: (customer_id: string, message: string, conversation_id?: string) =>
    request<ChatReply>('/simulator/chat', json('POST', { customer_id, message, conversation_id })),
  rate: (messageId: string, rating: 1 | -1) =>
    request<void>(`/messages/${messageId}/feedback`, json('POST', { rating })),
  conversations: () => request<ConversationRow[]>('/conversations'),
  conversation: (id: string) => request<MessageRow[]>(`/conversations/${id}`),

  definition: () => request<DefinitionResponse>('/definition'),
  catalog: () => request<Catalog>('/catalog'),
  validateDefinition: (content: unknown) =>
    request<{ valid: boolean; errors: string[] }>(
      '/definition/validate',
      json('POST', { content }),
    ),
  publishDefinition: (content: unknown) =>
    request<{ version: string; manifest_published: boolean }>(
      '/definition',
      json('PUT', { content }),
    ),

  documents: () => request<DocumentRow[]>('/documents'),
  createDocument: (title: string, body: string) =>
    request<DocumentRow>('/documents', json('POST', { title, body })),
  updateDocument: (id: string, title: string, body: string) =>
    request<DocumentRow>(`/documents/${id}`, json('PUT', { title, body })),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: 'DELETE' }),

  settings: () => request<SettingsResponse>('/settings'),
  setBranding: (company: string, color: string) =>
    request<{ company: string; color: string }>(
      '/settings/branding',
      json('PUT', { company, color }),
    ),
  enroll: (url: string, token: string) =>
    request<GovernanceInfo>('/settings/governance/enroll', json('POST', { url, token })),
  users: () =>
    request<{ id: string; email: string; name: string; role: string; active: boolean }[]>('/users'),
  createUser: (email: string, name: string, role: string) =>
    request<{ email: string; temporary_password: string }>(
      '/users',
      json('POST', { email, name, role }),
    ),
}

export const money = (value: string | number) =>
  new Intl.NumberFormat('es-EC', { style: 'currency', currency: 'USD' }).format(Number(value))

export const dateTime = (value: string) =>
  new Intl.DateTimeFormat('es-EC', { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value),
  )
