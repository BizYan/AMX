'use client'

import { cn } from '@/lib/utils'
import { HTMLAttributes, forwardRef } from 'react'

export interface AvatarProps extends HTMLAttributes<HTMLDivElement> {
  size?: 'sm' | 'md' | 'lg'
}

const Avatar = forwardRef<HTMLDivElement, AvatarProps>(
  ({ className, size = 'md', ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'relative flex shrink-0 overflow-hidden rounded-full',
        {
          'h-8 w-8': size === 'sm',
          'h-10 w-10': size === 'md',
          'h-12 w-12': size === 'lg',
        },
        className
      )}
      {...props}
    />
  )
)
Avatar.displayName = 'Avatar'

const AvatarFallback = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'flex h-full w-full items-center justify-center rounded-full bg-slate-100 dark:bg-slate-700',
        className
      )}
      {...props}
    />
  )
)
AvatarFallback.displayName = 'AvatarFallback'

export { Avatar, AvatarFallback }