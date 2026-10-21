import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Send, ShieldAlert, ThumbsDown, ThumbsUp, Wrench } from 'lucide-react'
import { type FormEvent, useEffect, useRef, useState } from 'react'

import { Badge, Button, Card, ErrorText, Input, PageTitle } from '@/components/ui'
import { cn } from '@/lib/cn'
import { api, type ChatReply } from '@/lib/api'
import { OUTCOME_LABEL, TOOL_LABEL, VIOLATION_LABEL } from '@/lib/labels'

interface Turn {
  role: 'user' | 'assistant'
  text: string
  reply?: ChatReply
  rating?: 1 | -1
}

const SUGGESTIONS = [
  '¿Cuánto debo?',
  'Puedo pagar $150 el viernes',
  '¿Cómo pago por transferencia?',
  'Envíame la factura',
  'Ya pagué esa factura',
  '¿Puedo pagar en 3 cuotas?',
  'Quiero hablar con una persona',
]

export function SimulatorPage() {
  const queryClient = useQueryClient()
  const customers = useQuery({ queryKey: ['customers'], queryFn: api.customers })
  const [customerId, setCustomerId] = useState('')
  const [conversationId, setConversationId] = useState<string>()
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)

  const selected = customerId || customers.data?.[0]?.id || ''
  const send = useMutation({
    mutationFn: (message: string) => api.chat(selected, message, conversationId),
    onSuccess: (reply) => {
      setConversationId(reply.conversation_id)
      setTurns((t) => [...t, { role: 'assistant', text: reply.answer, reply }])
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  const rate = useMutation({
    mutationFn: ({ id, rating }: { id: string; rating: 1 | -1 }) => api.rate(id, rating),
  })

  useEffect(() => end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), [turns.length])

  const submit = (message: string) => {
    if (!message.trim() || !selected) return
    setTurns((t) => [...t, { role: 'user', text: message }])
    setText('')
    send.mutate(message)
  }
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    submit(text)
  }
  const reset = (id: string) => {
    setCustomerId(id)
    setConversationId(undefined)
    setTurns([])
  }

  return (
    <>
      <PageTitle
        title="Simulador de cliente"
        hint="Conversa como si fueras un cliente de la cartera. En producción el canal (WhatsApp o la web con sesión) identifica al cliente."
      />
      <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
        <Card className="flex h-[36rem] flex-col p-0">
          <div className="flex items-center gap-3 border-b border-border px-4 py-3">
            <label htmlFor="customer" className="text-sm text-muted">
              Cliente
            </label>
            <select
              id="customer"
              className="flex-1 rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
              value={selected}
              onChange={(e) => reset(e.target.value)}
            >
              {customers.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.code})
                </option>
              ))}
            </select>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
            {turns.length === 0 && (
              <p className="text-center text-sm text-muted">
                Escribe un mensaje o elige una sugerencia.
              </p>
            )}
            {turns.map((turn, index) => (
              <div
                key={index}
                className={cn('flex', turn.role === 'user' ? 'justify-end' : 'justify-start')}
              >
                <div
                  className={cn(
                    'max-w-[80%] rounded-2xl px-4 py-2.5 text-sm',
                    turn.role === 'user'
                      ? 'bg-brand text-white'
                      : 'border border-border bg-surface',
                  )}
                >
                  <p className="whitespace-pre-wrap">{turn.text}</p>
                  {turn.reply && (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Badge tone={turn.reply.outcome === 'resolved' ? 'ok' : 'warn'}>
                        {OUTCOME_LABEL[turn.reply.outcome]}
                      </Badge>
                      {turn.reply.tools.map((t, i) => (
                        <Badge key={`${t}-${i}`}>
                          <Wrench className="size-3" aria-hidden="true" />
                          {TOOL_LABEL[t] ?? t}
                        </Badge>
                      ))}
                      {turn.reply.violations.map((v) => (
                        <Badge key={v} tone="bad">
                          <ShieldAlert className="size-3" aria-hidden="true" />
                          {VIOLATION_LABEL[v] ?? v}
                        </Badge>
                      ))}
                      <span className="ml-auto flex gap-1">
                        {([1, -1] as const).map((r) => (
                          <button
                            key={r}
                            type="button"
                            aria-label={r === 1 ? 'Respuesta útil' : 'Respuesta no útil'}
                            aria-pressed={turn.rating === r}
                            className={cn(
                              'rounded p-1 text-muted hover:text-ink',
                              turn.rating === r && 'text-brand',
                            )}
                            onClick={() => {
                              const id = turn.reply?.message_id
                              if (!id) return
                              rate.mutate({ id, rating: r })
                              setTurns((all) =>
                                all.map((t, i) => (i === index ? { ...t, rating: r } : t)),
                              )
                            }}
                          >
                            {r === 1 ? (
                              <ThumbsUp className="size-3.5" />
                            ) : (
                              <ThumbsDown className="size-3.5" />
                            )}
                          </button>
                        ))}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {send.isPending && <p className="text-sm text-muted">El agente está respondiendo…</p>}
            <div ref={end} />
          </div>
          <form onSubmit={onSubmit} className="flex gap-2 border-t border-border p-3">
            <Input
              aria-label="Mensaje"
              placeholder="Escribe como cliente…"
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={2000}
            />
            <Button type="submit" disabled={send.isPending || !text.trim()}>
              <Send className="size-4" aria-hidden="true" />
              <span className="sr-only">Enviar</span>
            </Button>
          </form>
          <div className="px-3 pb-3">
            <ErrorText error={send.error} />
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <h2 className="text-sm font-semibold">Pruebas sugeridas</h2>
            <div className="mt-3 flex flex-col gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  disabled={send.isPending}
                  onClick={() => submit(s)}
                  className="rounded-lg border border-border px-3 py-2 text-left text-sm hover:bg-surface"
                >
                  {s}
                </button>
              ))}
            </div>
          </Card>
          <Card>
            <h2 className="text-sm font-semibold">Qué se envía al portal</h2>
            <p className="mt-2 text-xs text-muted">
              Por cada mensaje: etapas recorridas, modelo y tokens, herramientas y su fuente,
              controles aplicados, resultado y valoración. El texto de la conversación queda solo en
              esta instalación.
            </p>
            {turns.at(-1)?.reply && (
              <p className="mt-3 font-mono text-[11px] break-all text-muted">
                traza {turns.at(-1)?.reply?.trace_id}
              </p>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}
