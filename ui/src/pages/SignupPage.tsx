import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import logoUrl from '../../logo.jpeg'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export default function SignupPage() {
  const { user, loading, needsRegistration, registrationOpen, register } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (!loading && user) {
    return <Navigate to="/" replace />
  }

  if (!loading && !registrationOpen) {
    return <Navigate to="/login" replace />
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)

    const trimmed = username.trim()
    if (!trimmed) {
      setError('Username is required')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    setSubmitting(true)
    try {
      await register(trimmed, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign up failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-full flex items-center justify-center bg-gradient-to-br from-background via-secondary/20 to-background p-6">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-3">
          <img
            src={logoUrl}
            alt="Smart Automator"
            className="w-14 h-14 rounded-xl object-cover mx-auto ring-1 ring-border/60"
          />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Smart Automator</h1>
            <p className="text-sm text-muted-foreground mt-1">
              {needsRegistration
                ? 'Create the first account to get started'
                : 'Create an account to get started'}
            </p>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-xl border border-border/60 bg-card/80 p-6 shadow-sm"
        >
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              maxLength={64}
              required
              autoFocus
            />
            <p className="text-xs text-muted-foreground">No email required — just a username.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
            <p className="text-xs text-muted-foreground">At least 8 characters.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm-password">Confirm password</Label>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <Button type="submit" className="w-full" disabled={submitting || loading}>
            {submitting ? 'Creating account…' : 'Create account'}
          </Button>
        </form>

        {!needsRegistration ? (
          <p className="text-center text-sm text-muted-foreground">
            Already have an account?{' '}
            <Link to="/login" className="font-medium text-foreground underline-offset-4 hover:underline">
              Sign in
            </Link>
          </p>
        ) : null}
      </div>
    </div>
  )
}
