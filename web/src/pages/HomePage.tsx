import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CircleCheck, CircleDashed } from 'lucide-react'
import { Link } from 'react-router'

import { Card, PageTitle, Stat } from '@/components/ui'
import { api, dateTime, money } from '@/lib/api'

export function HomePage() {
  const dash = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard })
  if (dash.isPending) return <p className="text-sm text-muted">Cargando…</p>
  if (dash.isError) return <p role="alert">No se pudo cargar el resumen.</p>
  const d = dash.data
  return (
    <>
      <PageTitle title="Resumen" hint="Últimos 30 días del agente en esta empresa." />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Cartera vencida"
          value={money(d.overdue_total)}
          hint={`${d.customers_overdue} clientes`}
        />
        <Stat label="Comprometido en conversaciones" value={money(d.promised)} />
        <Stat label="Recuperado de promesas" value={money(d.recovered)} />
        <Stat
          label="Conversaciones"
          value={d.conversations}
          hint={`${Math.round(d.escalation_share * 100)} % derivadas a un gestor`}
        />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="font-semibold">Pendiente para el equipo</h2>
          <ul className="mt-4 divide-y divide-border text-sm">
            <li className="flex items-center justify-between py-3">
              <span>Propuestas esperando aprobación</span>
              <Link
                to="/aprobaciones"
                className="inline-flex items-center gap-1 font-medium text-brand"
              >
                {d.pending_approvals} <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </li>
            <li className="flex items-center justify-between py-3">
              <span>Clientes que requieren un recordatorio</span>
              <Link to="/cartera" className="inline-flex items-center gap-1 font-medium text-brand">
                {d.actionable} <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </li>
            <li className="flex items-center justify-between py-3">
              <span>Casos abiertos (disputas y derivaciones)</span>
              <span className="font-medium tabular-nums">{d.open_cases}</span>
            </li>
          </ul>
        </Card>

        <Card>
          <h2 className="font-semibold">Gobierno</h2>
          {d.connected && d.governance ? (
            <div className="mt-4 text-sm">
              <p className="flex items-center gap-2 font-medium text-ok-fg">
                <CircleCheck className="size-4" aria-hidden="true" /> Conectado al portal
              </p>
              <dl className="mt-3 grid gap-2 text-muted">
                <div>
                  <dt className="text-xs">Solución</dt>
                  <dd className="text-ink">{d.governance.solution_name}</dd>
                </div>
                <div>
                  <dt className="text-xs">Empresa en el portal</dt>
                  <dd className="font-mono text-ink">{d.governance.tenant}</dd>
                </div>
                <div>
                  <dt className="text-xs">Desde</dt>
                  <dd className="text-ink">{dateTime(d.governance.enrolled_at)}</dd>
                </div>
              </dl>
              <p className="mt-3 text-xs text-muted">
                Se envían etapas, tokens, herramientas, resultados y valor. Nunca el texto de las
                conversaciones.
              </p>
            </div>
          ) : (
            <div className="mt-4 text-sm">
              <p className="flex items-center gap-2 font-medium text-muted">
                <CircleDashed className="size-4" aria-hidden="true" /> Sin conexión con el portal
              </p>
              <p className="mt-2 text-muted">
                El agente funciona igual; conéctalo en Ajustes para medir costo, recorrido y
                retorno.
              </p>
            </div>
          )}
        </Card>
      </div>
    </>
  )
}
