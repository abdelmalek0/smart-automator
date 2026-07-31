import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAuthSetup, getMe, login, logout, register } from '@/api'
import type { AuthUser } from '@/types'

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  needsRegistration: boolean
  registrationOpen: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  const setupQuery = useQuery({
    queryKey: ['auth', 'setup'],
    queryFn: getAuthSetup,
    staleTime: 60_000,
  })

  const meQuery = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: getMe,
    retry: false,
    staleTime: 30_000,
  })

  const loginMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      login(username, password),
    onSuccess: (data) => {
      queryClient.setQueryData(['auth', 'me'], data)
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })

  const registerMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      register(username, password),
    onSuccess: (data) => {
      const previous = queryClient.getQueryData<{
        needs_registration?: boolean
        registration_open?: boolean
      }>(['auth', 'setup'])
      queryClient.setQueryData(['auth', 'setup'], {
        needs_registration: false,
        registration_open: previous?.registration_open ?? false,
      })
      queryClient.setQueryData(['auth', 'me'], data)
      void queryClient.invalidateQueries({ queryKey: ['auth', 'setup'] })
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })

  const logoutMutation = useMutation({
    mutationFn: logout,
  })

  const handleLogin = useCallback(
    async (username: string, password: string) => {
      await loginMutation.mutateAsync({ username, password })
    },
    [loginMutation],
  )

  const handleRegister = useCallback(
    async (username: string, password: string) => {
      await registerMutation.mutateAsync({ username, password })
    },
    [registerMutation],
  )

  const handleLogout = useCallback(async () => {
    try {
      await logoutMutation.mutateAsync()
    } finally {
      // Drop all cached user data so the next login cannot briefly show the previous user's runs.
      queryClient.clear()
    }
  }, [logoutMutation, queryClient])

  const value = useMemo<AuthContextValue>(
    () => ({
      user: meQuery.data?.user ?? null,
      loading: setupQuery.isLoading || meQuery.isLoading,
      needsRegistration: setupQuery.data?.needs_registration ?? false,
      registrationOpen: setupQuery.data?.registration_open ?? false,
      login: handleLogin,
      register: handleRegister,
      logout: handleLogout,
    }),
    [
      meQuery.data,
      meQuery.isLoading,
      setupQuery.data,
      setupQuery.isLoading,
      handleLogin,
      handleRegister,
      handleLogout,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
