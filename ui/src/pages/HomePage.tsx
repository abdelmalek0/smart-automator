import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Bot, Play, Sparkles } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { listRuns } from '@/api'
import NewRunModal from '@/components/NewRunModal'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { statusBadgeVariant, statusLabel, elapsedSeconds, formatElapsed } from '@/lib/run-status'

export default function HomePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [showNewRun, setShowNewRun] = useState(searchParams.get('new') === '1')
  const { data: runs = [] } = useQuery({
    queryKey: ['runs'],
    queryFn: listRuns,
    refetchInterval: 3000,
  })

  useEffect(() => {
    if (searchParams.get('new') === '1') {
      setShowNewRun(true)
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

  const recentRuns = runs.slice(0, 5)

  return (
    <>
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
          <Button size="lg" onClick={() => setShowNewRun(true)}>
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
                <Link key={run.run_id} to={`/runs/${run.run_id}`}>
                  <Card className="hover:bg-accent/30 transition-colors cursor-pointer">
                    <CardHeader className="py-3 px-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 text-left">
                          <CardTitle className="text-sm font-medium line-clamp-2 mb-1">
                            {run.task}
                          </CardTitle>
                          <CardDescription className="text-xs">
                            {formatElapsed(elapsedSeconds(run.started_at, run.finished_at))} ·{' '}
                            {run.step_count} steps
                          </CardDescription>
                        </div>
                        <Badge variant={statusBadgeVariant(run.status)} className="shrink-0">
                          {statusLabel(run.status)}
                        </Badge>
                      </div>
                    </CardHeader>
                  </Card>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>

      {showNewRun && <NewRunModal onClose={() => setShowNewRun(false)} />}
    </>
  )
}
