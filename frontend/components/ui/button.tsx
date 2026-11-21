import type { ComponentProps } from 'react';
import { cn } from '@/lib/utils';

export function buttonClass(variant: 'primary' | 'outline' | 'ghost' = 'primary', className?: string) {
  return cn('button', `button-${variant}`, className);
}

export function Button({ className, variant, type = 'button', ...props }: ComponentProps<'button'> & {
  variant?: 'primary' | 'outline' | 'ghost';
}) {
  return <button type={type} className={buttonClass(variant, className)} {...props} />;
}
