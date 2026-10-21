import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { Badge, Card, Empty, PageTitle } from '@/components/ui'
import { cn } from '@/lib/cn'
import { api, dateTime } from '@/lib/api'
import { OUTCOME_LABEL, TOOL_LABEL, VIOLATION_LABEL } from '@/lib/labels'

export function ConversationsPage() {
  const list = useQuery({ queryKey: ['conversations'], queryFn: api.conversations })
  const [selected, setSelected] = useState<string>()
  const current = selected ?? list.data?.[0]?.id
  const messages = useQuery({
    queryKey: ['conversation', current],
    queryFn: () => api.conversation(current ?? ''),
    enabled: Boolean(current),
  })

  return (
    <>
      <PageTitle
        title="Conversaciones"
        hint={`Se conservan en esta instalación según la política de retención. Los datos personales escritos por el cliente se guardan ocultos.`}
      />
      {list.data?.length === 0 ? (
        <Empty>Aún no hay conversaciones. Prueba el simulador de cliente.</Empty>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <Card className="max-h-[36rem] overflow-y-auto p-0">
            <ul className="divide-y divide-border">
              {list.data?.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(c.id)}
                    className={cn(
                      'w-full px-4 py-3 text-left text-sm hover:bg-surface',
                      current === c.id && 'bg-brand-soft',
                    )}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{c.customer ?? 'Sin cliente'}</span>
                      {c.outcome && (
                        <Badge tone={c.outcome === 'resolved' ? 'ok' : 'warn'}>
                          {OUTCOME_LABEL[c.outcome]}
                        </Badge>
                      )}
                    </span>
                    <span className="mt-0.5 block text-xs text-muted">
                      {dateTime(c.last_message_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <Card className="space-y-3">
            {messages.data?.map((m) => (
              <div
                key={m.id}
                className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}
              >
                <div
                  className={cn(
                    'max-w-[80%] rounded-2xl px-4 py-2.5 text-sm',
                    m.role === 'user' ? 'bg-brand text-white' : 'border border-border bg-surface',
                  )}
                >
                  <p className="whitespace-pre-wrap">{m.content}</p>
                  {m.role === 'assistant' && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {(m.meta.tools ?? []).map((t, i) => (
                        <Badge key={`${t}-${i}`}>{TOOL_LABEL[t] ?? t}</Badge>
                      ))}
                      {(m.meta.violations ?? []).map((v) => (
                        <Badge key={v} tone="bad">
                          {VIOLATION_LABEL[v] ?? v}
                        </Badge>
                      ))}
                      {m.feedback === 1 && <Badge tone="ok">Útil</Badge>}
                      {m.feedback === -1 && <Badge tone="bad">No útil</Badge>}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </Card>
        </div>
      )}
    </>
  )
}
