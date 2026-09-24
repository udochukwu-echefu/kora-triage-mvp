import { Activity, BarChart3, ClipboardCheck, Inbox, Settings, Users, X } from "lucide-react";
import { cn } from "../lib/utils";
import { initialsOf } from "../lib/tickets";
import { Tooltip, TooltipProvider } from "../components/ui/tooltip";

export const navItems = [
  { id: "queue", label: "Queue", icon: Inbox },
  { id: "insights", label: "Insights", icon: BarChart3 },
  { id: "proof", label: "Historical evaluation", icon: ClipboardCheck },
  { id: "audit", label: "Audit trail", icon: Activity },
  { id: "team", label: "Team coverage", icon: Users },
  { id: "settings", label: "Automation", icon: Settings }
];

export default function Rail({ activeView, onView, open, onClose, user }) {
  const displayName = user?.display_name || "Signed in";
  const role = (user?.role || "").replaceAll("_", " ");
  return (
    <aside className={cn("fixed inset-y-3 left-3 z-40 flex w-[244px] max-w-[calc(100vw-24px)] flex-col rounded-[20px] border border-line bg-paper px-3 py-4 text-ink shadow-float transition-transform lg:translate-x-0", open ? "translate-x-0" : "-translate-x-[calc(100%+24px)]")} aria-label="Main navigation">
      <button onClick={onClose} className="absolute right-2 top-2 grid size-11 place-items-center rounded-[11px] text-ink/60 hover:bg-paper/45 hover:text-ink lg:hidden" aria-label="Close navigation"><X className="size-4" /></button>
      <div className="flex h-12 items-center gap-3 px-2" aria-label="Kora"><span className="grid size-9 place-items-center rounded-[12px] kora-mark text-xs font-semibold">KR</span><span><strong className="block text-[15px] font-semibold tracking-[-0.02em]">Kora</strong><small className="mt-1 block text-xs font-medium text-ink/55">Support operations</small></span></div>
      <TooltipProvider>
        <nav className="mt-8 flex flex-1 flex-col gap-1.5">
          {navItems.map(({ id, label, icon: Icon }) => (
            <Tooltip key={id} label={label}>
              <button onClick={() => { onView(id); onClose(); }} aria-label={label} aria-current={activeView === id ? "page" : undefined} className={cn("grid h-11 w-full grid-cols-[18px_minmax(0,1fr)] items-center gap-3 rounded-[12px] border px-3 text-left text-sm font-semibold transition-[background-color,color,border-color,transform]", activeView === id ? "border-line bg-muted-surface text-ink" : "border-transparent text-ink/68 hover:translate-x-0.5 hover:bg-canvas hover:text-ink")}>
                <Icon className="size-[16px] justify-self-center" /><span className="whitespace-nowrap leading-none">{label}</span>
              </button>
            </Tooltip>
          ))}
        </nav>
        <div className="border-t border-line pt-3">
          <button onClick={() => onView("settings")} className="flex min-h-16 w-full items-center gap-3 rounded-[12px] px-2 text-left hover:bg-canvas"><span className="grid size-10 place-items-center rounded-full bg-muted-surface text-xs font-extrabold text-ink">{initialsOf(displayName)}</span><span><strong className="block text-[15px] font-extrabold">{displayName}</strong><small className="mt-1 block capitalize text-xs font-semibold text-ink/60">{role}</small></span></button>
        </div>
      </TooltipProvider>
    </aside>
  );
}
