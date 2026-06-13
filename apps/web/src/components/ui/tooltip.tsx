'use client'

import { cn } from '@/lib/utils'
import { HTMLAttributes, forwardRef, createContext, useContext, useState, ReactNode } from 'react'

interface TooltipContextType {
  open: boolean
  setOpen: (open: boolean) => void
}

const TooltipContext = createContext<TooltipContextType | undefined>(undefined)

export interface TooltipProps extends HTMLAttributes<HTMLDivElement> {
  delayDuration?: number
}

const Tooltip = forwardRef<HTMLDivElement, TooltipProps>(
  ({ className, delayDuration = 300, children, ...props }, ref) => {
    const [open, setOpen] = useState(false)

    return (
      <TooltipContext.Provider value={{ open, setOpen }}>
        <div ref={ref} className={cn('relative inline-block', className)} {...props}>
          {children}
        </div>
      </TooltipContext.Provider>
    )
  }
)
Tooltip.displayName = 'Tooltip'

export interface TooltipTriggerProps extends HTMLAttributes<HTMLDivElement> {
  asChild?: boolean
}

const TooltipTrigger = forwardRef<HTMLDivElement, TooltipTriggerProps>(
  ({ className, children, ...props }, ref) => {
    const context = useContext(TooltipContext)

    return (
      <div
        ref={ref}
        className={cn('', className)}
        onMouseEnter={() => context?.setOpen(true)}
        onMouseLeave={() => context?.setOpen(false)}
        {...props}
      >
        {children}
      </div>
    )
  }
)
TooltipTrigger.displayName = 'TooltipTrigger'

export interface TooltipContentProps extends HTMLAttributes<HTMLDivElement> {
  side?: 'top' | 'right' | 'bottom' | 'left'
}

const TooltipContent = forwardRef<HTMLDivElement, TooltipContentProps>(
  ({ className, side = 'top', ...props }, ref) => {
    const context = useContext(TooltipContext)
    if (!context?.open) return null

    return (
      <div
        ref={ref}
        className={cn(
          'z-50 overflow-hidden rounded-md bg-slate-900 px-3 py-1.5 text-xs text-white dark:bg-slate-50 dark:text-slate-900',
          {
            'left-1/2 -translate-x-1/2': side === 'top' || side === 'bottom',
            'top-1/2 -translate-y-1/2': side === 'left' || side === 'right',
          },
          className
        )}
        {...props}
      />
    )
  }
)
TooltipContent.displayName = 'TooltipContent'

export { Tooltip, TooltipTrigger, TooltipContent }