import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { PricingEntry } from '@/types'

const PROVIDERS = ['groq', 'google', 'openrouter', 'ollama-cloud', 'ollama'] as const

const cellInput =
  'h-8 text-xs mono shadow-none border-transparent bg-transparent hover:border-input hover:bg-background focus-visible:bg-background focus-visible:border-input'

export default function PricingSettings({
  pricing,
  onUpdateRow,
  onRemoveRow,
  onAddRow,
}: {
  pricing: PricingEntry[]
  onUpdateRow: (index: number, field: keyof PricingEntry, value: string) => void
  onRemoveRow: (index: number) => void
  onAddRow: () => void
}) {
  return (
    <section className="rounded-xl border border-border/70 bg-card/50 overflow-hidden">
      <div className="px-5 py-4 border-b border-border/50">
        <h3 className="text-sm font-semibold tracking-tight">Token pricing</h3>
        <p className="text-xs text-muted-foreground mt-0.5">
          USD per 1 million tokens — used for cost shown on each run.
        </p>
      </div>

      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-[150px] text-[11px] uppercase tracking-wide">Provider</TableHead>
            <TableHead className="text-[11px] uppercase tracking-wide">Model</TableHead>
            <TableHead className="w-[92px] text-right text-[11px] uppercase tracking-wide">
              Input
            </TableHead>
            <TableHead className="w-[92px] text-right text-[11px] uppercase tracking-wide">
              Output
            </TableHead>
            <TableHead className="w-[100px] text-right text-[11px] uppercase tracking-wide">
              Cache
            </TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {pricing.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={6} className="text-sm text-muted-foreground py-10 text-center">
                No models yet. Add a row to start tracking cost.
              </TableCell>
            </TableRow>
          ) : (
            pricing.map((row, i) => (
              <TableRow key={i} className="hover:bg-muted/20">
                <TableCell className="py-1.5">
                  <Select
                    value={row.provider}
                    onValueChange={(v) => onUpdateRow(i, 'provider', v)}
                  >
                    <SelectTrigger className="h-8 text-xs shadow-none border-transparent bg-transparent hover:border-input hover:bg-background">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PROVIDERS.map((id) => (
                        <SelectItem key={id} value={id}>
                          {id}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell className="py-1.5">
                  <Input
                    value={row.model}
                    onChange={(e) => onUpdateRow(i, 'model', e.target.value)}
                    placeholder="model-name"
                    className={cellInput}
                  />
                </TableCell>
                {(['input', 'output', 'cache_read'] as const).map((field) => (
                  <TableCell key={field} className="py-1.5">
                    <Input
                      type="number"
                      min="0"
                      step="0.01"
                      value={row[field]}
                      onChange={(e) => onUpdateRow(i, field, e.target.value)}
                      className={`${cellInput} text-right`}
                    />
                  </TableCell>
                ))}
                <TableCell className="py-1.5">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground/70 hover:text-destructive"
                    onClick={() => onRemoveRow(i)}
                    aria-label="Remove row"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      <button
        type="button"
        onClick={onAddRow}
        className="w-full flex items-center justify-center gap-2 py-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-accent/40 border-t border-border/40 transition-colors"
      >
        <Plus className="h-3.5 w-3.5" />
        Add model
      </button>
    </section>
  )
}
