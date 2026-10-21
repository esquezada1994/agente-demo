import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Upload } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Badge, Button, Card, ErrorText, PageTitle, Textarea } from '@/components/ui'
import { cn } from '@/lib/cn'
import { api, dateTime, type Catalog, type FlowEdge, type FlowNode } from '@/lib/api'
import { STAGE_LABEL } from '@/lib/labels'
import { useUser } from '@/lib/session'

const W = 168
const H = 60

interface Box {
  id: string
  x: number
  y: number
  w: number
  h: number
  label: string
  type?: string
  stage?: string
}

/** Punto donde la línea entre dos centros cruza el borde de la caja destino. */
function clip(from: Box, to: Box) {
  const cx = to.x + to.w / 2
  const cy = to.y + to.h / 2
  const dx = from.x + from.w / 2 - cx
  const dy = from.y + from.h / 2 - cy
  const scale = 1 / Math.max(Math.abs(dx) / (to.w / 2), Math.abs(dy) / (to.h / 2), 1e-6)
  return { x: cx + dx * scale, y: cy + dy * scale }
}

/**
 * Vista del flujo tal como lo dibujaría un canvas: misma estructura (nodos con
 * posición, conexiones con su condición). El color marca la etapa de gobierno.
 */
function FlowView({
  nodes,
  edges,
  catalog,
}: {
  nodes: FlowNode[]
  edges: FlowEdge[]
  catalog?: Catalog
}) {
  const boxes = useMemo(() => {
    const map = new Map<string, Box>()
    nodes.forEach((n, i) => {
      const p = n.position ?? { x: i * 220, y: 0 }
      map.set(n.id, {
        id: n.id,
        x: p.x + 110,
        y: p.y + 40,
        w: W,
        h: H,
        label: n.label ?? n.id,
        type: n.type,
        stage: catalog?.node_types[n.type]?.stage,
      })
    })
    const first = edges.find((e) => e.from === 'START')
    const firstBox = first ? map.get(first.to) : undefined
    map.set('START', {
      id: 'START',
      x: 10,
      y: (firstBox?.y ?? 30) + H / 2 - 16,
      w: 70,
      h: 32,
      label: 'Inicio',
    })
    const last = edges.find((e) => e.to === 'END')
    const lastBox = last ? map.get(last.from) : undefined
    map.set('END', {
      id: 'END',
      x: (lastBox?.x ?? 0) + W + 50,
      y: (lastBox?.y ?? 30) + H / 2 - 16,
      w: 70,
      h: 32,
      label: 'Fin',
    })
    return map
  }, [nodes, edges, catalog])

  const all = [...boxes.values()]
  const width = Math.max(...all.map((b) => b.x + b.w)) + 20
  const height = Math.max(...all.map((b) => b.y + b.h)) + 30
  const grouped = new Map<string, string[]>()
  edges.forEach((e) => {
    const key = `${e.from}>${e.to}`
    grouped.set(key, [...(grouped.get(key) ?? []), e.when ?? ''])
  })

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full min-w-[44rem]"
        role="img"
        aria-label="Diagrama del flujo"
      >
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" className="fill-muted" />
          </marker>
        </defs>
        {[...grouped.entries()].map(([key, whens]) => {
          const [fromId, toId] = key.split('>')
          const a = boxes.get(fromId ?? '')
          const b = boxes.get(toId ?? '')
          if (!a || !b) return null
          const label = whens.filter((w) => w && w !== 'next').join(' / ')
          // Misma fila y no contiguos: un arco por encima para no cruzar los nodos.
          if (Math.abs(a.y - b.y) < 1 && Math.abs(b.x - a.x) > W + 80) {
            const x1 = a.x + a.w / 2
            const x2 = b.x + b.w / 2
            const top = a.y - 22
            return (
              <g key={key}>
                <path
                  d={`M${x1},${a.y} C${x1},${top} ${x2},${top} ${x2},${b.y}`}
                  className="fill-none stroke-muted"
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  markerEnd="url(#arrow)"
                />
                {label && (
                  <text
                    x={(x1 + x2) / 2}
                    y={top + 4}
                    textAnchor="middle"
                    className="fill-muted text-[10px]"
                  >
                    {label}
                  </text>
                )}
              </g>
            )
          }
          const start = clip(b, a)
          const end = clip(a, b)
          return (
            <g key={key}>
              <line
                x1={start.x}
                y1={start.y}
                x2={end.x}
                y2={end.y}
                className="stroke-muted"
                strokeWidth={1.5}
                markerEnd="url(#arrow)"
              />
              {label && (
                <text
                  x={(start.x + end.x) / 2 + 6}
                  y={(start.y + end.y) / 2 - 6}
                  className="fill-muted text-[10px]"
                >
                  {label}
                </text>
              )}
            </g>
          )
        })}
        {all.map((b) => (
          <g key={b.id}>
            <rect
              x={b.x}
              y={b.y}
              width={b.w}
              height={b.h}
              rx={b.type ? 10 : 16}
              className={cn(b.type ? 'fill-card stroke-border' : 'fill-surface stroke-border')}
              strokeWidth={1.5}
            />
            {b.stage && (
              <rect x={b.x} y={b.y} width={5} height={b.h} rx={2} className="fill-brand" />
            )}
            <text
              x={b.x + (b.type ? 16 : b.w / 2)}
              y={b.y + (b.type ? 24 : b.h / 2 + 4)}
              textAnchor={b.type ? 'start' : 'middle'}
              className="fill-ink text-[12px] font-medium"
            >
              {b.label}
            </text>
            {b.type && (
              <text x={b.x + 16} y={b.y + 43} className="fill-muted text-[10px]">
                {b.type} · {STAGE_LABEL[b.stage ?? ''] ?? ''}
              </text>
            )}
          </g>
        ))}
      </svg>
    </div>
  )
}

export function AgentPage() {
  const user = useUser()
  const queryClient = useQueryClient()
  const definition = useQuery({ queryKey: ['definition'], queryFn: api.definition })
  const catalog = useQuery({ queryKey: ['catalog'], queryFn: api.catalog })
  const [flow, setFlow] = useState('chat')
  const [draft, setDraft] = useState<string | null>(null)
  const [check, setCheck] = useState<{ valid: boolean; errors: string[] } | null>(null)

  const source = draft ?? (definition.data ? JSON.stringify(definition.data.active, null, 2) : '')
  const parsed = (() => {
    try {
      return JSON.parse(source) as unknown
    } catch {
      return null
    }
  })()
  const validate = useMutation({
    mutationFn: () => api.validateDefinition(parsed),
    onSuccess: setCheck,
  })
  const publish = useMutation({
    mutationFn: () => api.publishDefinition(parsed),
    onSuccess: async () => {
      setDraft(null)
      setCheck(null)
      await queryClient.invalidateQueries({ queryKey: ['definition'] })
    },
  })

  if (definition.isPending) return <p className="text-sm text-muted">Cargando…</p>
  if (definition.isError) return <p role="alert">No se pudo cargar la definición.</p>
  const d = definition.data.active
  const current = d.flows[flow]

  return (
    <>
      <PageTitle
        title={d.name}
        hint="El agente es esta definición: nodos, conexiones, herramientas y políticas. Un editor visual (canvas) editaría exactamente la misma estructura."
        actions={<Badge tone="brand">Versión {d.version}</Badge>}
      />

      <Card>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {Object.keys(d.flows).map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => setFlow(name)}
              className={cn(
                'rounded-lg px-3 py-1.5 text-sm',
                flow === name
                  ? 'bg-brand-soft font-medium text-brand'
                  : 'text-muted hover:text-ink',
              )}
            >
              {name === 'chat'
                ? 'Conversación con el cliente'
                : name === 'reminder'
                  ? 'Redacción de recordatorios'
                  : name}
            </button>
          ))}
        </div>
        {current && <FlowView nodes={current.nodes} edges={current.edges} catalog={catalog.data} />}
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <h2 className="text-sm font-semibold">Herramientas habilitadas</h2>
          <ul className="mt-3 space-y-2 text-sm">
            {d.tools.map((t) => {
              const info = catalog.data?.tools[t.name]
              return (
                <li key={t.name}>
                  <p className="font-mono text-xs">{t.name}</p>
                  <p className="text-xs text-muted">{info?.description}</p>
                  <div className="mt-1 flex gap-1">
                    <Badge>{info?.writes ? 'Escribe' : 'Solo lectura'}</Badge>
                    {info?.requires_approval && <Badge tone="warn">Requiere aprobación</Badge>}
                  </div>
                </li>
              )
            })}
          </ul>
        </Card>
        <Card>
          <h2 className="text-sm font-semibold">Modelos y persona</h2>
          <dl className="mt-3 space-y-2 text-sm">
            <div>
              <dt className="text-xs text-muted">Modelo principal · económico</dt>
              <dd className="font-mono text-xs">
                {d.models.main} · {d.models.small ?? '—'}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Nombre y empresa</dt>
              <dd>
                {d.persona.name} · {d.persona.company}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Tono</dt>
              <dd>{d.persona.tone}</dd>
            </div>
          </dl>
        </Card>
        <Card>
          <h2 className="text-sm font-semibold">Versiones publicadas</h2>
          <ul className="mt-3 space-y-1.5 text-sm">
            {definition.data.history.map((h) => (
              <li key={h.version + h.created_at} className="flex justify-between gap-2">
                <span className="font-mono text-xs">
                  {h.version}{' '}
                  {h.active && (
                    <CheckCircle2 className="inline size-3.5 text-ok-fg" aria-label="activa" />
                  )}
                </span>
                <span className="text-xs text-muted">{dateTime(h.created_at)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">
            Cada versión se publica en el portal como un manifiesto nuevo.
          </p>
        </Card>
      </div>

      {user.role === 'admin' && (
        <Card className="mt-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">Editar definición (JSON)</h2>
              <p className="text-xs text-muted">
                Se valida el grafo completo antes de publicar: un flujo roto no llega a producción.
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={!parsed || validate.isPending}
                onClick={() => validate.mutate()}
              >
                Validar
              </Button>
              <Button
                disabled={!parsed || publish.isPending || draft === null}
                onClick={() => publish.mutate()}
              >
                <Upload className="size-4" aria-hidden="true" /> Publicar versión
              </Button>
            </div>
          </div>
          {!parsed && <p className="mt-2 text-sm text-bad-fg">El JSON no es válido.</p>}
          {check && (
            <div
              className={cn(
                'mt-3 rounded-lg px-4 py-2 text-sm',
                check.valid ? 'bg-ok-bg text-ok-fg' : 'bg-bad-bg text-bad-fg',
              )}
            >
              {check.valid
                ? 'La definición es válida.'
                : check.errors.map((e) => <p key={e}>{e}</p>)}
            </div>
          )}
          {publish.data && (
            <p className="mt-3 rounded-lg bg-ok-bg px-4 py-2 text-sm text-ok-fg">
              Publicada la versión {publish.data.version}
              {publish.data.manifest_published ? ' y su manifiesto en el portal.' : '.'}
            </p>
          )}
          <ErrorText error={publish.error} />
          <Textarea
            aria-label="Definición en JSON"
            className="mt-3 h-96 font-mono text-xs"
            spellCheck={false}
            value={source}
            onChange={(e) => {
              setDraft(e.target.value)
              setCheck(null)
            }}
          />
        </Card>
      )}
    </>
  )
}
