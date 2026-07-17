import { useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Bot, Play, RotateCcw, Sparkles } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { listRuns } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useRunModal } from '@/contexts/RunModalContext'
import { runSummaryToDraft } from '@/lib/run-draft'
import { statusBadgeVariant, statusLabel, elapsedSeconds, formatElapsed } from '@/lib/run-status'

export default function HomePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { openNewRun } = useRunModal()
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

  const recentRuns = runs.slice(0, 5)

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

      {recentRuns.length > 0 && (
        <div className="max-w-3xl mx-auto px-8 pb-12">
          <div className="flex items-center gap-2 mb-4">
            <Sparkles className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold">Recent Runs</h2>
          </div>
          <div className="space-y-2">
            {recentRuns.map((run) => (
              <Card key={run.run_id} className="hover:bg-accent/30 transition-colors">
                <CardHeader className="py-3 px-4">
                  <div className="flex items-start justify-between gap-3">
                    <Link to={`/runs/${run.run_id}`} className="min-w-0 text-left flex-1">
                      <CardTitle className="text-sm font-medium line-clamp-2 mb-1">
                        {run.name || run.task}
                      </CardTitle>
                      <CardDescription className="text-xs">
                        {formatElapsed(elapsedSeconds(run.started_at, run.finished_at))} ·{' '}
                        {run.step_count} steps
                      </CardDescription>
                    </Link>
                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-8"
                        title="Re-run"
                        onClick={() => openNewRun(runSummaryToDraft(run))}
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                      </Button>
                      <Badge variant={statusBadgeVariant(run.status)}>
                        {statusLabel(run.status)}
                      </Badge>
                    </div>
                  </div>
                </CardHeader>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
