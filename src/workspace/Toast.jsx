import { useEffect } from "react";
import { CheckCircle2, CircleAlert, X } from "lucide-react";
import { cn } from "../lib/utils";

// Errors stay longer, use an alert icon, and are announced assertively.
export default function Toast({ toast, onDismiss }) {
  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(onDismiss, toast.tone === "error" ? 8000 : 3000);
    return () => clearTimeout(timer);
  }, [toast, onDismiss]);
  const isError = toast?.tone === "error";
  const Icon = isError ? CircleAlert : CheckCircle2;
  return (
    <div
      role={isError ? "alert" : "status"}
      aria-live={isError ? "assertive" : "polite"}
      className={cn(
        "fixed bottom-5 right-3 z-50 flex max-w-[calc(100vw-24px)] items-center gap-2 rounded-[14px] border bg-paper px-4 py-3 text-[13px] font-bold text-ink shadow-precision transition-all sm:right-5",
        isError ? "border-accent-strong" : "border-line-strong",
        toast ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-3 opacity-0"
      )}
    >
      {toast && <Icon className="size-4 shrink-0 text-accent-strong" />}
      <span>{toast?.message}</span>
      {toast && <button type="button" onClick={onDismiss} className="ml-1 grid size-6 place-items-center rounded-full text-ink-muted hover:bg-muted-surface hover:text-ink" aria-label="Dismiss message"><X className="size-3.5" /></button>}
    </div>
  );
}
