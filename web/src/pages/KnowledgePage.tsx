import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { type FormEvent, useState } from 'react'

import { Button, Card, ErrorText, Input, Label, PageTitle, Textarea } from '@/components/ui'
import { api, dateTime, type DocumentRow } from '@/lib/api'
import { useUser } from '@/lib/session'

function Editor({ doc, onDone }: { doc?: DocumentRow; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState(doc?.title ?? '')
  const [body, setBody] = useState(doc?.body ?? '')
  const save = useMutation({
    mutationFn: () =>
      doc ? api.updateDocument(doc.id, title, body) : api.createDocument(title, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['documents'] })
      onDone()
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <Label htmlFor="doc-title">Título</Label>
        <Input
          id="doc-title"
          required
          minLength={2}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>
      <div>
        <Label htmlFor="doc-body">Contenido</Label>
        <Textarea
          id="doc-body"
          required
          minLength={10}
          rows={5}
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          Guardar
        </Button>
        <Button variant="ghost" onClick={onDone}>
          Cancelar
        </Button>
      </div>
      <ErrorText error={save.error} />
    </form>
  )
}

export function KnowledgePage() {
  const user = useUser()
  const queryClient = useQueryClient()
  const docs = useQuery({ queryKey: ['documents'], queryFn: api.documents })
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const remove = useMutation({
    mutationFn: api.deleteDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
  })
  const isAdmin = user.role === 'admin'

  return (
    <>
      <PageTitle
        title="Conocimiento"
        hint="Políticas y respuestas que el agente usa al contestar. Cada cambio actualiza la fecha de la fuente: el portal avisa si la información queda desactualizada."
        actions={
          isAdmin && (
            <Button onClick={() => setEditing('new')}>
              <Plus className="size-4" aria-hidden="true" /> Agregar
            </Button>
          )
        }
      />
      {editing === 'new' && (
        <Card className="mb-4">
          <Editor onDone={() => setEditing(null)} />
        </Card>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {docs.data?.map((doc) => (
          <Card key={doc.id}>
            {editing === doc.id ? (
              <Editor doc={doc} onDone={() => setEditing(null)} />
            ) : (
              <>
                <div className="flex items-start justify-between gap-2">
                  <h2 className="font-medium">{doc.title}</h2>
                  {isAdmin && (
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        className="px-2 py-1"
                        onClick={() => setEditing(doc.id)}
                      >
                        Editar
                      </Button>
                      <Button
                        variant="ghost"
                        className="px-2 py-1"
                        aria-label={`Eliminar ${doc.title}`}
                        onClick={() => {
                          if (window.confirm(`¿Eliminar "${doc.title}"?`)) remove.mutate(doc.id)
                        }}
                      >
                        <Trash2 className="size-4" aria-hidden="true" />
                      </Button>
                    </div>
                  )}
                </div>
                <p className="mt-2 text-sm text-muted">{doc.body}</p>
                <p className="mt-3 text-xs text-muted">Actualizado {dateTime(doc.updated_at)}</p>
              </>
            )}
          </Card>
        ))}
      </div>
    </>
  )
}
