import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Sparkles } from 'lucide-react'

import { Badge, Button, Card, ErrorText, PageTitle } from '@/components/ui'
import { api, money } from '@/lib/api'
import { ACTION_LABEL, REASON_LABEL } from '@/lib/labels'
import { useUser } from '@/lib/session'

const TONE = {
  overdue: 'bad',
  promise_followup: 'warn',
  preventive: 'info',
  none: 'neutral',
} as const

export function PortfolioPage() {
  const user = useUser()
  const queryClient = useQueryClient()
  const items = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio })
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const prepare = useMutation({
    mutationFn: () => api.prepareReminders(10),
    onSuccess: () => queryClient.invalidateQueries(),
  })
  const simulate = useMutation({
    mutationFn: () => api.simulatePayments(7),
    onSuccess: () => queryClient.invalidateQueries(),
  })

  return (
    <>
      <PageTitle
        title="Cartera priorizada"
        hint="Orden por monto vencido, antigüedad e historial de promesas. La fórmula es fija y visible: el modelo no decide a quién cobrar."
        actions={
          <>
            <Button onClick={() => prepare.mutate()} disabled={prepare.isPending}>
              <Sparkles className="size-4" aria-hidden="true" />
              {prepare.isPending ? 'Redactando…' : 'Preparar recordatorios'}
            </Button>
            {user.role === 'admin' && settings.data?.simulator && (
              <Button
                variant="outline"
                onClick={() => simulate.mutate()}
                disabled={simulate.isPending}
              >
                <CalendarClock className="size-4" aria-hidden="true" /> Simular 7 días de pagos
              </Button>
            )}
          </>
        }
      />
      {prepare.data && (
        <p className="mb-4 rounded-lg bg-ok-bg px-4 py-2 text-sm text-ok-fg">
          {prepare.data.created} recordatorios en la bandeja de aprobación.
        </p>
      )}
      {simulate.data && (
        <p className="mb-4 rounded-lg bg-info-bg px-4 py-2 text-sm text-info-fg">
          Simulación: {simulate.data.cumplidas} de {simulate.data.promesas} promesas cumplidas ·
          recuperado {money(simulate.data.recuperado)}.
        </p>
      )}
      <ErrorText error={prepare.error ?? simulate.error} />

      <Card className="overflow-x-auto p-0">
        <table className="w-full min-w-[46rem] text-left text-sm">
          <thead className="text-muted">
            <tr className="border-b border-border">
              <th className="px-5 py-3 font-normal">Cliente</th>
              <th className="px-3 py-3 font-normal">Acción</th>
              <th className="px-3 py-3 text-right font-normal">Vencido</th>
              <th className="px-3 py-3 text-right font-normal">Días</th>
              <th className="px-3 py-3 text-right font-normal">Saldo total</th>
              <th className="px-5 py-3 font-normal">Por qué</th>
            </tr>
          </thead>
          <tbody>
            {items.data?.map((i) => (
              <tr key={i.customer_id} className="border-b border-border last:border-0">
                <td className="px-5 py-3">
                  <p className="font-medium">{i.name}</p>
                  <p className="text-xs text-muted">
                    {i.code} · {i.invoices} factura(s)
                  </p>
                </td>
                <td className="px-3 py-3">
                  <Badge tone={TONE[i.action]}>{ACTION_LABEL[i.action]}</Badge>
                  {i.pending_approval && (
                    <span className="mt-1 block text-xs text-muted">Propuesta en revisión</span>
                  )}
                </td>
                <td className="px-3 py-3 text-right tabular-nums">{money(i.overdue_balance)}</td>
                <td className="px-3 py-3 text-right tabular-nums">{i.max_days_overdue || '—'}</td>
                <td className="px-3 py-3 text-right tabular-nums">{money(i.total_balance)}</td>
                <td className="px-5 py-3">
                  <div className="flex flex-wrap gap-1">
                    {i.reasons.map((r) => (
                      <Badge key={r}>{REASON_LABEL[r] ?? r}</Badge>
                    ))}
                    {i.open_promise && (
                      <Badge tone="ok">
                        Promesa {money(i.open_promise.amount)} · {i.open_promise.date}
                      </Badge>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  )
}
