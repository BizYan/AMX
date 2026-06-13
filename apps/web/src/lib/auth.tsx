'use client'

import { createContext, useContext, ReactNode, useState, useEffect, useCallback } from 'react'
import { apiClient, authApi } from './api-client'
import type { User } from './api-client'

export type { User }

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

const TOKEN_KEY = 'auth_token'

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem(TOKEN_KEY, token)
    apiClient.setToken(token)
  }
}

export function clearToken(): void {
  if (typeof window !== 'undefined') {
    localStorage.removeItem(TOKEN_KEY)
    apiClient.setToken(null)
  }
}

export function isAuthenticated(): boolean {
  const token = getToken()
  return !!token
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

export function useCurrentUser() {
  const { user, refreshUser } = useAuth()

  return {
    data: user,
    refetch: refreshUser,
  }
}

interface AuthProviderProps {
  children: ReactNode
}

// Standalone login function - doesn't set user state, just authenticates
export async function login(email: string, password: string): Promise<void> {
  const { access_token } = await authApi.login(email, password)
  setToken(access_token)
  apiClient.setToken(access_token)
}

// Standalone logout function - doesn't clear user state, just deauthenticates
export async function logout(): Promise<void> {
  try {
    await authApi.logout()
  } catch (error) {
    console.error('Logout error:', error)
  } finally {
    clearToken()
  }
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null)
  const [hasToken, setHasToken] = useState(false)
  const [isLoading, setIsLoading] = useState(true)

  const refreshUser = useCallback(async () => {
    try {
      const token = getToken()
      if (!token) {
        setHasToken(false)
        setUser(null)
        return
      }

      setHasToken(true)
      apiClient.setToken(token)
      const userData = await authApi.me()
      setUser(userData)
    } catch (error) {
      if (error instanceof TypeError) {
        return
      }
      console.error('Failed to fetch current user:', error)
      clearToken()
      setHasToken(false)
      setUser(null)
    }
  }, [])

  useEffect(() => {
    const initAuth = async () => {
      setIsLoading(true)
      try {
        await refreshUser()
      } finally {
        setIsLoading(false)
      }
    }

    initAuth()
  }, [refreshUser])

  const handleLogin = async (email: string, password: string) => {
    await login(email, password)
    setHasToken(true)
    await refreshUser()
  }

  const handleLogout = async () => {
    await logout()
    setHasToken(false)
    setUser(null)
  }

  const value: AuthContextType = {
    user,
    isAuthenticated: hasToken,
    isLoading,
    login: handleLogin,
    logout: handleLogout,
    refreshUser,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
