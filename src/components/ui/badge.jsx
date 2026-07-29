import { cva } from "class-variance-authority";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex h-6 items-center gap-1.5 whitespace-nowrap border px-2.5 text-[10px] font-bold tracking-[-0.01em]",
  {
    variants: {
      variant: {
        neutral: "border-line bg-muted-surface text-ink-muted",
        accent: "border-accent bg-accent text-accent-ink",
        strong: "border-ink bg-ink text-paper",
        outline: "border-line-strong bg-paper text-ink"
      },
      shape: { pill: "rounded-full", square: "rounded-[3px]" }
    },
    defaultVariants: { variant: "neutral", shape: "pill" }
  }
);

export function Badge({ className, variant, shape, ...props }) {
  return <span className={cn(badgeVariants({ variant, shape }), className)} {...props} />;
}
