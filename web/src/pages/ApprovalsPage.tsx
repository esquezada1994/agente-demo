import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, MessageSquareText, X } from 'lucide-react'
import { useState } from 'react'

import { Badge, Button, Card, Empty, ErrorText, PageTitle, Textarea } from '@/components/ui'
import { cn } from '@/lib/cn'
import { api, dateTime, money, type ApprovalItem } from '@/lib/api'
import { ACTION_LABEL, REASON_LABEL } from '@/lib/labels'

function ApprovalCard({ item }: { item: ApprovalItem }) {
  const queryClient = useQueryClient()
  const [text, setText] = useState(item.payload.texto ?? '')
  const decide = useMutation({
    mutationFn: (approve: boolean) =>
      api.decide(item.id, { approve, text: text !== item.payload.texto ? text : undefined }),
    onSuccess: () => queryClient.invalidateQueries(),
  })
  const reasons = (item.payload.razones as string[] | undefined) ?? item.reason?.split(',') ?? []
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-medium">{item.customer}</p>
          <p className="text-xs text-muted">
            {item.customer_code} · {dateTime(item.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {item.kind === 'reminder' ? (
            <Badge tone="brand">
              <MessageSquareText className="size-3" aria-hidden="true" /> Recordatorio por{' '}
              {item.payload.canal}
            </Badge>
          ) : (
            <Badge tone="warn">Acuerdo de pago</Badge>
          )}
          {typeof item.payload.tipo === 'string' && (
            <Badge>{ACTION_LABEL[item.payload.tipo]}</Badge>
          )}
          {reasons.filter(Boolean).map((r) => (
            <Badge key={r}>{REASON_LABEL[r] ?? r}</Badge>
          ))}
        </div>
      </div>

      {item.kind === 'reminder' ? (
        <>
          <label htmlFor={`t-${item.id}`} className="mt-4 block text-xs text-muted">
            Texto propuesto por el agente (puedes editarlo antes de aprobar)
          </label>
          <Textarea
            id={`t-${item.id}`}
            rows={3}
            className="mt-1"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {typeof item.payload.saldo === 'string' && (
            <p className="mt-2 text-xs text-muted">
              Saldo considerado: {money(item.payload.saldo)}
            </p>
          )}
        </>
      ) : (
        <p className="mt-4 text-sm">
          El cliente pide pagar en <strong>{item.payload.cuotas} cuotas</strong> (motivo:{' '}
          {String(item.payload.motivo)}). Al aprobar se crea el caso para formalizar el acuerdo.
        </p>
      )}

      <div className="mt-4 flex gap-2">
        <Button
          onClick={() => decide.mutate(true)}
          disabled={decide.isPending || (item.kind === 'reminder' && !text.trim())}
        >
          <Check className="size-4" aria-hidden="true" />
          {item.kind === 'reminder' ? 'Aprobar y enviar' : 'Aprobar'}
        </Button>
        <Button variant="danger" onClick={() => decide.mutate(false)} disabled={decide.isPending}>
          <X className="size-4" aria-hidden="true" /> Rechazar
        </Button>
      </div>
      <ErrorText error={decide.error} />
    </Card>
  )
}

export function ApprovalsPage() {
  const [state, setState] = useState<'pending' | 'approved' | 'rejected'>('pending')
  const items = useQuery({ queryKey: ['approvals', state], queryFn: () => api.approvals(state) })
  return (
    <>
      <PageTitle
        title="Aprobaciones"
        hint="El agente propone; una persona decide. Ningún mensaje sale a un cliente ni se acuerda un plan de pago sin esta revisión."
      />
      <div className="mb-4 flex gap-1" role="tablist">
        {(['pending', 'approved', 'rejected'] as const).map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={state === s}
            onClick={() => setState(s)}
            className={cn(
              'rounded-lg px-3 py-1.5 text-sm',
              state === s ? 'bg-brand-soft font-medium text-brand' : 'text-muted hover:text-ink',
            )}
          >
            {{ pending: 'Pendientes', approved: 'Aprobadas', rejected: 'Rechazadas' }[s]}
          </button>
        ))}
      </div>
      {items.isPending ? (
        <p className="text-sm text-muted">Cargando…</p>
      ) : items.data?.length === 0 ? (
        <Empty>
          {state === 'pending'
            ? 'No hay propuestas pendientes. En Cartera puedes pedir al agente que prepare recordatorios.'
            : 'Sin registros.'}
        </Empty>
      ) : state === 'pending' ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {items.data?.map((item) => (
            <ApprovalCard key={item.id} item={item} />
          ))}
        </div>
      ) : (
        <Card className="p-0">
          <ul className="divide-y divide-border text-sm">
            {items.data?.map((item) => (
              <li key={item.id} className="px-5 py-3">
                <p className="font-medium">{item.customer}</p>
                <p className="mt-1 text-muted">
                  {item.payload.texto ?? `${item.payload.cuotas} cuotas`}
                </p>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  )
}
