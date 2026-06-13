import { cn } from '@/lib/utils'
import { HTMLAttributes, forwardRef } from 'react'

export interface BadgeProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'secondary' | 'destructive' | 'outline'
}

const Badge = forwardRef<HTMLDivElement, BadgeProps>(
  ({ className, variant = 'default', ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors',
        {
          'bg-indigo-100 text-indigo-900 dark:bg-indigo-900 dark:text-indigo-100':
            variant === 'default',
          'bg-slate-100 text-slate-900 dark:bg-slate-700 dark:text-slate-100':
            variant === 'secondary',
          'bg-red-100 text-red-900 dark:bg-red-900 dark:text-red-100':
            variant === 'destructive',
          'border border-slate-200 dark:border-slate-700': variant === 'outline',
        },
        className
      )}
      {...props}
    />
  )
)
Badge.displayName = 'Badge'

export { Badge }