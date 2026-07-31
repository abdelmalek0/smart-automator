import { useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Bot, Play, Sparkles } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { listRuns } from '@/api'
import { Button } from '@/components/ui/button'
import RunThreadList from '@/components/RunThreadList'
import { useRunModal } from '@/contexts/RunModalContext'
import { useProjects } from '@/hooks/useProjects'

export default function HomePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { openNewRun } = useRunModal()
  const { projects } = useProjects()
  const projectNames = useMemo(
    () => Object.fromEntries(projects.map((project) => [project.id, project.name])),
    [projects],
  )
  const { data: runs = [] } = useQuery({
    queryKey: ['runs'],
    queryFn: listRuns,
    refetchInterval: 3000,
  })

  useEffect(() => {
    if (searchParams.get('new') === '1') {
      openNewRun()
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams, openNewRun])

  const hasRuns = runs.length > 0

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-3xl mx-auto px-8 py-16 text-center">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 text-primary mb-6">
          <Bot className="h-8 w-8" />
        </div>
        <h1 className="text-3xl font-bold tracking-tight mb-3">Smart Automator</h1>
        <p className="text-muted-foreground max-w-lg mx-auto mb-8 leading-relaxed">
          Self-healing QA automation powered by CDP and LLM. Launch a run to watch the agent
          test your application in real time.
        </p>
        <Button size="lg" onClick={() => openNewRun()}>
          <Play className="h-4 w-4" />
          New Run
        </Button>
      </div>

      {hasRuns && (
        <div className="max-w-3xl mx-auto px-8 pb-12">
          <div className="flex items-center gap-2 mb-4">
            <Sparkles className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold">Recent Runs</h2>
          </div>
          <RunThreadList runs={runs} variant="home" limit={5} projectNames={projectNames} />
        </div>
      )}
    </div>
  )
}
