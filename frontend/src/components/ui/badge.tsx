import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded px-2 py-0.5 text-[10px] font-medium tracking-wide uppercase transition-colors",
  {
    variants: {
      variant: {
        default:
          "bg-steel-tint text-steel border border-steel-border",
        secondary:
          "bg-slate-100 text-slate-700 border border-slate-200",
        destructive:
          "bg-status-crimsonBg text-status-crimson border border-status-crimsonBorder",
        success:
          "bg-status-emeraldBg text-status-emerald border border-status-emeraldBorder",
        warning:
          "bg-status-amberBg text-status-amber border border-status-amberBorder",
        outline: "text-slate-700 border border-slate-300",
        enhanced:
          "bg-red-600 text-white font-bold border border-red-700 tracking-wider shadow-sm",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
