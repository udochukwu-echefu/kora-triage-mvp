import { cn } from "../../lib/utils";

export function Card({ className, ...props }) {
  return <section className={cn("border border-line bg-paper", className)} {...props} />;
}

export function CardHeader({ className, ...props }) {
  return <header className={cn("flex items-start justify-between gap-4 border-b border-line px-5 py-4", className)} {...props} />;
}

export function CardContent({ className, ...props }) {
  return <div className={cn("p-5", className)} {...props} />;
}
