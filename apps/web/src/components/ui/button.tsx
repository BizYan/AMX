import { cn } from '@/lib/utils'
import { ButtonHTMLAttributes, ReactElement, cloneElement, forwardRef, isValidElement } from 'react'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link'
  size?: 'default' | 'sm' | 'lg' | 'icon'
  asChild?: boolean
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', size = 'default', asChild, children, ...props }, ref) => {
    const buttonClassName = cn(
      'inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-50',
      {
        'bg-slate-900 text-white hover:bg-slate-800 dark:bg-slate-50 dark:text-slate-900 dark:hover:bg-slate-100':
          variant === 'default',
        'bg-destructive text-destructive-foreground hover:bg-destructive/90':
          variant === 'destructive',
        'border border-slate-200 bg-white text-slate-900 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700':
          variant === 'outline',
        'bg-secondary text-secondary-foreground hover:bg-secondary/80':
          variant === 'secondary',
        'text-slate-900 hover:bg-slate-100 dark:text-slate-100 dark:hover:bg-slate-800': variant === 'ghost',
        'text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400':
          variant === 'link',
      },
      {
        'h-10 px-4 py-2': size === 'default',
        'h-9 rounded-md px-3': size === 'sm',
        'h-11 rounded-md px-8': size === 'lg',
        'h-10 w-10': size === 'icon',
      },
      className
    )

    if (asChild && isValidElement(children)) {
      const child = children as ReactElement<any>

      return cloneElement(child, {
        ref,
        className: cn(buttonClassName, child.props.className),
        ...props,
      })
    }

    return (
      <button
        className={buttonClassName}
        ref={ref}
        {...props}
      >
        {children}
      </button>
    )
  }
)
Button.displayName = 'Button'

export { Button }
