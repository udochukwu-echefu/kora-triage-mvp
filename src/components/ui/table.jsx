import { cn } from "../../lib/utils";

export function Table({ className, ...props }) { return <table className={cn("w-full border-collapse text-left", className)} {...props} />; }
export function TableHeader({ className, ...props }) { return <thead className={cn("border-b border-line-strong bg-muted-surface", className)} {...props} />; }
export function TableBody({ className, ...props }) { return <tbody className={className} {...props} />; }
export function TableRow({ className, ...props }) { return <tr className={cn("border-b border-line transition-colors hover:bg-muted-surface/70", className)} {...props} />; }
export function TableHead({ className, ...props }) { return <th className={cn("h-11 px-4 text-[9px] font-extrabold uppercase tracking-[0.1em] text-ink-muted", className)} {...props} />; }
export function TableCell({ className, ...props }) { return <td className={cn("px-4 py-4 align-top text-[11px]", className)} {...props} />; }
