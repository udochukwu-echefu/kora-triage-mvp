import { forwardRef } from "react";
import { cn } from "../../lib/utils";

export const Input = forwardRef(function Input({ className, type = "text", ...props }, ref) {
  return (
    <input
      ref={ref}
      type={type}
      className={cn(
        "flex h-11 w-full rounded-[7px] border border-line-strong bg-paper px-3 text-[14px] text-ink shadow-[0_1px_0_oklch(18%_0.02_115_/_0.04)] outline-none transition-[border-color,box-shadow] placeholder:text-ink-faint hover:border-ink/55 focus-visible:border-ink focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:bg-muted-surface disabled:opacity-60",
        className
      )}
      {...props}
    />
  );
});
