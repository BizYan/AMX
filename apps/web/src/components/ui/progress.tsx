import { cn } from '@/lib/utils'
import { HTMLAttributes, forwardRef } from 'react'

export interface ProgressProps extends HTMLAttributes<HTMLDivElement> {
  value?: number
  max?: number
}

const Progress = forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value = 0, max = 100, ...props }, ref) => {
    const percentage = Math.min(100, Math.max(0, (value / max) * 100))

    return (
      <div
        ref={ref}
        className={cn(
          'relative h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800',
          className
        )}
        {...props}
      >
        <div
          className="h-full bg-indigo-500 transition-all duration-300"
          style={{ width: `${percentage}%` }}
        />
      </div>
    )
  }
)
Progress.displayName = 'Progress'

export { Progress }