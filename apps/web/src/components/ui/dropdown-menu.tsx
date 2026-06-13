'use client'

import { cn } from '@/lib/utils'
import {
  ButtonHTMLAttributes,
  HTMLAttributes,
  ReactElement,
  cloneElement,
  createContext,
  forwardRef,
  isValidElement,
  useContext,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'

export interface DropdownMenuProps extends HTMLAttributes<HTMLDivElement> {
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

interface DropdownMenuContextValue {
  open: boolean
  setOpen: (open: boolean) => void
}

const DropdownMenuContext = createContext<DropdownMenuContextValue | null>(null)

const DropdownMenu = forwardRef<HTMLDivElement, DropdownMenuProps>(
  ({ className, children, open: controlledOpen, onOpenChange, ...props }, ref) => {
    const [internalOpen, setInternalOpen] = useState(false)
    const open = controlledOpen ?? internalOpen
    const setOpen = useCallback((nextOpen: boolean) => {
      if (controlledOpen === undefined) {
        setInternalOpen(nextOpen)
      }
      onOpenChange?.(nextOpen)
    }, [controlledOpen, onOpenChange])
    const rootRef = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
      const handlePointerDown = (event: MouseEvent) => {
        if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
          setOpen(false)
        }
      }

      const handleKeyDown = (event: KeyboardEvent) => {
        if (event.key === 'Escape') {
          setOpen(false)
        }
      }

      document.addEventListener('mousedown', handlePointerDown)
      document.addEventListener('keydown', handleKeyDown)

      return () => {
        document.removeEventListener('mousedown', handlePointerDown)
        document.removeEventListener('keydown', handleKeyDown)
      }
    }, [setOpen])

    return (
      <DropdownMenuContext.Provider value={{ open, setOpen }}>
        <div
          ref={(node) => {
            rootRef.current = node
            if (typeof ref === 'function') ref(node)
            else if (ref) ref.current = node
          }}
          className={cn('relative inline-block', className)}
          {...props}
        >
          {children}
        </div>
      </DropdownMenuContext.Provider>
    )
  }
)
DropdownMenu.displayName = 'DropdownMenu'

const DropdownMenuTrigger = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { asChild?: boolean }>(
  ({ className, asChild, children, ...props }, ref) => {
    const context = useContext(DropdownMenuContext)
    const toggleOpen = () => context?.setOpen(!context.open)

    if (asChild && isValidElement(children)) {
      const child = children as ReactElement<any>

      return cloneElement(child, {
        ref,
        'aria-expanded': context?.open,
        'aria-haspopup': 'menu',
        className: cn(child.props.className, className),
        onClick: (event: React.MouseEvent<HTMLElement>) => {
          child.props.onClick?.(event)
          props.onClick?.(event as React.MouseEvent<HTMLButtonElement>)
          if (!event.defaultPrevented) {
            toggleOpen()
          }
        },
      })
    }

    return (
      <button
        ref={ref}
        className={cn('', className)}
        aria-expanded={context?.open}
        aria-haspopup="menu"
        {...props}
        onClick={(event) => {
          props.onClick?.(event)
          if (!event.defaultPrevented) {
            toggleOpen()
          }
        }}
      >
        {children}
      </button>
    )
  }
)
DropdownMenuTrigger.displayName = 'DropdownMenuTrigger'

const DropdownMenuContent = forwardRef<HTMLDivElement, DropdownMenuProps & { align?: 'start' | 'end' }>(
  ({ className, align = 'start', ...props }, ref) => {
    const context = useContext(DropdownMenuContext)
    if (!context?.open) return null

    return (
      <div
        ref={ref}
        role="menu"
        className={cn(
          'absolute top-full z-50 mt-2 min-w-[8rem] overflow-hidden rounded-md border border-slate-200 bg-white p-1 text-slate-900 shadow-md dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100',
          align === 'end' && 'right-0',
          align === 'start' && 'left-0',
          className
        )}
        {...props}
      />
    )
  }
)
DropdownMenuContent.displayName = 'DropdownMenuContent'

const DropdownMenuItem = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement> & {
  inset?: boolean
  disabled?: boolean
  asChild?: boolean
}>(
  ({ className, inset, disabled, asChild, children, ...props }, ref) => {
    const context = useContext(DropdownMenuContext)
    const itemClassName = cn(
      'relative flex cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none transition-colors hover:bg-slate-100 dark:hover:bg-slate-700',
      inset && 'pl-8',
      disabled && 'opacity-50 pointer-events-none',
      className
    )

    if (asChild && isValidElement(children)) {
      const child = children as ReactElement<any>

      return cloneElement(child, {
        ref,
        role: 'menuitem',
        className: cn(itemClassName, child.props.className),
        onClick: (event: React.MouseEvent<HTMLElement>) => {
          if (disabled) {
            event.preventDefault()
            return
          }
          child.props.onClick?.(event)
          props.onClick?.(event as React.MouseEvent<HTMLDivElement>)
          if (!event.defaultPrevented) {
            context?.setOpen(false)
          }
        },
      })
    }

    return (
      <div
        ref={ref}
        role="menuitem"
        tabIndex={disabled ? -1 : 0}
        className={itemClassName}
        {...props}
        onClick={(event) => {
          if (disabled) return
          props.onClick?.(event)
          if (!event.defaultPrevented) {
            context?.setOpen(false)
          }
        }}
      >
        {children}
      </div>
    )
  }
)
DropdownMenuItem.displayName = 'DropdownMenuItem'

const DropdownMenuLabel = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement> & {
  inset?: boolean
}>(
  ({ className, inset, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'px-2 py-1.5 text-sm font-semibold',
        inset && 'pl-8',
        className
      )}
      {...props}
    />
  )
)
DropdownMenuLabel.displayName = 'DropdownMenuLabel'

const DropdownMenuSeparator = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('-mx-1 my-1 h-px bg-slate-200 dark:bg-slate-700', className)}
      {...props}
    />
  )
)
DropdownMenuSeparator.displayName = 'DropdownMenuSeparator'

export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
}
