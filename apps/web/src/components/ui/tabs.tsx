'use client'

import { cn } from '@/lib/utils'
import { HTMLAttributes, forwardRef, createContext, useContext, useState, ReactNode } from 'react'

interface TabsContextType {
  value: string
  onValueChange: (value: string) => void
}

const TabsContext = createContext<TabsContextType | undefined>(undefined)

export interface TabsProps extends HTMLAttributes<HTMLDivElement> {
  value?: string
  defaultValue?: string
  onValueChange?: (value: string) => void
}

const Tabs = forwardRef<HTMLDivElement, TabsProps>(
  ({ className, value: controlledValue, defaultValue = '', onValueChange, children, ...props }, ref) => {
    const [internalValue, setInternalValue] = useState(defaultValue)
    const value = controlledValue ?? internalValue

    const handleValueChange = (newValue: string) => {
      setInternalValue(newValue)
      onValueChange?.(newValue)
    }

    return (
      <TabsContext.Provider value={{ value, onValueChange: handleValueChange }}>
        <div ref={ref} className={cn('', className)} {...props}>
          {children}
        </div>
      </TabsContext.Provider>
    )
  }
)
Tabs.displayName = 'Tabs'

export interface TabsListProps extends HTMLAttributes<HTMLDivElement> {}

const TabsList = forwardRef<HTMLDivElement, TabsListProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      role="tablist"
      className={cn(
        'inline-flex h-10 items-center justify-center rounded-md bg-slate-100 p-1 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
        className
      )}
      {...props}
    />
  )
)
TabsList.displayName = 'TabsList'

export interface TabsTriggerProps extends HTMLAttributes<HTMLButtonElement> {
  value: string
}

const TabsTrigger = forwardRef<HTMLButtonElement, TabsTriggerProps>(
  ({ className, value: triggerValue, ...props }, ref) => {
    const context = useContext(TabsContext)
    const isActive = context?.value === triggerValue

    return (
      <button
        ref={ref}
        role="tab"
        aria-selected={isActive}
        className={cn(
          'inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium ring-offset-white transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50',
          isActive
            ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-900 dark:text-white'
            : 'hover:bg-white/50 hover:text-slate-900 dark:hover:bg-slate-700/50',
          className
        )}
        onClick={() => context?.onValueChange(triggerValue)}
        {...props}
      />
    )
  }
)
TabsTrigger.displayName = 'TabsTrigger'

export interface TabsContentProps extends HTMLAttributes<HTMLDivElement> {
  value: string
}

const TabsContent = forwardRef<HTMLDivElement, TabsContentProps>(
  ({ className, value: contentValue, ...props }, ref) => {
    const context = useContext(TabsContext)
    if (context?.value !== contentValue) return null

    return (
      <div
        ref={ref}
        role="tabpanel"
        className={cn('mt-2 ring-offset-white focus-visible:outline-none focus-visible:ring-2', className)}
        {...props}
      />
    )
  }
)
TabsContent.displayName = 'TabsContent'

export { Tabs, TabsList, TabsTrigger, TabsContent }
