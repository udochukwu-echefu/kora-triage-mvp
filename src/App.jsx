import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, ArrowRight, BarChart3, Bell, Bot, Check,
  CheckCircle2, ChevronDown, CircleAlert, CircleUserRound, Clock3, Database, Download, Filter,
  Inbox, LoaderCircle, LogOut, Menu, MoreHorizontal, Route, Save, Search, Settings, ShieldAlert,
  Sparkles, Square, SquareCheckBig, Timer, UserRoundCheck, Users, X, Zap
} from "lucide-react";
import { customers, messages } from "./data";
import { cn } from "./lib/utils";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card } from "./components/ui/card";
import { Skeleton } from "./components/ui/skeleton";
import { Tooltip, TooltipProvider } from "./components/ui/tooltip";
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger
} from "./components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./components/ui/table";
import {
  getAutomationSettings, getBackendAudit, getBackendHealth, getCases, getCustomerMemory,
  recordCaseAction, recordCaseRoute, runGroqTriage, updateAutomationSettings
} from "./api";
import LandingPage from "./components/LandingPage";

const InsightsView = lazy(() => import("./components/InsightsView"));

const seedTickets = messages.map((message) => ({
  ...message,
  customer: customers[message.customerId],
  intent: "Awaiting triage",
  urgency: "pending",
  sentiment: "pending",
  route: "Unassigned",
  confidence: 0,
  entities: {},
  memoryUsed: false,
  escalated: false,
  escalationReason: null,
  evidence: [],
  response: "",
  status: "Awaiting live AI",
  source: "pending",
  model: null,
  processingMs: null,
  estimatedMinutesSaved: null
}));

const navItems = [
  { id: "queue", label: "Queue", icon: Inbox },
  { id: "insights", label: "Insights", icon: BarChart3 },
  { id: "audit", label: "Audit trail", icon: Activity },
  { id: "team", label: "Team", icon: Users },
  { id: "settings", label: "Settings", icon: Settings }
];

const urgencyOrder = { critical: 0, high: 1, medium: 2, low: 3, pending: 4 };
const intentShort = {
  "Transfer pending": "Transfer", "Payment failed": "Payment", "Duplicate debit": "Card debit",
  "Fraud report": "Fraud", "Delivery delayed": "Delivery", "Delivery missing": "Delivery",
  "Delivery change": "Delivery", "Account access": "Account", "Account verification": "KYC",
  "Refund pending": "Refund"
};
const isProcessed = (ticket) => ticket.source && ticket.source !== "pending";
const teamOptions = ["Transfers", "Fraud", "Logistics", "Billing", "Account Support", "Compliance", "General Support"];

function policyState(ticket, automation) {
  if (!isProcessed(ticket)) return "pending";
  if (ticket.escalated || Math.round(ticket.confidence * 100) < automation.mandatory_review_threshold) return "mandatory";
  if (automation.enabled && Math.round(ticket.confidence * 100) >= automation.auto_approve_threshold) return "auto";
  return "normal";
}

function slaState(ticket) {
  const target = { critical: 24, high: 48, medium: 120, low: 240 }[ticket.urgency] || 120;
  const remaining = target - ticket.minutesAgo;
  if (["Approved", "Auto-approved"].includes(ticket.status)) return null;
  if (remaining <= 0) return { label: `${Math.abs(remaining)}m overdue`, overdue: true };
  if (remaining <= Math.max(12, target * .2)) return { label: `${remaining}m to SLA`, overdue: false };
  return null;
}

function lowRisk(ticket) {
  return isProcessed(ticket)
    && !ticket.escalated
    && ["low", "medium"].includes(ticket.urgency)
    && ticket.route !== "Fraud"
    && ticket.confidence >= .8;
}

function formatRelative(minutes) {
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function UrgencyBadge({ urgency }) {
  const variants = { critical: "strong", high: "accent", medium: "outline", low: "neutral" };
  return (
    <Badge variant={variants[urgency] || "neutral"} shape={urgency === "critical" ? "square" : "pill"}>
      <span className={cn("size-1.5", urgency === "critical" ? "rotate-45 bg-accent" : "rounded-full bg-current")} />
      {urgency}
    </Badge>
  );
}

function Rail({ activeView, onView, open, onClose }) {
  return (
    <aside className={cn("fixed inset-y-0 left-0 z-40 flex w-[214px] flex-col border-r border-line bg-paper px-3 py-5 transition-transform lg:translate-x-0", open ? "translate-x-0 shadow-precision" : "-translate-x-full")} aria-label="Main navigation">
      <button onClick={onClose} className="absolute right-2 top-2 p-1 lg:hidden" aria-label="Close navigation"><X className="size-4" /></button>
      <div className="flex h-10 items-center gap-3 px-2" aria-label="Kora"><span className="grid size-9 place-items-center bg-ink text-xs font-extrabold text-paper">KR</span><span><strong className="block text-[13px] font-extrabold tracking-[-0.03em]">Kora</strong><small className="block text-[8px] font-bold uppercase tracking-[0.1em] text-ink-faint">Support operations</small></span></div>
      <TooltipProvider>
        <nav className="mt-10 flex flex-1 flex-col gap-1">
          {navItems.map(({ id, label, icon: Icon }) => (
            <Tooltip key={id} label={label}>
              <button onClick={() => { onView(id); onClose(); }} aria-label={label} aria-current={activeView === id ? "page" : undefined} className={cn("flex h-10 w-full items-center gap-3 border px-3 text-[11px] font-bold text-ink-muted transition-colors", activeView === id ? "border-ink bg-ink text-paper" : "border-transparent hover:border-line hover:bg-muted-surface hover:text-ink")}>
                <Icon className="size-[16px]" /><span>{label}</span>
              </button>
            </Tooltip>
          ))}
        </nav>
        <div className="border-t border-line pt-3">
          <button onClick={() => onView("settings")} className="flex h-12 w-full items-center gap-3 px-2 text-left hover:bg-muted-surface"><span className="grid size-8 place-items-center rounded-full bg-accent text-[9px] font-extrabold text-accent-ink">AO</span><span><strong className="block text-[10px] font-extrabold">Ada Okafor</strong><small className="text-[8px] font-semibold text-ink-faint">Support manager</small></span></button>
        </div>
      </TooltipProvider>
    </aside>
  );
}

function Header({ activeView, onMenu, backend, tickets, onOpenTicket, onView, onLogout }) {
  const [readNotificationIds, setReadNotificationIds] = useState([]);
  const titles = { queue: ["Operations", "Triage queue"], insights: ["Performance", "Support insights"], audit: ["Governance", "Decision audit"], team: ["Workforce", "Support team"], settings: ["Controls", "Automation settings"] };
  const engineLabel = backend.state === "checking"
    ? "Checking API"
    : backend.configured
      ? "Groq ready"
      : backend.state === "online" ? "Key required" : "API offline";
  const notifications = [...tickets]
    .sort((a, b) => Number(b.escalated) - Number(a.escalated) || urgencyOrder[a.urgency] - urgencyOrder[b.urgency] || a.minutesAgo - b.minutesAgo)
    .slice(0, 4)
    .map((ticket) => ({
      ...ticket,
      notificationTitle: ticket.escalated ? "Human review required" : isProcessed(ticket) ? `${intentShort[ticket.intent] || ticket.intent} triaged` : "Live triage pending"
    }));
  const unreadCount = notifications.filter((notification) => !readNotificationIds.includes(notification.id)).length;
  return (
    <header className="flex h-[76px] items-center justify-between border-b border-line bg-paper px-4 sm:px-7 lg:px-9">
      <div className="flex items-center gap-3">
        <Button variant="outline" size="icon" className="lg:hidden" onClick={onMenu} aria-label="Open navigation"><Menu className="size-4" /></Button>
        <div><p className="section-label">{titles[activeView][0]}</p><h1 className="text-[19px] font-extrabold tracking-[-0.04em]">{titles[activeView][1]}</h1></div>
      </div>
      <div className="flex items-center gap-2">
        <div className="hidden items-center gap-2 border border-line px-3 py-2 text-[10px] font-bold text-ink-muted sm:flex"><span className={cn("size-2 rounded-full", backend.configured ? "bg-accent" : "bg-line-strong")} />{engineLabel}</div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="icon" aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ""}`} className="relative">
              <Bell className="size-4" />
              {unreadCount > 0 && <span className="absolute right-1.5 top-1.5 grid size-4 place-items-center rounded-full bg-accent text-[8px] font-extrabold text-accent-ink">{unreadCount}</span>}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-[min(360px,calc(100vw-24px))] p-0" sideOffset={8}>
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div><p className="text-[12px] font-extrabold">Notifications</p><p className="mt-0.5 text-[9px] font-semibold text-ink-faint">{unreadCount ? `${unreadCount} items need attention` : "You are all caught up"}</p></div>
              <button type="button" onClick={() => setReadNotificationIds(notifications.map((notification) => notification.id))} disabled={!unreadCount} className="text-[9px] font-extrabold text-ink-muted hover:text-ink focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default disabled:opacity-40">Mark all read</button>
            </div>
            <div className="max-h-[360px] overflow-y-auto p-1">
              {notifications.map((notification) => (
                <DropdownMenuItem key={notification.id} onSelect={() => { setReadNotificationIds((ids) => ids.includes(notification.id) ? ids : [...ids, notification.id]); onOpenTicket(notification.id); }} className={cn("h-auto items-start gap-3 px-3 py-3", readNotificationIds.includes(notification.id) && "opacity-60")}>
                  <span className={cn("mt-1.5 size-2 shrink-0", notification.escalated ? "rotate-45 bg-ink" : notification.source === "groq" ? "rounded-full bg-accent" : "rounded-full border border-line-strong bg-paper")} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-3"><strong className="text-[10px] font-extrabold">{notification.notificationTitle}</strong><time className="shrink-0 text-[8px] font-bold text-ink-faint">{formatRelative(notification.minutesAgo)}</time></span>
                    <span className="mt-1 block truncate text-[10px] font-semibold text-ink-muted">{notification.customer.name} · {notification.id}</span>
                    <span className="mt-1 line-clamp-2 text-[9px] leading-4 text-ink-faint">{notification.message}</span>
                  </span>
                </DropdownMenuItem>
              ))}
            </div>
            <div className="border-t border-line p-1"><DropdownMenuItem onSelect={() => onView("queue")} className="justify-center">View support queue</DropdownMenuItem></div>
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" className="px-2.5 sm:px-3" aria-label="Open profile menu">
              <span className="grid size-5 place-items-center rounded-full bg-accent text-[8px] font-extrabold text-accent-ink sm:hidden">AO</span>
              <CircleUserRound className="hidden size-4 sm:block" /><span className="hidden sm:inline">Ada Okafor</span><ChevronDown className="size-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56" sideOffset={8}>
            <div className="px-2.5 py-2.5"><p className="text-[11px] font-extrabold">Ada Okafor</p><p className="mt-1 text-[9px] font-semibold text-ink-faint">Support manager</p></div>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Workspace</DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => onView("queue")}><Inbox className="size-3.5" />Support queue</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => onView("audit")}><Activity className="size-3.5" />My audit activity</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onLogout} className="text-ink"><LogOut className="size-3.5" />Log out</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}

function SignedOutView({ onReturn }) {
  return (
    <main className="grid min-h-screen place-items-center bg-canvas px-6 text-ink">
      <section className="w-full max-w-sm border border-line-strong bg-paper p-7 shadow-precision" aria-labelledby="signed-out-title">
        <div className="grid size-10 place-items-center bg-ink text-sm font-extrabold text-paper">KR</div>
        <p className="section-label mt-8">Local workspace</p>
        <h1 id="signed-out-title" className="mt-2 text-[24px] font-extrabold tracking-[-0.05em]">You are logged out</h1>
        <p className="mt-3 text-[11px] leading-5 text-ink-muted">Your Kora workspace is still running locally. Return when you are ready to continue triaging support cases.</p>
        <Button onClick={onReturn} className="mt-7 w-full">Return to workspace</Button>
      </section>
    </main>
  );
}

function MetricsStrip({ tickets }) {
  const live = tickets.filter(isProcessed);
  const correctLabels = live.reduce(
    (total, ticket) => total
      + Number(ticket.intent === ticket.truthIntent)
      + Number(ticket.urgency === ticket.truthUrgency),
    0
  );
  const liveAccuracy = live.length
    ? Math.round(correctLabels / (live.length * 2) * 100)
    : 0;
  const averageSaved = live.length
    ? live.reduce((sum, ticket) => sum + (ticket.estimatedMinutesSaved || 0), 0) / live.length
    : 0;
  const metrics = [
    { label: "Model accuracy", value: `${liveAccuracy}%`, meta: "intent + urgency", accent: true },
    { label: "Avg time saved", value: `${averageSaved.toFixed(1)}m`, meta: "12m manual baseline" },
    { label: "Human review", value: live.filter((ticket) => ticket.escalated).length, meta: "guardrail decisions" },
    { label: "Processed", value: live.length, meta: `${tickets.length - live.length} pending` }
  ];
  return (
    <section className="grid grid-cols-2 border-b border-line bg-paper xl:grid-cols-[repeat(4,minmax(150px,1fr))_minmax(260px,1.4fr)]" aria-label="Support metrics">
      {metrics.map((item) => (
        <div key={item.label} className="metric-cell">
          <div className="flex items-center justify-between gap-2"><span className="metric-label">{item.label}</span>{item.accent && <span className="size-2 rounded-full bg-accent" />}</div>
          <div className="mt-2 flex items-baseline gap-2"><strong>{item.value}</strong><small>{item.meta}</small></div>
        </div>
      ))}
      <div className="hidden min-h-[92px] items-center gap-4 px-6 xl:flex">
        <div className="w-24"><span className="metric-label">Hourly volume</span><strong className="mt-2 block text-[22px] tracking-[-0.05em]">14</strong></div>
        <div className="h-14 flex-1 overflow-hidden" aria-label="Hourly ticket volume trend">
          <svg viewBox="0 0 180 56" role="img" aria-label="Ticket volume rises from 5 to 14 with a peak of 18">
            <path d="M0 43 C15 42 18 20 35 24 S55 38 70 27 S88 10 104 22 S126 35 140 14 S163 8 180 17 L180 56 L0 56 Z" fill="var(--color-accent)" fillOpacity=".35" />
            <path d="M0 43 C15 42 18 20 35 24 S55 38 70 27 S88 10 104 22 S126 35 140 14 S163 8 180 17" fill="none" stroke="var(--color-ink)" strokeWidth="1.5" />
          </svg>
        </div>
      </div>
    </section>
  );
}

function QueueLoading() {
  return <div aria-label="Loading tickets" className="divide-y divide-line">{Array.from({ length: 5 }).map((_, index) => <div key={index} className="space-y-3 p-5"><div className="flex justify-between"><Skeleton className="h-3 w-28" /><Skeleton className="h-3 w-8" /></div><Skeleton className="h-4 w-44" /><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-2/3" /></div>)}</div>;
}

function EmptyQueue({ onReset }) {
  return (
    <div className="grid min-h-[430px] place-items-center px-8 text-center">
      <div className="max-w-[260px]"><div className="mx-auto grid size-12 place-items-center border border-line-strong bg-muted-surface"><Inbox className="size-5" /></div><h3 className="mt-5 text-[15px] font-extrabold tracking-[-0.03em]">No tickets match this view</h3><p className="mt-2 text-[11px] leading-5 text-ink-muted">Clear the filters to return to the full support queue.</p><Button onClick={onReset} variant="outline" size="sm" className="mt-5">Reset filters</Button></div>
    </div>
  );
}

function TicketRow({ ticket, selected, checked, onSelect, onCheck, automation = { enabled: true, auto_approve_threshold: 95, mandatory_review_threshold: 70 } }) {
  const sla = slaState(ticket);
  const policy = policyState(ticket, automation);
  return (
    <div data-ticket={ticket.id} className={cn("ticket-row group", selected && "bg-selected")}>
      <button type="button" onClick={() => onCheck(ticket.id)} aria-label={`${checked ? "Deselect" : "Select"} ${ticket.id}`} aria-pressed={checked} className="mt-0.5 grid size-5 shrink-0 place-items-center text-ink-faint hover:text-ink focus-visible:ring-2 focus-visible:ring-ring">{checked ? <SquareCheckBig className="size-4 text-ink" /> : <Square className="size-4" />}</button>
      <span className={cn("mt-1 size-2 shrink-0", ticket.urgency === "critical" ? "rotate-45 bg-ink" : ticket.urgency === "high" ? "rounded-full bg-accent ring-2 ring-accent/25" : "rounded-full border border-line-strong bg-paper")} />
      <button type="button" onClick={() => onSelect(ticket.id)} className="min-w-0 flex-1 text-left" aria-pressed={selected}>
        <span className="flex items-center justify-between gap-3"><strong className="truncate text-[12px] font-extrabold tracking-[-0.02em]">{ticket.customer.name}</strong><time className="text-[9px] font-bold text-ink-faint">{formatRelative(ticket.minutesAgo)}</time></span>
        <span className="mt-2 flex flex-wrap items-center gap-2"><span className="text-[10px] font-bold">{intentShort[ticket.intent] || ticket.intent}</span><span className="text-ink-faint">/</span><span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-ink-muted">{ticket.channel}</span>{policy === "mandatory" && <Badge variant="strong" className="ml-auto h-5 px-1.5">Review</Badge>}{policy === "auto" && <Badge variant="accent" className="ml-auto h-5 px-1.5">Auto</Badge>}</span>
        <span className="mt-2.5 line-clamp-2 text-[10px] leading-[1.55] text-ink-muted">{ticket.message}</span>
        <span className="mt-3 flex flex-wrap items-center gap-3 text-[9px] font-bold text-ink-faint"><span>{ticket.id}</span><span>{isProcessed(ticket) ? `${Math.round(ticket.confidence * 100)}% confidence` : "Live triage pending"}</span>{ticket.memoryUsed && <span className="text-ink">Memory used</span>}{sla && <span className={cn("inline-flex items-center gap-1", sla.overdue ? "text-ink" : "text-ink-muted")}><Timer className="size-3" />{sla.label}</span>}</span>
      </button>
      <ArrowRight className={cn("mt-0.5 size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100", selected && "opacity-100")} />
    </div>
  );
}

function QueuePane({ tickets, selectedId, onSelect, loading, query, onQuery, filters, onFilters, selectedIds = [], onToggle, onSelectAll, onBulkApprove, onBulkRoute, bulkLoading, automation = { enabled: true, auto_approve_threshold: 95, mandatory_review_threshold: 70 } }) {
  const reset = () => { onQuery(""); onFilters({ review: false, high: false, channel: "all", urgency: "all", team: "all" }); };
  const allSelected = tickets.length > 0 && tickets.every((ticket) => selectedIds.includes(ticket.id));
  const selectedLowRisk = tickets.filter((ticket) => selectedIds.includes(ticket.id) && lowRisk(ticket)).length;
  const chip = (label, value, options, key) => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button variant={value === "all" ? "outline" : "default"} size="sm" className="h-7 px-2 text-[9px]">{label}: {value === "all" ? "All" : value}<ChevronDown className="size-3" /></Button></DropdownMenuTrigger>
      <DropdownMenuContent align="start">{options.map((option) => <DropdownMenuItem key={option.value} onSelect={() => onFilters({ ...filters, [key]: option.value })}>{option.label}{value === option.value && <Check className="ml-auto size-3" />}</DropdownMenuItem>)}</DropdownMenuContent>
    </DropdownMenu>
  );
  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col border-r border-line bg-paper" aria-labelledby="queue-heading">
      <div className="border-b border-line p-4 sm:p-5">
        <div className="flex items-center justify-between"><div><p className="section-label">Incoming</p><h2 id="queue-heading" className="mt-1 text-[17px] font-extrabold tracking-[-0.04em]">Open conversations <span className="text-ink-faint">{tickets.length}</span></h2></div>
          <DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline" size="icon" aria-label="Filter tickets"><Filter className="size-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuCheckboxItem checked={filters.review} onCheckedChange={(value) => onFilters({ ...filters, review: value })}>Needs human review</DropdownMenuCheckboxItem><DropdownMenuCheckboxItem checked={filters.high} onCheckedChange={(value) => onFilters({ ...filters, high: value })}>High or critical urgency</DropdownMenuCheckboxItem><DropdownMenuItem onSelect={reset}>Clear all filters</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
        </div>
        <label className="mt-4 flex h-10 items-center gap-2 border border-line-strong bg-canvas px-3 focus-within:ring-2 focus-within:ring-ring"><Search className="size-4 text-ink-faint" /><span className="sr-only">Search tickets</span><input value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Search name, case or message" className="min-w-0 flex-1 bg-transparent text-[11px] font-semibold outline-none placeholder:text-ink-faint" /></label>
        <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Ticket filters">
          {chip("Channel", filters.channel, [{ value: "all", label: "All channels" }, { value: "whatsapp", label: "WhatsApp" }, { value: "email", label: "Email" }], "channel")}
          {chip("Urgency", filters.urgency, [{ value: "all", label: "All urgency" }, ...["critical", "high", "medium", "low"].map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) }))], "urgency")}
          {chip("Team", filters.team, [{ value: "all", label: "All teams" }, ...teamOptions.map((value) => ({ value, label: value }))], "team")}
          {(query || filters.review || filters.high || filters.channel !== "all" || filters.urgency !== "all" || filters.team !== "all") && <Button variant="ghost" size="sm" className="h-7 px-2 text-[9px]" onClick={reset}><X className="size-3" />Clear</Button>}
        </div>
      </div>
      <div className="flex min-h-10 items-center justify-between border-b border-line bg-muted-surface px-4 py-2">
        <button type="button" onClick={() => onSelectAll(tickets.map((ticket) => ticket.id), !allSelected)} className="flex items-center gap-2 text-[9px] font-extrabold uppercase tracking-[0.08em] text-ink-muted">{allSelected ? <SquareCheckBig className="size-4 text-ink" /> : <Square className="size-4" />}{selectedIds.length ? `${selectedIds.length} selected` : "Select all"}</button>
        {selectedIds.length > 0 && <div className="flex items-center gap-1.5"><Button size="sm" variant="outline" className="h-7 px-2 text-[9px]" disabled={!selectedLowRisk || bulkLoading} onClick={onBulkApprove}><Check className="size-3" />Approve {selectedLowRisk || ""}</Button><DropdownMenu><DropdownMenuTrigger asChild><Button size="sm" className="h-7 px-2 text-[9px]" disabled={bulkLoading}><Route className="size-3" />Route<ChevronDown className="size-3" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">{teamOptions.map((team) => <DropdownMenuItem key={team} onSelect={() => onBulkRoute(team)}>{team}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu></div>}
      </div>
      <div className="queue-scroll">{loading ? <QueueLoading /> : tickets.length ? tickets.map((ticket) => <TicketRow key={ticket.id} ticket={ticket} selected={selectedId === ticket.id} checked={selectedIds.includes(ticket.id)} onSelect={onSelect} onCheck={onToggle} automation={automation} />) : <EmptyQueue onReset={reset} />}</div>
    </section>
  );
}

function EntityTag({ label, value }) {
  return <div className="border border-line bg-paper px-3 py-2"><span className="block text-[8px] font-extrabold uppercase tracking-[0.1em] text-ink-faint">{label}</span><strong className="mt-1 block text-[10px] font-bold">{value}</strong></div>;
}

function TicketDetail({ ticket, onApprove, onEscalate, onRunAI, aiLoading, actionLoading, backend, automation = { enabled: true, auto_approve_threshold: 95, mandatory_review_threshold: 70 }, memoryItems = [], memoryLoading = false }) {
  const [draft, setDraft] = useState(ticket.response);
  useEffect(() => setDraft(ticket.response), [ticket.id, ticket.response]);
  const entities = Object.entries(ticket.entities).filter(([, value]) => value);
  const labels = { amount: "Amount", transactionId: "Transaction ID", orderId: "Order ID", account: "Account", card: "Card" };
  const sla = slaState(ticket);
  const policy = policyState(ticket, automation);

  return (
    <article className="detail-scroll bg-canvas" aria-labelledby="ticket-title">
      <header className="sticky top-0 z-10 flex min-h-[86px] items-center justify-between gap-4 border-b border-line bg-canvas/95 px-5 backdrop-blur-sm sm:px-7">
        <div className="min-w-0"><div className="flex items-center gap-2"><span className="section-label">{ticket.id}</span><span className="text-ink-faint">/</span><span className="section-label">{ticket.channel}</span></div><h2 id="ticket-title" className="mt-1 truncate text-[20px] font-extrabold tracking-[-0.045em]">{ticket.customer.name}</h2></div>
        <div className="flex items-center gap-2">{sla && <Badge variant={sla.overdue ? "strong" : "outline"} shape="pill"><Timer className="size-3" />{sla.label}</Badge>}<UrgencyBadge urgency={ticket.urgency} /><DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline" size="icon" aria-label="More case actions"><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem>Copy case link</DropdownMenuItem><DropdownMenuItem>Add internal note</DropdownMenuItem><DropdownMenuItem>Mark as duplicate</DropdownMenuItem></DropdownMenuContent></DropdownMenu></div>
      </header>

      <div className="detail-content">
        <section className="border-b border-line bg-paper p-5 sm:p-7" aria-labelledby="customer-message-title">
          <div className="flex items-center justify-between gap-4"><div><p className="section-label">Raw customer input</p><h3 id="customer-message-title" className="mt-1 text-[14px] font-extrabold">Customer message</h3></div><span className="flex items-center gap-1.5 text-[9px] font-bold text-ink-faint"><Clock3 className="size-3" />{ticket.receivedAt}</span></div>
          {ticket.subject && <p className="mt-5 text-[11px] font-extrabold">{ticket.subject}</p>}
          <blockquote className="mt-4 max-w-[70ch] text-[13px] font-medium leading-7 tracking-[-0.01em] text-ink-muted">“{ticket.message}”</blockquote>
          <div className="mt-6 flex flex-wrap gap-2">{entities.map(([key, value]) => <EntityTag key={key} label={labels[key]} value={value} />)}</div>
        </section>

        <div className="grid xl:grid-cols-[minmax(0,1.08fr)_minmax(300px,.92fr)]">
          <section className="ai-panel border-b border-line p-5 sm:p-7 xl:border-b-0 xl:border-r" aria-labelledby="ai-reasoning-title">
            <div className="flex items-start justify-between gap-4"><div><div className="flex items-center gap-2"><Bot className="size-4" /><p className="section-label !text-ink">AI assessment</p></div><h3 id="ai-reasoning-title" className="mt-2 text-[16px] font-extrabold tracking-[-0.03em]">Decision and reasoning</h3></div>{isProcessed(ticket) ? <Badge variant={ticket.confidence < .8 ? "strong" : "accent"} shape="pill">{Math.round(ticket.confidence * 100)}% confidence</Badge> : <Badge variant="outline" shape="pill">Awaiting Groq</Badge>}</div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-y border-line-strong py-3">
              <span className="text-[9px] font-bold text-ink-muted">{ticket.source === "groq" ? `Live result · ${ticket.model}` : ticket.source === "seeded" ? `Model snapshot · ${ticket.model}` : "No local classification fallback"}</span>
              {backend.configured && ticket.source !== "groq" && <Button onClick={() => onRunAI(ticket)} disabled={aiLoading} variant="outline" size="sm">{aiLoading ? <LoaderCircle className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}{aiLoading ? "Running Groq" : "Refresh with live AI"}</Button>}
              {ticket.source === "groq" && <Badge variant="accent" shape="pill"><Check className="size-3" />Groq verified</Badge>}
            </div>
            {!backend.configured && <p className="mt-3 text-[9px] leading-4 text-ink-faint">{backend.state === "online" ? "Live classification is blocked until GROQ_API_KEY is configured in backend/.env." : "The backend API is offline. Start it to enable live classification."}</p>}
            <div className="mt-6 grid grid-cols-2 gap-px border border-line-strong bg-line-strong">
              {[['Intent', ticket.intent], ['Urgency', ticket.urgency], ['Sentiment', ticket.sentiment], ['Route', ticket.route]].map(([label, value]) => <div key={label} className="bg-ai px-3 py-3"><span className="text-[8px] font-extrabold uppercase tracking-[0.1em] text-ink-faint">{label}</span><strong className="mt-1 block text-[11px] font-extrabold capitalize">{value}</strong></div>)}
            </div>
            <details open className="mt-5 border border-line-strong bg-paper">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3"><span className="flex items-center gap-2"><Database className="size-3.5" /><strong className="text-[9px] font-extrabold uppercase tracking-[0.09em]">SQLite customer memory</strong></span><span className="flex items-center gap-2">{ticket.memoryUsed && <Badge variant="outline" shape="pill">Reused</Badge>}<ChevronDown className="size-3" /></span></summary>
              <div className="border-t border-line px-4 py-3">{memoryLoading ? <div className="space-y-2"><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /></div> : memoryItems.length ? <div className="space-y-2">{memoryItems.slice(0, 2).map((memory) => <div key={`${memory.case_id}-${memory.created_at}`} className="bg-muted-surface p-3"><div className="flex items-center justify-between gap-3"><strong className="text-[9px] font-extrabold">{memory.case_id}</strong><time className="text-[8px] text-ink-faint">{new Date(memory.created_at).toLocaleDateString()}</time></div><p className="mt-1 text-[9px] leading-4 text-ink-muted">{memory.summary}</p></div>)}</div> : <p className="text-[10px] leading-5 text-ink-muted">No stored case memory yet. Provided context: {ticket.customer.previousContext}</p>}</div>
            </details>
            <div className="mt-6"><p className="section-label !text-ink">Evidence used</p>{ticket.evidence.length ? <ol className="mt-3 space-y-3">{ticket.evidence.map((item, index) => <li key={item} className="flex items-start gap-3 text-[10px] font-semibold leading-5 text-ink-muted"><span className="grid size-5 shrink-0 place-items-center border border-ink text-[8px] font-extrabold text-ink">0{index + 1}</span>{item}</li>)}</ol> : <p className="mt-3 text-[10px] text-ink-faint">Evidence will appear after live Groq classification.</p>}</div>
            {ticket.escalationReason && <div className="mt-6 flex gap-3 border border-ink bg-ink p-4 text-paper"><ShieldAlert className="mt-0.5 size-4 shrink-0 text-accent" /><div><strong className="text-[10px] font-extrabold uppercase tracking-[0.08em]">Escalation rule triggered</strong><p className="mt-1 text-[10px] leading-5 text-paper/70">{ticket.escalationReason}</p></div></div>}
          </section>

          <section className="human-panel p-5 sm:p-7" aria-labelledby="human-checkpoint-title">
            <div className="flex items-center gap-2"><UserRoundCheck className="size-4" /><p className="section-label !text-ink">Human checkpoint</p></div>
            <h3 id="human-checkpoint-title" className="mt-2 text-[16px] font-extrabold tracking-[-0.03em]">Review before action</h3>
            <p className="mt-2 text-[10px] leading-5 text-ink-muted">{policy === "auto" ? `This response qualifies for auto-approval at the ${automation.auto_approve_threshold}% threshold.` : policy === "mandatory" ? "Policy requires a human decision before this response can be sent." : "The AI prepared this response. An agent owns the final decision and can edit every word."}</p>
            <label className="mt-6 block"><span className="mb-2 block text-[9px] font-extrabold uppercase tracking-[0.09em] text-ink-muted">Response draft</span><textarea value={draft} onChange={(event) => setDraft(event.target.value)} disabled={!isProcessed(ticket)} placeholder="A live Groq draft will appear here." rows={10} className="w-full resize-none border border-line-strong bg-paper p-4 text-[11px] font-medium leading-6 outline-none placeholder:text-ink-faint focus:ring-2 focus:ring-ring disabled:bg-muted-surface" /></label>
            <div className="mt-4 flex items-center justify-between text-[9px] font-semibold text-ink-faint"><span>{draft.length} characters</span><span>{ticket.customer.notes.some((note) => note.includes("Pidgin")) ? "Pidgin aware" : "English"}</span></div>
            <div className="mt-6 border-t border-line-strong pt-5">
              {!isProcessed(ticket) ? <Button disabled className="w-full"><LoaderCircle className={cn("size-4", aiLoading && "animate-spin")} />{aiLoading ? "Running live triage" : "Live triage required"}</Button> : policy === "mandatory" ? <Button disabled={actionLoading} onClick={() => onEscalate(ticket.id, draft)} variant="default" className="w-full">{actionLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Users className="size-4" />}Assign to specialist</Button> : <div className="grid grid-cols-[auto_1fr] gap-2"><Button disabled={actionLoading} onClick={() => onEscalate(ticket.id, draft)} variant="outline" aria-label="Escalate to a person"><Users className="size-4" /></Button><Button disabled={actionLoading} onClick={() => onApprove(ticket.id, draft)} variant="accent">{actionLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Check className="size-4" />}Approve and send</Button></div>}
              <p className="mt-3 text-center text-[8px] font-bold uppercase tracking-[0.08em] text-ink-faint">No financial action is automated</p>
            </div>
          </section>
        </div>
      </div>
    </article>
  );
}

function TeamView({ tickets }) {
  const members = [
    { name: "Ada Okafor", role: "Support manager", teams: teamOptions, initials: "AO" },
    { name: "Musa Ibrahim", role: "Payments specialist", teams: ["Transfers", "Billing"], initials: "MI" },
    { name: "Nneka Eze", role: "Risk specialist", teams: ["Fraud", "Compliance"], initials: "NE" },
    { name: "Bola Martins", role: "Customer operations", teams: ["Logistics", "Account Support", "General Support"], initials: "BM" }
  ];
  return (
    <div className="view-padding">
      <div className="mb-7"><p className="section-label">Workload ownership</p><h2 className="mt-1 text-[24px] font-extrabold tracking-[-0.05em]">Team coverage</h2><p className="mt-2 max-w-xl text-[11px] leading-5 text-ink-muted">Current queue volume mapped to the specialists responsible for each resolution path.</p></div>
      <Card className="overflow-hidden"><Table><TableHeader><TableRow><TableHead>Team member</TableHead><TableHead>Role</TableHead><TableHead>Coverage</TableHead><TableHead>Open queue</TableHead><TableHead>Status</TableHead></TableRow></TableHeader><TableBody>{members.map((member) => { const count = tickets.filter((ticket) => member.teams.includes(ticket.route)).length; return <TableRow key={member.name}><TableCell><span className="flex items-center gap-3"><span className="grid size-8 place-items-center rounded-full bg-muted-surface text-[9px] font-extrabold">{member.initials}</span><strong>{member.name}</strong></span></TableCell><TableCell>{member.role}</TableCell><TableCell className="max-w-xs">{member.teams.join(", ")}</TableCell><TableCell><strong className="text-sm">{count}</strong></TableCell><TableCell><Badge variant="accent" shape="pill"><span className="size-1.5 rounded-full bg-current" />Online</Badge></TableCell></TableRow>; })}</TableBody></Table></Card>
    </div>
  );
}

function SettingsView({ automation, onChange, onSave, saving, tickets }) {
  const autoCount = tickets.filter((ticket) => policyState(ticket, automation) === "auto").length;
  const reviewCount = tickets.filter((ticket) => policyState(ticket, automation) === "mandatory").length;
  const normalCount = tickets.filter((ticket) => policyState(ticket, automation) === "normal").length;
  return (
    <div className="view-padding max-w-5xl">
      <div className="mb-7"><p className="section-label">Decision policy</p><h2 className="mt-1 text-[24px] font-extrabold tracking-[-0.05em]">Confidence automation</h2><p className="mt-2 max-w-2xl text-[11px] leading-5 text-ink-muted">Define which low-risk drafts can move automatically and where human review is mandatory. Fraud and guardrail-triggered cases always remain human-owned.</p></div>
      <div className="grid gap-5 lg:grid-cols-[1.2fr_.8fr]">
        <Card className="p-6">
          <div className="flex items-start justify-between gap-5 border-b border-line pb-5"><div><div className="flex items-center gap-2"><Zap className="size-4" /><h3 className="text-[14px] font-extrabold">Auto-approve eligible drafts</h3></div><p className="mt-2 max-w-lg text-[10px] leading-5 text-ink-muted">When enabled, newly triaged responses at or above the upper threshold are recorded as auto-approved when no safety guardrail is active.</p></div><button type="button" role="switch" aria-checked={automation.enabled} onClick={() => onChange({ ...automation, enabled: !automation.enabled })} className={cn("relative h-6 w-11 shrink-0 border transition-colors focus-visible:ring-2 focus-visible:ring-ring", automation.enabled ? "border-ink bg-ink" : "border-line-strong bg-muted-surface")}><span className={cn("absolute top-1 size-3.5 bg-paper transition-transform", automation.enabled ? "translate-x-5" : "translate-x-1")} /></button></div>
          <label className="mt-6 block"><span className="flex items-center justify-between"><span className="text-[10px] font-extrabold">Auto-approve threshold</span><strong className="text-[20px] tracking-[-0.04em]">{automation.auto_approve_threshold}%</strong></span><input type="range" min="80" max="99" value={automation.auto_approve_threshold} onChange={(event) => onChange({ ...automation, auto_approve_threshold: Number(event.target.value) })} className="mt-4 w-full accent-[var(--color-ink)]" /><span className="mt-2 flex justify-between text-[8px] font-bold text-ink-faint"><span>80%</span><span>99%</span></span></label>
          <label className="mt-7 block border-t border-line pt-6"><span className="flex items-center justify-between"><span className="text-[10px] font-extrabold">Mandatory review below</span><strong className="text-[20px] tracking-[-0.04em]">{automation.mandatory_review_threshold}%</strong></span><input type="range" min="50" max="90" value={automation.mandatory_review_threshold} onChange={(event) => onChange({ ...automation, mandatory_review_threshold: Number(event.target.value) })} className="mt-4 w-full accent-[var(--color-ink)]" /><span className="mt-2 flex justify-between text-[8px] font-bold text-ink-faint"><span>50%</span><span>90%</span></span></label>
          {automation.mandatory_review_threshold >= automation.auto_approve_threshold && <p className="mt-4 flex items-center gap-2 text-[10px] font-bold"><CircleAlert className="size-4" />The lower threshold must remain below auto-approve.</p>}
          <Button onClick={onSave} disabled={saving || automation.mandatory_review_threshold >= automation.auto_approve_threshold} className="mt-7"><Save className="size-4" />{saving ? "Saving policy" : "Save automation policy"}</Button>
        </Card>
        <div className="border border-line-strong bg-ai p-6"><p className="section-label !text-ink">Current queue impact</p><h3 className="mt-2 text-[15px] font-extrabold">Policy preview</h3><div className="mt-6 divide-y divide-line-strong border-y border-line-strong">{[["Auto-approve", autoCount, "At or above upper threshold"], ["Normal queue", normalCount, "Agent review remains optional"], ["Mandatory review", reviewCount, "Low confidence or guardrail"]].map(([label, count, meta], index) => <div key={label} className="flex items-center justify-between py-4"><span><strong className="block text-[10px]">{label}</strong><small className="mt-1 block text-[8px] text-ink-faint">{meta}</small></span><strong className={cn("text-[22px] tracking-[-0.05em]", index === 0 && "text-accent-ink")}>{count}</strong></div>)}</div><p className="mt-5 text-[9px] leading-5 text-ink-muted">This policy records approval decisions inside Kora. A WhatsApp or email delivery provider must be connected before drafts can be transmitted externally.</p></div>
      </div>
    </div>
  );
}

function AuditView({ items, loading }) {
  const exportCsv = () => {
    const headings = ["time", "case", "customer", "event", "model_or_actor", "decision", "guardrail_reason"];
    const rows = items.map((item) => [
      item.created_at,
      item.case_id,
      item.customer_id,
      item.event_type,
      item.model || item.actor || "human",
      item.decision.intent || item.decision.status || "",
      item.guardrails.reason || ""
    ]);
    const csv = [headings, ...rows]
      .map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(","))
      .join("\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    link.download = "kora-live-audit.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  };

  return (
    <div className="view-padding">
      <div className="mb-7 flex items-end justify-between gap-4">
        <div><p className="section-label">Persisted decision record</p><h2 className="mt-1 text-[24px] font-extrabold tracking-[-0.05em]">Every action, explained</h2><p className="mt-2 max-w-xl text-[11px] leading-5 text-ink-muted">Seeded model snapshots, new live Groq classifications, and human interventions are loaded from SQLite, so this record survives page reloads.</p></div>
        <Button variant="outline" onClick={exportCsv} disabled={!items.length}><Download className="size-4" />Export CSV</Button>
      </div>
      <Card className="overflow-x-auto">
        {loading ? <div className="space-y-3 p-5"><Skeleton className="h-10 w-full" /><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /></div> : items.length ? <Table>
          <TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Case</TableHead><TableHead className="min-w-[148px]">Event</TableHead><TableHead>Decision</TableHead><TableHead>Model / actor</TableHead><TableHead>Why</TableHead></TableRow></TableHeader>
          <TableBody>{items.map((item) => {
            const decision = item.decision;
            const summary = decision.intent || decision.status || "Recorded action";
            const reason = item.guardrails.reason || decision.evidence?.join("; ") || "Human decision";
            return <TableRow key={item.id}><TableCell><time className="font-bold">{new Date(item.created_at).toLocaleString()}</time></TableCell><TableCell><strong className="block font-extrabold">{item.case_id}</strong><span className="mt-1 block text-[9px] text-ink-faint">{item.customer_id}</span></TableCell><TableCell className="whitespace-nowrap"><Badge variant={item.event_type === "triage" ? "neutral" : "accent"}>{item.event_type.replaceAll("_", " ")}</Badge></TableCell><TableCell><strong className="block font-bold">{summary}</strong>{decision.urgency && <span className="mt-1 block capitalize text-ink-faint">{decision.urgency} · {decision.route}</span>}</TableCell><TableCell>{item.model || item.actor || "human"}</TableCell><TableCell className="max-w-sm text-ink-muted">{reason}</TableCell></TableRow>;
          })}</TableBody>
        </Table> : <div className="p-12 text-center"><Activity className="mx-auto size-6 text-ink-faint" /><h3 className="mt-4 text-sm font-extrabold">No persisted decisions yet</h3><p className="mt-2 text-[10px] text-ink-muted">Run live triage to create the first audit entry.</p></div>}
      </Card>
    </div>
  );
}

function DashboardApp() {
  const [signedIn, setSignedIn] = useState(true);
  const [tickets, setTickets] = useState(seedTickets);
  const [activeView, setActiveView] = useState("queue");
  const [selectedId, setSelectedId] = useState(seedTickets.find((ticket) => ticket.urgency === "critical")?.id || seedTickets[0].id);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ review: false, high: false, channel: "all", urgency: "all", team: "all" });
  const [selectedIds, setSelectedIds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [railOpen, setRailOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [backend, setBackend] = useState({ state: "checking", configured: false });
  const [aiLoadingId, setAiLoadingId] = useState(null);
  const [actionLoadingId, setActionLoadingId] = useState(null);
  const [auditItems, setAuditItems] = useState([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [memoryItems, setMemoryItems] = useState([]);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [automation, setAutomation] = useState({ enabled: true, auto_approve_threshold: 95, mandatory_review_threshold: 70 });
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [bulkLoading, setBulkLoading] = useState(false);
  const activeFilters = { review: false, high: false, channel: "all", urgency: "all", team: "all", ...filters };

  const refreshAudit = async () => {
    setAuditLoading(true);
    try {
      const result = await getBackendAudit(200);
      setAuditItems(result.items || []);
    } catch (error) {
      setToast(error.message || "Could not load the audit trail");
    } finally {
      setAuditLoading(false);
    }
  };

  const refreshMemory = async (customerId) => {
    setMemoryLoading(true);
    try {
      const result = await getCustomerMemory(customerId);
      setMemoryItems(result.items || []);
    } catch (error) {
      setMemoryItems([]);
      setToast(error.message || "Could not load customer memory");
    } finally {
      setMemoryLoading(false);
    }
  };

  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(""), 2600); return () => clearTimeout(timer); }, [toast]);
  useEffect(() => {
    let active = true;
    getBackendHealth()
      .then((health) => active && setBackend({ state: "online", ...health }))
      .catch(() => { if (active) { setBackend({ state: "offline", configured: false }); setLoading(false); } });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (backend.state !== "online") return;
    let active = true;
    Promise.all([getCases(), getAutomationSettings(), getBackendAudit(200)])
      .then(([caseResult, settingsResult, auditResult]) => {
        if (!active) return;
        setTickets(caseResult.items || seedTickets);
        setAutomation(settingsResult);
        setAuditItems(auditResult.items || []);
      })
      .catch((error) => active && setToast(error.message || "Could not load the operations dataset"))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [backend.state]);
  useEffect(() => {
    if (activeView === "audit" && backend.state === "online") refreshAudit();
  }, [activeView, backend.state]);

  const visibleTickets = useMemo(() => tickets.filter((ticket) => {
    const text = `${ticket.id} ${ticket.customer.name} ${ticket.message} ${ticket.intent}`.toLowerCase();
    return (!query || text.includes(query.toLowerCase()))
      && (!activeFilters.review || policyState(ticket, automation) === "mandatory")
      && (!activeFilters.high || ["critical", "high"].includes(ticket.urgency))
      && (activeFilters.channel === "all" || ticket.channel === activeFilters.channel)
      && (activeFilters.urgency === "all" || ticket.urgency === activeFilters.urgency)
      && (activeFilters.team === "all" || ticket.route === activeFilters.team);
  }).sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency] || a.minutesAgo - b.minutesAgo), [tickets, query, activeFilters.review, activeFilters.high, activeFilters.channel, activeFilters.urgency, activeFilters.team, automation]);

  useEffect(() => { if (visibleTickets.length && !visibleTickets.some((ticket) => ticket.id === selectedId)) setSelectedId(visibleTickets[0].id); }, [visibleTickets, selectedId]);
  const selectedTicket = tickets.find((ticket) => ticket.id === selectedId) || tickets[0];
  useEffect(() => {
    if (backend.state === "online") refreshMemory(selectedTicket.customerId);
  }, [backend.state, selectedTicket.customerId]);
  const updateStatus = (id, status, escalated) => setTickets((items) => items.map((ticket) => ticket.id === id ? { ...ticket, status, escalated: escalated ?? ticket.escalated } : ticket));
  const runLiveAI = async (ticket) => {
    setAiLoadingId(ticket.id);
    try {
      const result = await runGroqTriage(ticket);
      const updatedTicket = {
        ...ticket,
        intent: result.intent,
        urgency: result.urgency,
        sentiment: result.sentiment,
        route: result.route,
        confidence: result.confidence,
        entities: result.entities,
        memoryUsed: result.memory_used,
        escalated: result.escalated,
        escalationReason: result.escalation_reason,
        evidence: result.evidence,
        response: result.response,
        status: result.status,
        source: result.source,
        model: result.model,
        auditId: result.audit_id,
        processingMs: result.processing_ms,
        estimatedMinutesSaved: result.estimated_minutes_saved
      };
      const shouldAutoApprove = result.status === "Auto-approved";
      setTickets((items) => items.map((item) => item.id === ticket.id ? { ...updatedTicket, customer: item.customer } : item));
      refreshAudit();
      refreshMemory(ticket.customerId);
      setToast(shouldAutoApprove ? `${ticket.id} auto-approved at ${Math.round(result.confidence * 100)}%` : `${ticket.id} classified by ${result.model}`);
    } catch (error) {
      setToast(error.message || "Live triage failed");
    } finally {
      setAiLoadingId(null);
    }
  };
  const approve = async (id, draft) => {
    const ticket = tickets.find((item) => item.id === id);
    if (!isProcessed(ticket)) {
      setToast("Model triage is required before approval");
      return;
    }
    setActionLoadingId(id);
    try {
      await recordCaseAction(ticket, "approve", draft);
      updateStatus(id, "Approved", false);
      refreshAudit();
      setToast(`${id} approval recorded`);
    } catch (error) {
      setToast(error.message || "Approval failed");
    } finally {
      setActionLoadingId(null);
    }
  };
  const escalate = async (id, draft) => {
    const ticket = tickets.find((item) => item.id === id);
    if (!isProcessed(ticket)) {
      setToast("Model triage is required before escalation");
      return;
    }
    setActionLoadingId(id);
    try {
      await recordCaseAction(ticket, "escalate", draft);
      updateStatus(id, "Assigned", true);
      refreshAudit();
      setToast(`${id} assigned and recorded`);
    } catch (error) {
      setToast(error.message || "Escalation failed");
    } finally {
      setActionLoadingId(null);
    }
  };

  const toggleSelected = (id) => setSelectedIds((ids) => ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]);
  const selectAll = (ids, checked) => setSelectedIds((current) => checked ? [...new Set([...current, ...ids])] : current.filter((id) => !ids.includes(id)));
  const bulkApprove = async () => {
    const eligible = tickets.filter((ticket) => selectedIds.includes(ticket.id) && lowRisk(ticket));
    if (!eligible.length) return;
    setBulkLoading(true);
    try {
      await Promise.all(eligible.map((ticket) => recordCaseAction(ticket, "approve", ticket.response)));
      const approvedIds = new Set(eligible.map((ticket) => ticket.id));
      setTickets((items) => items.map((ticket) => approvedIds.has(ticket.id) ? { ...ticket, status: "Approved" } : ticket));
      setSelectedIds((ids) => ids.filter((id) => !approvedIds.has(id)));
      refreshAudit();
      setToast(`${eligible.length} low-risk ${eligible.length === 1 ? "case" : "cases"} approved`);
    } catch (error) {
      setToast(error.message || "Bulk approval failed");
    } finally {
      setBulkLoading(false);
    }
  };
  const bulkRoute = async (team) => {
    const selected = tickets.filter((ticket) => selectedIds.includes(ticket.id) && lowRisk(ticket));
    if (!selected.length) return;
    setBulkLoading(true);
    try {
      await Promise.all(selected.map((ticket) => recordCaseRoute(ticket, team)));
      const routedIds = new Set(selected.map((ticket) => ticket.id));
      setTickets((items) => items.map((ticket) => routedIds.has(ticket.id) ? { ...ticket, route: team, status: `Routed to ${team}` } : ticket));
      setSelectedIds([]);
      refreshAudit();
      setToast(`${selected.length} ${selected.length === 1 ? "case" : "cases"} routed to ${team}`);
    } catch (error) {
      setToast(error.message || "Bulk routing failed");
    } finally {
      setBulkLoading(false);
    }
  };
  const saveAutomation = async () => {
    setSettingsSaving(true);
    try {
      const saved = await updateAutomationSettings(automation);
      setAutomation(saved);
      setToast("Automation policy saved");
    } catch (error) {
      setToast(error.message || "Could not save automation policy");
    } finally {
      setSettingsSaving(false);
    }
  };

  const openTicketFromNotification = (id) => {
    setQuery("");
    setFilters({ review: false, high: false, channel: "all", urgency: "all", team: "all" });
    setActiveView("queue");
    setSelectedId(id);
  };

  if (!signedIn) return <SignedOutView onReturn={() => setSignedIn(true)} />;

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <Rail activeView={activeView} onView={setActiveView} open={railOpen} onClose={() => setRailOpen(false)} />
      <div className="lg:pl-[214px]"><Header activeView={activeView} onMenu={() => setRailOpen(true)} backend={backend} tickets={tickets} onOpenTicket={openTicketFromNotification} onView={setActiveView} onLogout={() => setSignedIn(false)} /><main id="main-content" tabIndex={-1}>{activeView === "queue" && <><MetricsStrip tickets={tickets} /><div className="workspace-grid"><QueuePane tickets={visibleTickets} selectedId={selectedId} onSelect={setSelectedId} loading={loading} query={query} onQuery={setQuery} filters={activeFilters} onFilters={setFilters} selectedIds={selectedIds} onToggle={toggleSelected} onSelectAll={selectAll} onBulkApprove={bulkApprove} onBulkRoute={bulkRoute} bulkLoading={bulkLoading} automation={automation} /><TicketDetail ticket={selectedTicket} onApprove={approve} onEscalate={escalate} onRunAI={runLiveAI} aiLoading={aiLoadingId === selectedTicket.id} actionLoading={actionLoadingId === selectedTicket.id} backend={backend} automation={automation} memoryItems={memoryItems} memoryLoading={memoryLoading} /></div></>}{activeView === "insights" && <Suspense fallback={<div className="view-padding"><Skeleton className="h-[420px] w-full" /></div>}><InsightsView tickets={tickets} /></Suspense>}{activeView === "audit" && <AuditView items={auditItems} loading={auditLoading} />}{activeView === "team" && <TeamView tickets={tickets} />}{activeView === "settings" && <SettingsView automation={automation} onChange={setAutomation} onSave={saveAutomation} saving={settingsSaving} tickets={tickets} />}</main></div>
      {railOpen && <button className="fixed inset-0 z-30 bg-ink/20 lg:hidden" onClick={() => setRailOpen(false)} aria-label="Close navigation overlay" />}
      <div role="status" aria-live="polite" className={cn("fixed bottom-5 right-5 z-50 flex items-center gap-2 border border-ink bg-ink px-4 py-3 text-[11px] font-bold text-paper shadow-precision transition-all", toast ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-3 opacity-0")}><CheckCircle2 className="size-4 text-accent" />{toast}</div>
    </div>
  );
}

function surfaceFromLocation() {
  return window.location.pathname === "/app" || window.location.pathname.startsWith("/app/")
    ? "workspace"
    : "landing";
}

export default function App() {
  const [surface, setSurface] = useState(surfaceFromLocation);

  useEffect(() => {
    const handleNavigation = () => setSurface(surfaceFromLocation());
    window.addEventListener("popstate", handleNavigation);
    return () => window.removeEventListener("popstate", handleNavigation);
  }, []);

  const openWorkspace = () => {
    window.history.pushState({}, "", "/app");
    setSurface("workspace");
    window.scrollTo({ top: 0, behavior: "instant" });
  };

  return surface === "workspace"
    ? <DashboardApp />
    : <LandingPage onOpenWorkspace={openWorkspace} />;
}
