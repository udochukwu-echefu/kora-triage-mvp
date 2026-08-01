import { cva } from "class-variance-authority";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[7px] text-[12px] font-bold tracking-[-0.01em] transition-[background-color,border-color,color,transform,box-shadow] duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        default: "bg-ink text-paper shadow-[0_2px_0_var(--color-accent-ink)] hover:-translate-y-px hover:bg-shell hover:shadow-[0_4px_0_var(--color-accent-ink)] active:translate-y-0 active:shadow-none",
        accent: "border border-accent-strong bg-accent text-accent-ink shadow-[0_2px_0_var(--color-accent-ink)] hover:-translate-y-px hover:bg-accent-strong hover:shadow-[0_4px_0_var(--color-accent-ink)] active:translate-y-0 active:shadow-none",
        outline: "border border-line-strong bg-paper hover:-translate-y-px hover:border-ink hover:bg-paper hover:shadow-float active:translate-y-0 active:shadow-none",
        ghost: "hover:bg-muted-surface",
        quiet: "text-ink-muted hover:text-ink"
      },
      size: {
        default: "h-11 px-4",
        sm: "h-9 px-3 text-[11px]",
        icon: "size-11 p-0"
      }
    },
    defaultVariants: { variant: "default", size: "default" }
  }
);

export function Button({ className, variant, size, ...props }) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
