import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleCheck } from 'lucide-react'
import { type FormEvent, useState } from 'react'

import { Badge, Button, Card, ErrorText, Input, Label, PageTitle } from '@/components/ui'
import { api, dateTime } from '@/lib/api'

function Branding({ company, color }: { company: string; color: string }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(company)
  const [value, setValue] = useState(color)
  const save = useMutation({
    mutationFn: () => api.setBranding(name, value),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings'] }),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Card>
      <h2 className="font-semibold">Marca</h2>
      <form onSubmit={submit} className="mt-4 space-y-3">
        <div>
          <Label htmlFor="company">Nombre de la empresa</Label>
          <Input id="company" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <Label htmlFor="color">Color principal</Label>
          <div className="flex items-center gap-2">
            <input
              id="color"
              type="color"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="h-9 w-12 rounded border border-border"
            />
            <span className="font-mono text-sm">{value}</span>
          </div>
        </div>
        <Button type="submit" disabled={save.isPending}>
          Guardar
        </Button>
        <ErrorText error={save.error} />
      </form>
    </Card>
  )
}

function Governance() {
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const enroll = useMutation({
    mutationFn: () => api.enroll(url || settings.data?.platform_url || '', token),
    onSuccess: () => queryClient.invalidateQueries(),
  })
  const info = settings.data?.governance
  const submit = (e: FormEvent) => {
    e.preventDefault()
    enroll.mutate()
  }
  return (
    <Card>
      <h2 className="font-semibold">Portal de gobernanza</h2>
      {settings.data?.connected && info ? (
        <div className="mt-4 text-sm">
          <p className="flex items-center gap-2 font-medium text-ok-fg">
            <CircleCheck className="size-4" aria-hidden="true" /> Conectado como{' '}
            {info.solution_name}
          </p>
          <p className="mt-2 text-muted">
            {info.url} · empresa <span className="font-mono">{info.tenant}</span> · desde{' '}
            {dateTime(info.enrolled_at)}
          </p>
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted">
          En el portal: ficha de la solución → Integración → Generar token de enrolamiento.
        </p>
      )}
      <form onSubmit={submit} className="mt-4 space-y-3">
        <div>
          <Label htmlFor="url">URL de la API del portal</Label>
          <Input
            id="url"
            placeholder={settings.data?.platform_url ?? 'https://api.portal.com'}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="token">Token de enrolamiento</Label>
          <Input
            id="token"
            placeholder="ge_…"
            required
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={enroll.isPending}>
          {settings.data?.connected ? 'Volver a conectar' : 'Conectar'}
        </Button>
        <ErrorText error={enroll.error} />
      </form>
      <p className="mt-4 text-xs text-muted">
        Modelo en uso: <Badge>{settings.data?.model_provider}</Badge>
        {settings.data?.model_provider === 'demo' &&
          ' (simulador para pruebas: configura OPENAI_API_KEY para usar un modelo real)'}
      </p>
    </Card>
  )
}

function UsersCard() {
  const queryClient = useQueryClient()
  const users = useQuery({ queryKey: ['users'], queryFn: api.users })
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState('gestor')
  const create = useMutation({
    mutationFn: () => api.createUser(email, name, role),
    onSuccess: async () => {
      setEmail('')
      setName('')
      await queryClient.invalidateQueries({ queryKey: ['users'] })
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  return (
    <Card className="lg:col-span-2">
      <h2 className="font-semibold">Usuarios</h2>
      <ul className="mt-3 divide-y divide-border text-sm">
        {users.data?.map((u) => (
          <li key={u.id} className="flex items-center justify-between py-2">
            <span>
              {u.name} <span className="text-muted">· {u.email}</span>
            </span>
            <Badge>{u.role === 'admin' ? 'Administrador' : 'Gestor'}</Badge>
          </li>
        ))}
      </ul>
      <form
        onSubmit={submit}
        className="mt-4 grid gap-3 sm:grid-cols-[1fr_1fr_9rem_auto] sm:items-end"
      >
        <div>
          <Label htmlFor="u-name">Nombre</Label>
          <Input id="u-name" required value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <Label htmlFor="u-email">Correo</Label>
          <Input
            id="u-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="u-role">Rol</Label>
          <select
            id="u-role"
            className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            <option value="gestor">Gestor</option>
            <option value="admin">Administrador</option>
          </select>
        </div>
        <Button type="submit" disabled={create.isPending}>
          Agregar
        </Button>
      </form>
      {create.data && (
        <p className="mt-3 rounded-lg bg-warn-bg px-4 py-2 text-sm text-warn-fg">
          Contraseña temporal de {create.data.email}:{' '}
          <span className="font-mono">{create.data.temporary_password}</span> (se muestra una sola
          vez; se cambia al entrar).
        </p>
      )}
      <ErrorText error={create.error} />
    </Card>
  )
}

export function SettingsPage() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  if (!settings.data) return <p className="text-sm text-muted">Cargando…</p>
  return (
    <>
      <PageTitle title="Ajustes" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Branding
          key={settings.data.branding.color + settings.data.branding.company}
          {...settings.data.branding}
        />
        <Governance />
        <UsersCard />
      </div>
    </>
  )
}
