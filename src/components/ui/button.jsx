import { cva } from "class-variance-authority";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap text-[12px] font-bold tracking-[-0.01em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        default: "bg-ink text-paper hover:bg-ink/88",
        accent: "bg-accent text-accent-ink hover:bg-accent-strong",
        outline: "border border-line-strong bg-paper hover:bg-muted-surface",
        ghost: "hover:bg-muted-surface",
        quiet: "text-ink-muted hover:text-ink"
      },
      size: {
        default: "h-10 px-4",
        sm: "h-8 px-3 text-[11px]",
        icon: "size-10 p-0"
      }
    },
    defaultVariants: { variant: "default", size: "default" }
  }
);

export function Button({ className, variant, size, ...props }) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
