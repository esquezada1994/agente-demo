import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookOpen,
  Bot,
  ClipboardCheck,
  Home,
  LogOut,
  MessagesSquare,
  Settings,
  Users,
  Workflow,
} from 'lucide-react'
import { type FormEvent, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router'

import { Button, Card, ErrorText, Input, Label } from '@/components/ui'
import { cn } from '@/lib/cn'
import { api, type User } from '@/lib/api'
import { SessionContext } from '@/lib/session'
import { AgentPage } from '@/pages/AgentPage'
import { ApprovalsPage } from '@/pages/ApprovalsPage'
import { ConversationsPage } from '@/pages/ConversationsPage'
import { HomePage } from '@/pages/HomePage'
import { KnowledgePage } from '@/pages/KnowledgePage'
import { PortfolioPage } from '@/pages/PortfolioPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { SimulatorPage } from '@/pages/SimulatorPage'

function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.login(email, password)
      onDone()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="grid min-h-screen place-items-center p-4">
      <Card className="w-full max-w-sm p-6">
        <div className="mb-6 flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-lg bg-brand text-white">
            <Bot className="size-5" aria-hidden="true" />
          </span>
          <div>
            <h1 className="font-semibold">Agente de cobranza</h1>
            <p className="text-sm text-muted">Consola del equipo</p>
          </div>
        </div>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div>
            <Label htmlFor="email">Correo</Label>
            <Input
              id="email"
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="password">Contraseña</Label>
            <Input
              id="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={busy}>
            Entrar
          </Button>
          <ErrorText error={error && 'Correo o contraseña incorrectos'} />
        </form>
      </Card>
    </div>
  )
}

function ChangePassword({ onDone }: { onDone: () => void }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [error, setError] = useState<unknown>(null)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await api.changePassword(current, next)
      onDone()
    } catch (err) {
      setError(err)
    }
  }
  return (
    <div className="grid min-h-screen place-items-center p-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="font-semibold">Cambia tu contraseña</h1>
        <p className="mt-1 text-sm text-muted">
          Es tu primer ingreso: reemplaza la contraseña temporal.
        </p>
        <form onSubmit={submit} className="mt-5 flex flex-col gap-4">
          <div>
            <Label htmlFor="current">Contraseña temporal</Label>
            <Input
              id="current"
              type="password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="next">Nueva contraseña</Label>
            <Input
              id="next"
              type="password"
              required
              minLength={10}
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <p className="mt-1 text-xs text-muted">
              Mínimo 10 caracteres, con letras y números o símbolos.
            </p>
          </div>
          <Button type="submit">Guardar</Button>
          <ErrorText error={error} />
        </form>
      </Card>
    </div>
  )
}

const NAV = [
  { to: '/', label: 'Inicio', icon: Home },
  { to: '/aprobaciones', label: 'Aprobaciones', icon: ClipboardCheck, badge: true },
  { to: '/cartera', label: 'Cartera', icon: Users },
  { to: '/simulador', label: 'Simulador de cliente', icon: Bot },
  { to: '/conversaciones', label: 'Conversaciones', icon: MessagesSquare },
  { to: '/agente', label: 'Definición del agente', icon: Workflow },
  { to: '/conocimiento', label: 'Conocimiento', icon: BookOpen },
  { to: '/ajustes', label: 'Ajustes', icon: Settings, admin: true },
]

function Shell({ user, onLogout }: { user: User; onLogout: () => void }) {
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const dash = useQuery({
    queryKey: ['dashboard'],
    queryFn: api.dashboard,
    refetchInterval: 30_000,
  })
  const color = settings.data?.branding.color
  useEffect(() => {
    if (color) document.documentElement.style.setProperty('--brand', color)
  }, [color])

  return (
    <div className="min-h-screen md:grid md:grid-cols-[15rem_1fr]">
      <aside className="border-b border-border bg-card md:sticky md:top-0 md:h-screen md:border-r md:border-b-0">
        <div className="flex items-center gap-3 px-4 py-4">
          <span className="grid size-9 place-items-center rounded-lg bg-brand text-white">
            <Bot className="size-5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">
              {settings.data?.branding.company ?? 'Mi empresa'}
            </p>
            <p className="text-xs text-muted">Agente de cobranza</p>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-3 md:flex-col md:overflow-visible">
          {NAV.filter((n) => !n.admin || user.role === 'admin').map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm whitespace-nowrap',
                  isActive
                    ? 'bg-brand-soft font-medium text-brand'
                    : 'text-muted hover:bg-surface hover:text-ink',
                )
              }
            >
              <n.icon className="size-4" aria-hidden="true" />
              <span className="flex-1">{n.label}</span>
              {n.badge && (dash.data?.pending_approvals ?? 0) > 0 && (
                <span className="rounded-full bg-brand px-1.5 text-xs text-white tabular-nums">
                  {dash.data?.pending_approvals}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="hidden border-t border-border px-4 py-3 text-xs md:absolute md:bottom-0 md:block md:w-60">
          <p className="truncate font-medium">{user.name}</p>
          <p className="truncate text-muted">{user.email}</p>
          <button
            type="button"
            onClick={onLogout}
            className="mt-2 inline-flex items-center gap-1.5 text-muted hover:text-ink"
          >
            <LogOut className="size-3.5" aria-hidden="true" /> Salir
          </button>
        </div>
      </aside>
      <main className="mx-auto w-full max-w-6xl p-4 md:p-8">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/aprobaciones" element={<ApprovalsPage />} />
          <Route path="/cartera" element={<PortfolioPage />} />
          <Route path="/simulador" element={<SimulatorPage />} />
          <Route path="/conversaciones" element={<ConversationsPage />} />
          <Route path="/agente" element={<AgentPage />} />
          <Route path="/conocimiento" element={<KnowledgePage />} />
          {user.role === 'admin' && <Route path="/ajustes" element={<SettingsPage />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export function App() {
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const refresh = () => void queryClient.invalidateQueries()
  if (me.isPending) return <p className="p-8 text-sm text-muted">Cargando…</p>
  if (me.isError) return <Login onDone={refresh} />
  if (me.data.must_change_password) return <ChangePassword onDone={refresh} />
  const logout = async () => {
    await api.logout()
    queryClient.clear()
    await me.refetch()
  }
  return (
    <SessionContext.Provider value={me.data}>
      <Shell user={me.data} onLogout={() => void logout()} />
    </SessionContext.Provider>
  )
}
