import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import NewRunModal from '@/components/NewRunModal'
import type { RunDraft } from '@/types'

interface RunModalContextValue {
  openNewRun: (draft?: RunDraft) => void
  closeNewRun: () => void
}

const RunModalContext = createContext<RunModalContextValue | null>(null)

export function RunModalProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<RunDraft | undefined>()

  const openNewRun = useCallback((nextDraft?: RunDraft) => {
    setDraft(nextDraft)
    setOpen(true)
  }, [])

  const closeNewRun = useCallback(() => {
    setOpen(false)
    setDraft(undefined)
  }, [])

  const value = useMemo(
    () => ({ openNewRun, closeNewRun }),
    [openNewRun, closeNewRun],
  )

  return (
    <RunModalContext.Provider value={value}>
      {children}
      {open && <NewRunModal initialValues={draft} onClose={closeNewRun} />}
    </RunModalContext.Provider>
  )
}

export function useRunModal() {
  const ctx = useContext(RunModalContext)
  if (!ctx) {
    throw new Error('useRunModal must be used within RunModalProvider')
  }
  return ctx
}
