import { cn } from "../../lib/utils";

export function Skeleton({ className, ...props }) {
  return <div className={cn("animate-pulse bg-line/70", className)} {...props} />;
}
