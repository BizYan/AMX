import { cn } from '@/lib/utils'
import { LabelHTMLAttributes, forwardRef } from 'react'

export interface LabelProps extends LabelHTMLAttributes<HTMLLabelElement> {}

const Label = forwardRef<HTMLLabelElement, LabelProps>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn(
        'text-sm font-medium leading-none text-slate-900 peer-disabled:cursor-not-allowed peer-disabled:opacity-70 dark:text-slate-100',
        className
      )}
      {...props}
    />
  )
)
Label.displayName = 'Label'

export { Label }
