import { createContext, useContext } from 'react'

import type { User } from '@/lib/api'

export const SessionContext = createContext<User | null>(null)

export function useUser(): User {
  const user = useContext(SessionContext)
  if (!user) throw new Error('Sin sesión')
  return user
}
