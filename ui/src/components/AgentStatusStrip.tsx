import {
  AnimatePresence,
  motion,
  useReducedMotion,
  type Variants,
} from 'motion/react'
import { useRunStartGate, type AgentPhase } from '@/hooks/useRunStartGate'
import { EASE_OUT } from '@/lib/ease'
import { elapsedSeconds, formatElapsed } from '@/lib/run-status'
import { cn } from '@/lib/utils'

const PHASE_TITLE: Record<AgentPhase, string> = {
  offline: 'Agent is offline',
  connected: 'Agent is connected',
  starting: 'Agent is starting…',
  running: 'Agent is running',
  awaiting_human: 'Agent is recording',
}

const PHASE_DOT: Record<AgentPhase, string> = {
  offline: 'bg-destructive',
  connected: 'bg-success',
  starting: 'bg-warning',
  running: 'bg-brand-blue',
  awaiting_human: 'bg-warning',
}

const PHASE_SURFACE: Record<AgentPhase, string> = {
  offline: 'border-destructive/30 bg-destructive/10 text-destructive',
  connected: 'border-success/30 bg-success/10 text-success',
  starting: 'border-warning/30 bg-warning/10 text-warning',
  running: 'border-brand-blue/30 bg-brand-blue/10 text-brand-blue',
  awaiting_human: 'border-warning/30 bg-warning/10 text-warning',
}

const ICON_ROLL_VARIANTS: Variants = {
  initial: {
    opacity: 0.72,
    y: '80%',
    scale: 0.92,
    rotate: -8,
    filter: 'blur(6px)',
  },
  animate: {
    opacity: 1,
    y: '0%',
    scale: 1,
    rotate: 0,
    filter: 'blur(0px)',
    transition: {
      y: { type: 'spring', stiffness: 210, damping: 24, mass: 0.85 },
      scale: { type: 'spring', stiffness: 250, damping: 24, mass: 0.75 },
      rotate: { duration: 0.28, ease: EASE_OUT },
      opacity: { duration: 0.28, ease: EASE_OUT },
      filter: { duration: 0.42, ease: EASE_OUT },
    },
  },
  exit: {
    opacity: 0.5,
    y: '-80%',
    scale: 0.96,
    rotate: 8,
    filter: 'blur(6px)',
    transition: { duration: 0.22, ease: EASE_OUT },
  },
}

const TEXT_ROLL_VARIANTS: Variants = {
  initial: { opacity: 0.76, y: '85%', filter: 'blur(6px)' },
  animate: {
    opacity: 1,
    y: '0%',
    filter: 'blur(0px)',
    transition: {
      y: { type: 'spring', stiffness: 210, damping: 24, mass: 0.85 },
      opacity: { duration: 0.3, ease: EASE_OUT },
      filter: { duration: 0.42, ease: EASE_OUT },
    },
  },
  exit: {
    opacity: 0.5,
    y: '-85%',
    filter: 'blur(6px)',
    transition: { duration: 0.2, ease: EASE_OUT },
  },
}

interface Props {
  embedded?: boolean
}

export default function AgentStatusStrip({ embedded = false }: Props) {
  const { agentPhase, activeRun } = useRunStartGate()
  const reduce = useReducedMotion()

  const title = PHASE_TITLE[agentPhase]
  const runLabel = activeRun ? activeRun.name || activeRun.task : null
  const duration =
    activeRun
      ? formatElapsed(elapsedSeconds(activeRun.started_at, activeRun.finished_at))
      : null

  const subline =
    runLabel && duration ? `${runLabel} · ${duration}` : runLabel
  const hint = subline ?? (agentPhase === 'offline' ? 'Run the Connect app' : null)
  const pulse = agentPhase === 'starting' || agentPhase === 'running'

  return (
    <motion.div
      layout
      transition={{ type: 'spring', stiffness: 420, damping: 30, mass: 0.7 }}
      className={cn(
        'relative w-full min-w-0 overflow-hidden rounded-md border transition-colors duration-300',
        PHASE_SURFACE[agentPhase],
        embedded ? 'px-2.5 py-2' : 'mx-3 mb-2 px-2.5 py-2',
      )}
      role="status"
      aria-live="polite"
      aria-atomic="true"
      title={subline ?? title}
    >
      {pulse && !reduce ? (
        <motion.span
          aria-hidden
          className="absolute inset-0 rounded-md bg-current opacity-10"
          animate={{ scale: [0.94, 1.08, 0.94], opacity: [0.08, 0.16, 0.08] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
        />
      ) : null}
      <div className="relative z-10 flex min-w-0 items-center gap-2">
        <span className="inline-flex shrink-0 items-center justify-center overflow-hidden">
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.span
              key={agentPhase}
              aria-hidden
              variants={ICON_ROLL_VARIANTS}
              initial={reduce ? false : 'initial'}
              animate={reduce ? { opacity: 1 } : 'animate'}
              exit={reduce ? undefined : 'exit'}
              className="inline-flex will-change-transform"
            >
              <span
                className={cn('inline-block h-2 w-2 shrink-0 rounded-full', PHASE_DOT[agentPhase])}
              />
            </motion.span>
          </AnimatePresence>
        </span>
        <span className="inline-flex min-w-0 overflow-hidden text-xs font-semibold leading-snug">
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.span
              key={title}
              variants={TEXT_ROLL_VARIANTS}
              initial={reduce ? false : 'initial'}
              animate={reduce ? { opacity: 1 } : 'animate'}
              exit={reduce ? undefined : 'exit'}
              className="inline-block truncate will-change-transform"
            >
              {title}
            </motion.span>
          </AnimatePresence>
        </span>
      </div>
      {hint ? (
        <span className="relative z-10 mt-0.5 flex overflow-hidden pl-4 text-[11px] text-muted-foreground">
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.span
              key={runLabel ?? agentPhase}
              variants={TEXT_ROLL_VARIANTS}
              initial={reduce ? false : 'initial'}
              animate={reduce ? { opacity: 1 } : 'animate'}
              exit={reduce ? undefined : 'exit'}
              className="inline-block truncate will-change-transform"
            >
              {hint}
            </motion.span>
          </AnimatePresence>
        </span>
      ) : null}
    </motion.div>
  )
}
