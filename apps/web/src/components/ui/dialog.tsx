'use client'

import { cn } from '@/lib/utils'
import {
  cloneElement,
  createContext,
  forwardRef,
  HTMLAttributes,
  isValidElement,
  useContext,
  useEffect,
} from 'react'

export interface DialogProps extends HTMLAttributes<HTMLDivElement> {
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

interface DialogContextValue {
  open: boolean
  onOpenChange?: (open: boolean) => void
}

const DialogContext = createContext<DialogContextValue | null>(null)

const Dialog = forwardRef<HTMLDivElement, DialogProps>(
  ({ open = false, onOpenChange, children }, ref) => {
    return (
      <DialogContext.Provider value={{ open, onOpenChange }}>
        <div ref={ref}>{children}</div>
      </DialogContext.Provider>
    )
  }
)
Dialog.displayName = 'Dialog'

const DialogContent = forwardRef<HTMLDivElement, DialogProps>(
  ({ className, onClick, ...props }, ref) => {
    const context = useContext(DialogContext)

    useEffect(() => {
      if (!context?.open) return

      const handleKeyDown = (event: KeyboardEvent) => {
        if (event.key === 'Escape') {
          context.onOpenChange?.(false)
        }
      }

      document.addEventListener('keydown', handleKeyDown)
      return () => document.removeEventListener('keydown', handleKeyDown)
    }, [context])

    if (!context?.open) return null

    return (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"
        onClick={() => context.onOpenChange?.(false)}
      >
        <div
          ref={ref}
          role="dialog"
          aria-modal="true"
          className={cn(
            'relative w-full max-w-lg rounded-lg border border-slate-200 bg-white p-6 text-slate-900 shadow-lg dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100',
            className
          )}
          onClick={(event) => {
            event.stopPropagation()
            onClick?.(event)
          }}
          {...props}
        />
      </div>
    )
  }
)
DialogContent.displayName = 'DialogContent'

const DialogHeader = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('flex flex-col space-y-1.5 text-center sm:text-left', className)}
      {...props}
    />
  )
)
DialogHeader.displayName = 'DialogHeader'

const DialogTitle = forwardRef<HTMLHeadingElement, HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h2
      ref={ref}
      className={cn('text-lg font-semibold leading-none tracking-tight text-slate-900 dark:text-white', className)}
      {...props}
    />
  )
)
DialogTitle.displayName = 'DialogTitle'

const DialogDescription = forwardRef<HTMLParagraphElement, HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <p
      ref={ref}
      className={cn('text-sm text-slate-500 dark:text-slate-400', className)}
      {...props}
    />
  )
)
DialogDescription.displayName = 'DialogDescription'

const DialogFooter = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2', className)}
      {...props}
    />
  )
)
DialogFooter.displayName = 'DialogFooter'

const DialogTrigger = forwardRef<HTMLButtonElement, HTMLAttributes<HTMLButtonElement> & { asChild?: boolean }>(
  ({ className, asChild, children, ...props }, ref) => {
    const context = useContext(DialogContext)
    const handleClick = () => context?.onOpenChange?.(true)

    if (asChild && isValidElement(children)) {
      return cloneElement(children, {
        ...props,
        className: cn((children.props as { className?: string }).className, className),
        onClick: (event: React.MouseEvent<HTMLButtonElement>) => {
          ;(children.props as { onClick?: (event: React.MouseEvent<HTMLButtonElement>) => void }).onClick?.(event)
          handleClick()
        },
      })
    }

    return (
      <button ref={ref} className={cn('', className)} onClick={handleClick} {...props}>
        {children}
      </button>
    )
  }
)
DialogTrigger.displayName = 'DialogTrigger'

export { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger }
