import { cn } from "../../lib/utils";

export function Card({ className, ...props }) {
  return <section className={cn("rounded-[10px] border border-line bg-paper shadow-[0_1px_0_oklch(18%_0.02_115_/_0.04)]", className)} {...props} />;
}

export function CardHeader({ className, ...props }) {
  return <header className={cn("flex items-start justify-between gap-4 border-b border-line px-5 py-4", className)} {...props} />;
}

export function CardContent({ className, ...props }) {
  return <div className={cn("p-5", className)} {...props} />;
}
