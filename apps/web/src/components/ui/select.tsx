'use client'

import { cn } from '@/lib/utils'
import { OptionHTMLAttributes, SelectHTMLAttributes, forwardRef } from 'react'

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  value?: string
  onValueChange?: (value: string) => void
}

const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, children, onChange, onValueChange, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        'flex h-10 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:ring-offset-slate-900',
        className
      )}
      {...props}
      onChange={(event) => {
        onChange?.(event)
        onValueChange?.(event.target.value)
      }}
    >
      {children}
    </select>
  )
)
Select.displayName = 'Select'

export interface SelectOptionProps extends OptionHTMLAttributes<HTMLOptionElement> {
  value?: string
}

const SelectOption = forwardRef<HTMLOptionElement, SelectOptionProps>(
  ({ className, value, ...props }, ref) => (
    <option ref={ref} className={cn('', className)} value={value} {...props} />
  )
)
SelectOption.displayName = 'SelectOption'

export { Select, SelectOption }
