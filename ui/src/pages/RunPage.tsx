import { useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import RunView from '@/components/RunView'

export default function RunPage() {
  const { runId } = useParams<{ runId: string }>()
  const queryClient = useQueryClient()

  if (!runId) return null

  return (
    <RunView
      key={runId}
      runId={runId}
      onRunComplete={() => {
        queryClient.invalidateQueries({ queryKey: ['runs'] })
      }}
    />
  )
}
