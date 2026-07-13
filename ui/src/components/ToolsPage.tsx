import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Wrench } from 'lucide-react'
import { listTools } from '@/api'
import type { Tool } from '@/types'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'

function ToolCard({ tool }: { tool: Tool }) {
  return (
    <Accordion type="single" collapsible>
      <AccordionItem value={tool.name} className="border rounded-lg bg-card px-1">
        <AccordionTrigger className="px-3 py-2.5 hover:no-underline hover:bg-accent/30 rounded-lg">
          <div className="flex items-center gap-3 flex-1 min-w-0 text-left">
            <Wrench className="h-4 w-4 text-primary shrink-0" />
            <div className="min-w-0">
              <span className="mono text-sm text-primary font-medium">{tool.name}</span>
              <span className="mono text-xs text-muted-foreground ml-2">{tool.signature}</span>
            </div>
          </div>
        </AccordionTrigger>
        {tool.doc && (
          <AccordionContent className="px-4 pb-3 text-xs text-muted-foreground leading-relaxed">
            {tool.doc}
          </AccordionContent>
        )}
      </AccordionItem>
    </Accordion>
  )
}

export default function ToolsPage() {
  const { data: tools = [], isLoading, error } = useQuery({
    queryKey: ['tools'],
    queryFn: listTools,
  })
  const [filter, setFilter] = useState('')

  const filtered = filter
    ? tools.filter(
        (t) =>
          t.name.toLowerCase().includes(filter.toLowerCase()) ||
          t.doc.toLowerCase().includes(filter.toLowerCase()),
      )
    : tools

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-shrink-0 px-6 pt-6 pb-4 border-b border-border">
        <Card className="border-0 shadow-none bg-transparent">
          <CardHeader className="p-0 mb-4">
            <CardTitle className="text-lg">Browser Tools</CardTitle>
            <CardDescription>
              {tools.length > 0 ? `${tools.length} registered tools` : 'Agent browser automation tools'}
            </CardDescription>
          </CardHeader>
        </Card>
        <Input
          placeholder="Filter tools…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="mono"
        />
      </div>

      <ScrollArea className="flex-1 px-6 py-4">
        {isLoading && <p className="text-sm text-muted-foreground">Loading tools…</p>}
        {error && (
          <p className="text-sm text-destructive">
            Failed to load: {error instanceof Error ? error.message : 'unknown'}
          </p>
        )}
        <div className="space-y-2 max-w-3xl">
          {filtered.map((tool) => (
            <ToolCard key={tool.name} tool={tool} />
          ))}
          {!isLoading && filtered.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-12">No tools match your filter</p>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
