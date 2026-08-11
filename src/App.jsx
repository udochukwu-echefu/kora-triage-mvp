import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, AlertTriangle, ArrowLeft, ArrowRight, BarChart3, Bell, BellRing, Bot, Check, CheckCheck,
  BookOpenCheck, CheckCircle2, ChevronDown, CircleAlert, CircleUserRound, ClipboardCheck,
  Clock3, CreditCard, Database, Download, Filter, Inbox, LoaderCircle, LogOut, Mail, Menu,
  GitFork, MessageCircle, MessagesSquare, MoreHorizontal, Route,
  Eye, Save, Search, Send, Settings, ShieldAlert, ShieldCheck, Sparkles, Square, SquareCheckBig, Timer,
  UserPlus, UserRoundCheck, Users, WifiOff, Wrench, X, Zap
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./components/ui/select";
import {
  addCaseNote, createPolicy, createProofRun, getAutomationSettings, getBackendAudit,
  getBackendHealth, getCases, getCustomerMemory, getCaseConversation, getCurrentUser,
  getEvaluationGate, getEvaluationSummary, getIntegrations, getJobs, getPolicies, getProofRuns,
  recordCaseAction, recordCaseFeedback, recordCaseRoute, recordSensitiveReveal, resolveCase, runGroqTriage,
  saveManualAssessment, setPolicyState, updateAutomationSettings, updateCaseAssignment,
  verifyPaystackTransaction
} from "./api";
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
  { id: "proof", label: "Historical evaluation", icon: ClipboardCheck },
  { id: "audit", label: "Audit trail", icon: Activity },
  { id: "team", label: "Team coverage", icon: Users },
  { id: "settings", label: "Automation", icon: Settings }
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
const intentOptions = ["Transfer pending", "Payment failed", "Duplicate debit", "Fraud report", "Delivery delayed", "Delivery missing", "Delivery change", "Account access", "Account verification", "Refund pending", "General enquiry"];
const urgencyOptions = ["low", "medium", "high", "critical"];

const riskyIntents = new Set(["Fraud report", "Duplicate debit", "Payment failed", "Transfer pending", "Account access"]);
const riskyRoutes = new Set(["Fraud", "Transfers", "Billing", "Account Support", "Compliance"]);

function automationDecision(ticket, automation, governance = {}) {
  if (!isProcessed(ticket)) return { state: "pending", reason: "Classification pending." };
  if (!ticket.policyCitations?.length) return { state: "mandatory", reason: "Human review required: no approved policy matched." };
  if (!automation.enabled) return { state: "mandatory", reason: "Human review required: auto-approval is off." };
  if (ticket.escalated || ticket.escalationReason) return { state: "mandatory", reason: ticket.escalationReason ? `Human review required: ${ticket.escalationReason}` : "Human review required: a safety guardrail was triggered." };
  if (riskyIntents.has(ticket.intent) || riskyRoutes.has(ticket.route)) return { state: "mandatory", reason: "Human review required: this case involves security or financial risk." };
  if (ticket.entities?.transactionId && !ticket.verifiedTransaction) return { state: "mandatory", reason: "Human review required: transaction verification is unavailable." };
  if (["please provide", "kindly provide", "could you share", "send us your"].some((phrase) => ticket.responseDraft?.toLowerCase().includes(phrase))) return { state: "mandatory", reason: "Human review required: customer information is incomplete." };
  const delivery = ticket.channel === "email" ? governance.integrations?.email : governance.integrations?.whatsapp;
  if (!delivery?.configured || governance.integrations?.mode !== "live") return { state: "mandatory", reason: "Human review required: customer delivery is not connected." };
  if (Math.round(ticket.confidence * 100) < automation.auto_approve_threshold) return { state: "mandatory", reason: `Human review required: confidence is below ${automation.auto_approve_threshold}%.` };
  return { state: "auto", reason: "Eligible for auto-approval under the active safety policy." };
}

function policyState(ticket, automation, governance) {
  return automationDecision(ticket, automation, governance).state;
}

function operationalState(ticket, automation, governance) {
  if (!isProcessed(ticket)) return "pending";
  const lifecycle = ticket.lifecycle?.state;
  if (lifecycle === "resolved") return "Resolved";
  if (["sent", "delivered", "replied"].includes(lifecycle)) return "Waiting on customer";
  if (ticket.escalated || lifecycle === "review_required") return "Escalated";
  if (ticket.lifecycle?.assigned_to || ticket.assignee) return "Assigned";
  if (policyState(ticket, automation, governance) === "auto" || ticket.status === "Auto-approved") return "Auto-approved";
  return "Needs review";
}

function slaState(ticket) {
  const target = { critical: 24, high: 48, medium: 120, low: 240 }[ticket.urgency] || 120;
  const remaining = target - ticket.minutesAgo;
  if (["Approved", "Auto-approved"].includes(ticket.status)) return null;
  if (remaining <= 0) return { label: `${Math.abs(remaining)}m overdue`, overdue: true };
  if (remaining <= Math.max(12, target * .2)) return { label: `${remaining}m to SLA`, overdue: false };
  return null;
}

function lowRisk(ticket, automation, governance) {
  return policyState(ticket, automation, governance) === "auto";
}

function maskSensitive(value = "") {
  return String(value)
    .replace(/\b(\d{6})(\d{4})\b/g, "••••$2")
    .replace(/\b([A-Z]{2,5}-?\d{2,})(\d{4})\b/gi, (_, prefix, last4) => `${prefix.slice(0, 3)}•••${last4}`);
}

function formatDate(value) {
  return new Intl.DateTimeFormat("en-NG", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)).replace(",", "");
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

function Rail({ activeView, onView, open, onClose, user }) {
  const displayName = user?.display_name || "Ada Okafor";
  const role = (user?.role || "support_manager").replaceAll("_", " ");
  const initials = displayName.split(" ").slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  return (
    <aside className={cn("fixed inset-y-0 left-0 z-40 flex w-[232px] flex-col border-r border-white/10 bg-shell px-3 py-4 text-paper transition-transform lg:translate-x-0", open ? "translate-x-0 shadow-precision" : "-translate-x-full")} aria-label="Main navigation">
      <button onClick={onClose} className="absolute right-2 top-2 rounded-[6px] p-2 text-paper/60 hover:bg-white/10 hover:text-paper lg:hidden" aria-label="Close navigation"><X className="size-4" /></button>
      <div className="flex h-12 items-center gap-3 px-2" aria-label="Kora"><span className="grid size-9 place-items-center rounded-[8px] bg-accent text-xs font-semibold text-accent-ink">KR</span><span><strong className="block text-[14px] font-semibold tracking-[-0.03em]">Kora</strong><small className="mt-1 block text-[10px] font-medium text-paper/45">Support operations</small></span></div>
      <TooltipProvider>
        <nav className="mt-8 flex flex-1 flex-col gap-1.5">
          {navItems.map(({ id, label, icon: Icon }) => (
            <Tooltip key={id} label={label}>
              <button onClick={() => { onView(id); onClose(); }} aria-label={label} aria-current={activeView === id ? "page" : undefined} className={cn("grid h-11 w-full grid-cols-[18px_minmax(0,1fr)] items-center gap-3 rounded-[7px] border px-3 text-left text-[12px] font-semibold transition-[background-color,color,border-color,transform]", activeView === id ? "border-accent bg-accent text-accent-ink" : "border-transparent text-paper/58 hover:translate-x-0.5 hover:bg-white/[.07] hover:text-paper")}>
                <Icon className="size-[16px] justify-self-center" /><span className="whitespace-nowrap leading-none">{label}</span>
              </button>
            </Tooltip>
          ))}
        </nav>
        <div className="border-t border-white/10 pt-3">
          <button onClick={() => onView("settings")} className="flex h-14 w-full items-center gap-3 rounded-[7px] px-2 text-left hover:bg-white/[.07]"><span className="grid size-9 place-items-center rounded-full bg-accent text-[10px] font-extrabold text-accent-ink">{initials}</span><span><strong className="block text-[11px] font-extrabold">{displayName}</strong><small className="mt-1 block capitalize text-[9px] font-semibold text-paper/40">{role}</small></span></button>
        </div>
      </TooltipProvider>
    </aside>
  );
}

function Header({ activeView, onMenu, backend, tickets, onOpenTicket, onView, onLogout, user }) {
  const [readNotificationIds, setReadNotificationIds] = useState([]);
  const displayName = user?.display_name || "Ada Okafor";
  const role = (user?.role || "support_manager").replaceAll("_", " ");
  const initials = displayName.split(" ").slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  const titles = { queue: "Queue", insights: "Insights", proof: "Historical evaluation", audit: "Decision audit", team: "Team coverage", settings: "Confidence automation" };
  const engineLabel = backend.state === "checking"
    ? "Checking API"
    : backend.configured
      ? "AI service available"
      : backend.state === "online" ? "AI setup required" : "AI service unavailable";
  const notifications = [...tickets]
    .sort((a, b) => Number(b.escalated) - Number(a.escalated) || urgencyOrder[a.urgency] - urgencyOrder[b.urgency] || a.minutesAgo - b.minutesAgo)
    .slice(0, 4)
    .map((ticket) => ({
      ...ticket,
      notificationTitle: ticket.escalated ? "Human review required" : isProcessed(ticket) ? `${intentShort[ticket.intent] || ticket.intent} triaged` : "Live triage pending"
    }));
  const unreadCount = notifications.filter((notification) => !readNotificationIds.includes(notification.id)).length;
  const reviewCount = tickets.filter((ticket) => ticket.escalated).length;
  const slaRiskCount = tickets.filter((ticket) => slaState(ticket)).length;
  return (
    <header className="flex h-[72px] shrink-0 items-center justify-between border-b border-line bg-paper px-4 sm:px-7 lg:px-8">
      <div className="flex items-center gap-3">
        <Button variant="outline" size="icon" className="lg:hidden" onClick={onMenu} aria-label="Open navigation"><Menu className="size-4" /></Button>
        <h1 className="text-[20px] font-semibold tracking-[-0.035em]">{titles[activeView]}</h1>
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
          <DropdownMenuContent align="end" className="notification-popover w-[min(410px,calc(100vw-20px))] p-0" sideOffset={9}>
            <div className="notification-header">
              <div className="flex items-center gap-3">
                <span className="grid size-9 place-items-center rounded-[8px] bg-ink text-paper"><BellRing className="size-4" /></span>
                <div><p className="text-[14px] font-extrabold tracking-[-0.025em]">Support inbox</p><p className="mt-1 text-[9px] font-semibold text-ink-faint">{unreadCount ? `${unreadCount} unread updates` : "No unread updates"}</p></div>
              </div>
              <button type="button" onClick={() => setReadNotificationIds(notifications.map((notification) => notification.id))} disabled={!unreadCount} className="notification-mark-read"><CheckCheck className="size-3.5" />Mark read</button>
            </div>
            <div className="notification-summary" aria-label="Notification summary">
              <span><UserRoundCheck className="size-3.5" /><strong>{reviewCount}</strong> reviews waiting</span>
              <span><Timer className="size-3.5" /><strong>{slaRiskCount}</strong> SLA risks</span>
            </div>
            <div className="max-h-[430px] overflow-y-auto">
              {notifications.length ? notifications.map((notification) => {
                const isRead = readNotificationIds.includes(notification.id);
                const sla = slaState(notification);
                return (
                  <DropdownMenuItem
                    key={notification.id}
                    onSelect={() => { setReadNotificationIds((ids) => ids.includes(notification.id) ? ids : [...ids, notification.id]); onOpenTicket(notification.id); }}
                    className={cn("notification-item", isRead && "notification-item-read")}
                  >
                    <span className={cn("notification-symbol", notification.escalated ? "notification-symbol-review" : sla ? "notification-symbol-sla" : "notification-symbol-update")}>
                      {notification.escalated ? <UserRoundCheck className="size-4" /> : sla ? <Timer className="size-4" /> : isProcessed(notification) ? <CheckCircle2 className="size-4" /> : <Bell className="size-4" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-start justify-between gap-3">
                        <span className="min-w-0"><strong className="block truncate text-[11px] font-extrabold">{notification.notificationTitle}</strong><span className="mt-1 block truncate text-[9px] font-semibold text-ink-faint">{notification.customer.name} · {notification.id}</span></span>
                        {!isRead && <span className="mt-1 size-2 shrink-0 rounded-full bg-accent-strong" aria-label="Unread" />}
                      </span>
                      <span className="mt-2 block text-[12px] leading-[1.5] text-ink-muted">{intentShort[notification.intent] || notification.intent} · <span className="capitalize">{notification.urgency} urgency</span></span>
                      <span className="mt-2.5 flex items-center gap-2 text-[12px] font-semibold text-ink-faint">
                        <span>{sla ? `SLA: ${sla.label}` : `Waiting ${formatRelative(notification.minutesAgo)}`}</span><span className="ml-auto">{operationalState(notification, { enabled: false })}</span>
                      </span>
                    </span>
                  </DropdownMenuItem>
                );
              }) : (
                <div className="grid min-h-48 place-items-center px-8 text-center"><div><Bell className="mx-auto size-5 text-ink-faint" /><strong className="mt-3 block text-[12px]">Nothing needs attention</strong><p className="mt-1 text-[9px] leading-4 text-ink-faint">New triage decisions and human reviews will appear here.</p></div></div>
              )}
            </div>
            <div className="border-t border-line bg-muted-surface/55 p-2"><DropdownMenuItem onSelect={() => onView("queue")} className="h-10 justify-center gap-2 bg-paper font-bold">Open full support queue<ArrowRight className="size-3.5" /></DropdownMenuItem></div>
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" className="px-2.5 sm:px-3" aria-label="Open profile menu">
              <span className="grid size-5 place-items-center rounded-full bg-accent text-[8px] font-extrabold text-accent-ink sm:hidden">{initials}</span>
              <CircleUserRound className="hidden size-4 sm:block" /><span className="hidden sm:inline">{displayName}</span><ChevronDown className="size-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56" sideOffset={8}>
            <div className="px-2.5 py-2.5"><p className="text-[11px] font-extrabold">{displayName}</p><p className="mt-1 capitalize text-[9px] font-semibold text-ink-faint">{role}</p></div>
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

function MetricsStrip({ tickets, automation, governance, onFilter }) {
  const open = tickets.filter((ticket) => !["resolved", "sent", "delivered"].includes(ticket.lifecycle?.state));
  const metrics = [
    { key: "review", label: "Needs human review", value: open.filter((ticket) => policyState(ticket, automation, governance) === "mandatory").length, meta: `Open conversations, right now` },
    { key: "sla", label: "SLA breached or at risk", value: open.filter((ticket) => slaState(ticket)).length, meta: "Open conversations, current SLA clock" },
    { key: "unassigned", label: "Unassigned conversations", value: open.filter((ticket) => !ticket.lifecycle?.assigned_to && !ticket.assignee && ticket.status !== "Assigned").length, meta: `Of ${open.length} open conversations` }
  ];
  return (
    <section className="operational-priorities" aria-label="Queue priorities">
      {metrics.map((item) => (
        <button key={item.label} type="button" className="priority-metric" onClick={() => onFilter(item.key)} aria-label={`${item.label}: ${item.value}. ${item.meta}`}>
          <span><strong>{item.value}</strong><span>{item.label}</span></span><small>{item.meta}</small><ArrowRight className="size-4" />
        </button>
      ))}
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

function TicketRow({ ticket, selected, checked, onSelect, onCheck, automation = { enabled: false, auto_approve_threshold: 95, mandatory_review_threshold: 70 }, governance }) {
  const sla = slaState(ticket);
  const state = operationalState(ticket, automation, governance);
  const stateVariant = state === "Needs review" || state === "Escalated" ? "strong" : state === "Auto-approved" ? "accent" : "neutral";
  return (
    <div data-ticket={ticket.id} className={cn("ticket-row group", selected && "bg-selected")}>
      <button type="button" onClick={() => onCheck(ticket.id)} aria-label={`${checked ? "Deselect" : "Select"} ${ticket.id}`} aria-pressed={checked} className="ticket-select-control">{checked ? <SquareCheckBig className="size-5 text-ink" /> : <Square className="size-5" />}</button>
      <button type="button" onClick={() => onSelect(ticket.id)} className="min-w-0 flex-1 text-left" aria-pressed={selected}>
        <span className="flex items-center justify-between gap-3"><strong className="truncate text-[14px] font-semibold tracking-[-0.02em]">{ticket.customer.name}</strong><time className="text-[12px] font-semibold text-ink-faint">Waiting {formatRelative(ticket.minutesAgo)}</time></span>
        <span className="mt-2 flex flex-wrap items-center gap-2"><span className="text-[13px] font-semibold">{intentShort[ticket.intent] || ticket.intent}</span><Badge variant={stateVariant}>{state}</Badge></span>
        <span className="mt-2.5 line-clamp-2 text-[14px] leading-[1.55] text-ink-muted">{maskSensitive(ticket.message)}</span>
        {sla && <span className={cn("mt-3 inline-flex items-center gap-1.5 text-[12px] font-semibold", sla.overdue ? "text-red-700" : "text-amber-700")}><Timer className="size-3.5" />{sla.overdue ? "SLA breached" : "SLA at risk"}: {sla.label}</span>}
        <details className="ticket-secondary mt-2" onClick={(event) => event.stopPropagation()}><summary>More details</summary><span>{ticket.id} · <span className="capitalize">{ticket.channel}</span> · {ticket.route}{isProcessed(ticket) ? ` · ${Math.round(ticket.confidence * 100)}% confidence` : ""}{ticket.memoryUsed ? " · Customer history used" : ""}</span></details>
      </button>
    </div>
  );
}

function QueuePane({ tickets, selectedId, onSelect, loading, query, onQuery, filters, onFilters, selectedIds = [], onToggle, onSelectAll, onBulkApprove, onBulkRoute, bulkLoading, automation = { enabled: false, auto_approve_threshold: 95, mandatory_review_threshold: 70 }, governance, scrollRef }) {
  const [filtersOpen, setFiltersOpen] = useState(false);
  const reset = () => { onQuery(""); onFilters({ review: false, high: false, sla: false, unassigned: false, channel: "all", urgency: "all", team: "all" }); };
  const allSelected = tickets.length > 0 && tickets.every((ticket) => selectedIds.includes(ticket.id));
  const selectedLowRisk = tickets.filter((ticket) => selectedIds.includes(ticket.id) && lowRisk(ticket, automation, governance)).length;
  const chip = (label, value, options, key) => (
    <Select value={value} onValueChange={(nextValue) => onFilters({ ...filters, [key]: nextValue })}>
      <SelectTrigger aria-label={`Filter by ${label.toLowerCase()}`} className={cn("h-9 min-w-[118px] bg-paper", value !== "all" && "border-ink bg-selected")}>
        <span className="text-[9px] font-bold uppercase tracking-[0.06em] text-ink-faint">{label}</span>
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="start">
        {options.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
      </SelectContent>
    </Select>
  );
  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-[10px] border border-line bg-paper" aria-labelledby="queue-heading">
      <div className="border-b border-line p-4 sm:p-5">
        <div className="flex items-center justify-between"><h2 id="queue-heading" className="text-[18px] font-semibold tracking-[-0.035em]">Open conversations <span className="text-ink-faint">{tickets.length}</span></h2>
          <Button variant="outline" onClick={() => setFiltersOpen((value) => !value)} aria-expanded={filtersOpen} className="queue-filter-button"><Filter className="size-4" />Filters</Button>
        </div>
        <label className="mt-4 flex h-11 items-center gap-2 rounded-[7px] border border-line-strong bg-canvas px-3 focus-within:border-ink focus-within:ring-2 focus-within:ring-ring"><Search className="size-4 text-ink-faint" /><span className="sr-only">Search tickets</span><input value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Search name, case or message" className="min-w-0 flex-1 bg-transparent text-[12px] font-semibold outline-none placeholder:text-ink-faint" /></label>
        <div className={cn("queue-filter-fields mt-3 flex-wrap gap-2", filtersOpen ? "flex" : "hidden md:flex")} aria-label="Ticket filters">
          {chip("Channel", filters.channel, [{ value: "all", label: "All channels" }, { value: "whatsapp", label: "WhatsApp" }, { value: "email", label: "Email" }], "channel")}
          {chip("Urgency", filters.urgency, [{ value: "all", label: "All urgency" }, ...["critical", "high", "medium", "low"].map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) }))], "urgency")}
          {chip("Team", filters.team, [{ value: "all", label: "All teams" }, ...teamOptions.map((value) => ({ value, label: value }))], "team")}
          {(query || filters.review || filters.high || filters.sla || filters.unassigned || filters.channel !== "all" || filters.urgency !== "all" || filters.team !== "all") && <Button variant="ghost" size="sm" onClick={reset}><X className="size-3" />Clear</Button>}
        </div>
        <div className="active-filter-chips md:hidden">{filters.review && <button onClick={() => onFilters({ ...filters, review: false })}>Needs review <X /></button>}{filters.sla && <button onClick={() => onFilters({ ...filters, sla: false })}>SLA risk <X /></button>}{filters.unassigned && <button onClick={() => onFilters({ ...filters, unassigned: false })}>Unassigned <X /></button>}</div>
      </div>
      <div className="flex min-h-10 items-center justify-between border-b border-line bg-muted-surface px-4 py-2">
        <button type="button" onClick={() => onSelectAll(tickets.map((ticket) => ticket.id), !allSelected)} className="flex items-center gap-2 text-[9px] font-extrabold uppercase tracking-[0.08em] text-ink-muted">{allSelected ? <SquareCheckBig className="size-4 text-ink" /> : <Square className="size-4" />}{selectedIds.length ? `${selectedIds.length} selected` : "Select all"}</button>
        {selectedIds.length > 0 && <div className="flex items-center gap-1.5"><Button size="sm" variant="outline" className="h-7 px-2 text-[9px]" disabled={!selectedLowRisk || bulkLoading} onClick={onBulkApprove}><Check className="size-3" />Approve {selectedLowRisk || ""}</Button><DropdownMenu><DropdownMenuTrigger asChild><Button size="sm" className="h-7 px-2 text-[9px]" disabled={bulkLoading}><Route className="size-3" />Route<ChevronDown className="size-3" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">{teamOptions.map((team) => <DropdownMenuItem key={team} onSelect={() => onBulkRoute(team)}>{team}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu></div>}
      </div>
      <div className="queue-scroll" ref={scrollRef}>{loading ? <QueueLoading /> : tickets.length ? tickets.map((ticket) => <TicketRow key={ticket.id} ticket={ticket} selected={selectedId === ticket.id} checked={selectedIds.includes(ticket.id)} onSelect={onSelect} onCheck={onToggle} automation={automation} governance={governance} />) : <EmptyQueue onReset={reset} />}</div>
    </section>
  );
}

function EntityTag({ label, value }) {
  return <div className="rounded-[6px] bg-muted-surface px-3 py-2.5"><span className="block text-[12px] text-ink-faint">{label}</span><strong className="mt-1 block text-[13px] font-semibold">{maskSensitive(value)}</strong></div>;
}

function TicketDetail({ ticket, onApprove, onEscalate, onRunAI, onFeedback, onResolve, onAssign, onAddNote, onVerifyTransaction, onManualAssessment, aiLoading, actionLoading, backend, automation = { enabled: true, auto_approve_threshold: 95, mandatory_review_threshold: 70 }, memoryItems = [], memoryLoading = false, conversation = [], notes = [], conversationLoading = false, currentUser }) {
  const [draft, setDraft] = useState(ticket.response);
  const [correction, setCorrection] = useState({ intent: "", urgency: "", route: "", reason: "" });
  const [noteDraft, setNoteDraft] = useState("");
  useEffect(() => { setDraft(ticket.response); setCorrection({ intent: "", urgency: "", route: "", reason: "" }); setNoteDraft(""); }, [ticket.id, ticket.response]);
  const entities = Object.entries(ticket.entities).filter(([, value]) => value);
  const labels = { amount: "Amount", transactionId: "Transaction ID", orderId: "Order ID", account: "Account", card: "Card" };
  const sla = slaState(ticket);
  const policy = policyState(ticket, automation);

  return (
    <article className="detail-scroll rounded-[10px] border border-line bg-canvas" aria-labelledby="ticket-title">
      <header className="sticky top-0 z-10 flex min-h-[82px] items-center justify-between gap-4 border-b border-line bg-canvas px-5 sm:px-7">
        <div className="min-w-0"><div className="flex items-center gap-2"><span className="section-label">{ticket.id}</span><span className="text-ink-faint">/</span><span className="section-label">{ticket.channel}</span></div><h2 id="ticket-title" className="mt-1 truncate text-[20px] font-extrabold tracking-[-0.045em]">{ticket.customer.name}</h2></div>
        <div className="flex flex-wrap items-center justify-end gap-2">{ticket.lifecycle?.assigned_to ? <Badge variant="outline" shape="pill"><UserRoundCheck className="size-3" />{ticket.lifecycle.assigned_to}</Badge> : <Button size="sm" variant="outline" onClick={() => onAssign(ticket.id, "me", null)}><UserPlus className="size-3.5" />Claim</Button>}{ticket.lifecycle?.state && <Badge variant="neutral" shape="pill"><span className="size-1.5 rounded-full bg-current" />{ticket.lifecycle.state.replaceAll("_", " ")}</Badge>}{sla && <Badge variant={sla.overdue ? "strong" : "outline"} shape="pill"><Timer className="size-3" />{sla.label}</Badge>}<UrgencyBadge urgency={ticket.urgency} /><DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline" size="icon" aria-label="More case actions"><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => navigator.clipboard?.writeText(`${window.location.origin}/app?case=${ticket.id}`)}>Copy case link</DropdownMenuItem>{ticket.lifecycle?.assigned_to && <DropdownMenuItem onSelect={() => onAssign(ticket.id, null, ticket.lifecycle.assigned_to)}>Release ownership</DropdownMenuItem>}<DropdownMenuItem>Mark as duplicate</DropdownMenuItem></DropdownMenuContent></DropdownMenu></div>
      </header>

      <div className="detail-content">
        <section className="rounded-[8px] border border-line bg-paper p-5 sm:p-7" aria-labelledby="customer-message-title">
          <div className="flex items-center justify-between gap-4"><div><p className="section-label">Raw customer input</p><h3 id="customer-message-title" className="mt-1 text-[14px] font-extrabold">Customer message</h3></div><span className="flex items-center gap-1.5 text-[9px] font-bold text-ink-faint"><Clock3 className="size-3" />{ticket.receivedAt}</span></div>
          {ticket.subject && <p className="mt-5 text-[11px] font-extrabold">{ticket.subject}</p>}
          <blockquote className="mt-4 max-w-[70ch] text-[15px] font-medium leading-7 tracking-[-0.015em] text-ink-muted">“{ticket.message}”</blockquote>
          <div className="mt-6 flex flex-wrap gap-2">{entities.map(([key, value]) => <EntityTag key={key} label={labels[key]} value={value} />)}</div>
          {(conversationLoading || conversation.length > 0) && <details className="mt-6 border-t border-line pt-4"><summary className="flex cursor-pointer list-none items-center justify-between"><span className="flex items-center gap-2 text-[9px] font-extrabold uppercase tracking-[0.09em]"><MessagesSquare className="size-3.5" />Conversation history</span><span className="flex items-center gap-2 text-[9px] text-ink-faint">{conversation.length} messages<ChevronDown className="size-3" /></span></summary><div className="mt-4 space-y-2">{conversationLoading ? <Skeleton className="h-20 w-full" /> : conversation.map((message) => <div key={message.id} className={cn("max-w-[88%] border p-3", message.direction === "outbound" ? "ml-auto border-ink bg-ink text-paper" : "border-line-strong bg-muted-surface")}><div className="flex items-center justify-between gap-4 text-[8px] font-bold uppercase tracking-[0.08em] opacity-70"><span>{message.direction === "outbound" ? "Kora response" : "Customer"}</span><span>{message.delivery_status}</span></div><p className="mt-2 text-[10px] leading-5">{message.body}</p></div>)}</div></details>}
        </section>

        <div className="decision-columns grid xl:grid-cols-[minmax(0,1.08fr)_minmax(300px,.92fr)]">
          <section className="ai-panel rounded-[8px] border border-line p-5 sm:p-7" aria-labelledby="ai-reasoning-title">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2"><span className="grid size-7 place-items-center rounded-[6px] bg-ink text-paper"><Bot className="size-3.5" /></span><p className="section-label !text-ink">AI assessment</p></div>
                <h3 id="ai-reasoning-title" className="mt-3 text-[18px] font-extrabold tracking-[-0.035em]">Decision and reasoning</h3>
                <p className="mt-1 max-w-md text-[10px] leading-5 text-ink-muted">Structured classification, policy route, and evidence for agent review.</p>
              </div>
              {isProcessed(ticket) ? <Badge variant={ticket.confidence < .8 ? "strong" : "accent"} shape="pill">{Math.round(ticket.confidence * 100)}% confidence</Badge> : <Badge variant="outline" shape="pill">Awaiting Groq</Badge>}
            </div>
            <div className="mt-5 rounded-[8px] border border-line-strong bg-paper p-4">
              <div className="flex items-end justify-between gap-4">
                <div><span className="block text-[9px] font-bold uppercase tracking-[0.07em] text-ink-faint">Classification certainty</span><strong className="mt-1 block text-[24px] font-extrabold tracking-[-0.05em]">{isProcessed(ticket) ? `${Math.round(ticket.confidence * 100)}%` : "Pending"}</strong></div>
                <span className="max-w-[150px] text-right text-[9px] leading-4 text-ink-faint">Mandatory review below {automation.mandatory_review_threshold}%</span>
              </div>
              <div className="confidence-track mt-4" aria-label={`Confidence ${Math.round(ticket.confidence * 100)} percent`}>
                <span className="confidence-fill" style={{ width: `${Math.max(0, Math.min(100, ticket.confidence * 100))}%` }} />
                <i style={{ left: `${automation.mandatory_review_threshold}%` }} />
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-[7px] border border-line bg-paper/70 px-3 py-2.5">
              <span className="text-[9px] font-bold text-ink-muted">{ticket.source === "groq" ? `Live result · ${ticket.model}` : ticket.source === "seeded" ? `Model snapshot · ${ticket.model}` : "No local classification fallback"}</span>
              {backend.configured && ticket.source !== "groq" && <Button onClick={() => onRunAI(ticket)} disabled={aiLoading} variant="outline" size="sm">{aiLoading ? <LoaderCircle className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}{aiLoading ? "Running Groq" : "Refresh with live AI"}</Button>}
              {ticket.source === "groq" && <Badge variant="accent" shape="pill"><Check className="size-3" />Groq verified</Badge>}
            </div>
            {!backend.configured && <p className="mt-3 text-[9px] leading-4 text-ink-faint">{backend.state === "online" ? "Live classification is blocked until GROQ_API_KEY is configured in backend/.env." : "The backend API is offline. Start it to enable live classification."}</p>}
            <dl className="decision-summary mt-5">
              {[['Intent', ticket.intent], ['Urgency', ticket.urgency], ['Sentiment', ticket.sentiment], ['Recommended route', ticket.route]].map(([label, value], index) => <div key={label}><dt>{label}</dt><dd><span className={cn("status-shape", index === 1 && ["critical", "high"].includes(ticket.urgency) && "status-shape-alert")} />{value}</dd></div>)}
            </dl>
            {isProcessed(ticket) && (
              <details className="mt-5 border border-line-strong bg-paper">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3.5">
                  <span className="flex items-center gap-2"><Wrench className="size-3.5" /><strong className="text-[9px] font-extrabold uppercase tracking-[0.09em]">Correct the AI decision</strong></span>
                  <ChevronDown className="size-3.5" />
                </summary>
                <div className="grid gap-4 border-t border-line p-4 sm:grid-cols-2">
                  <label className="grid gap-2 text-[10px] font-bold">
                    Intent
                    <Select value={correction.intent || "__keep__"} onValueChange={(value) => setCorrection({ ...correction, intent: value === "__keep__" ? "" : value })}>
                      <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="__keep__">Keep {ticket.intent}</SelectItem>{intentOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
                    </Select>
                  </label>
                  <label className="grid gap-2 text-[10px] font-bold">
                    Urgency
                    <Select value={correction.urgency || "__keep__"} onValueChange={(value) => setCorrection({ ...correction, urgency: value === "__keep__" ? "" : value })}>
                      <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="__keep__">Keep {ticket.urgency}</SelectItem>{urgencyOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
                    </Select>
                  </label>
                  <label className="grid gap-2 text-[10px] font-bold">
                    Route
                    <Select value={correction.route || "__keep__"} onValueChange={(value) => setCorrection({ ...correction, route: value === "__keep__" ? "" : value })}>
                      <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="__keep__">Keep {ticket.route}</SelectItem>{teamOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
                    </Select>
                  </label>
                  <label className="grid gap-2 text-[10px] font-bold">
                    Reason
                    <input value={correction.reason} onChange={(event) => setCorrection({ ...correction, reason: event.target.value })} placeholder="Why was it corrected?" className="h-10 w-full rounded-[7px] border border-line-strong bg-paper px-3 text-[11px] outline-none transition-colors hover:border-ink/55 focus:border-ink focus:ring-2 focus:ring-ring" />
                  </label>
                  <Button size="sm" variant="outline" className="sm:col-span-2 sm:justify-self-start" disabled={actionLoading || (!correction.intent && !correction.urgency && !correction.route)} onClick={() => onFeedback(ticket.id, correction)}><ShieldCheck className="size-3.5" />Save correction</Button>
                </div>
              </details>
            )}
            <details open className="mt-5 border border-line-strong bg-paper">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3"><span className="flex items-center gap-2"><Database className="size-3.5" /><strong className="text-[9px] font-extrabold uppercase tracking-[0.09em]">SQLite customer memory</strong></span><span className="flex items-center gap-2">{ticket.memoryUsed && <Badge variant="outline" shape="pill">Reused</Badge>}<ChevronDown className="size-3" /></span></summary>
              <div className="border-t border-line px-4 py-3">{memoryLoading ? <div className="space-y-2"><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /></div> : memoryItems.length ? <div className="space-y-2">{memoryItems.slice(0, 2).map((memory) => <div key={`${memory.case_id}-${memory.created_at}`} className="bg-muted-surface p-3"><div className="flex items-center justify-between gap-3"><strong className="text-[9px] font-extrabold">{memory.case_id}</strong><time className="text-[8px] text-ink-faint">{new Date(memory.created_at).toLocaleDateString()}</time></div><p className="mt-1 text-[9px] leading-4 text-ink-muted">{memory.summary}</p></div>)}</div> : <p className="text-[10px] leading-5 text-ink-muted">No stored case memory yet. Provided context: {ticket.customer.previousContext}</p>}</div>
            </details>
            <div className="mt-6"><p className="section-label !text-ink">Evidence used</p>{ticket.evidence.length ? <ol className="mt-3 space-y-3">{ticket.evidence.map((item, index) => <li key={item} className="flex items-start gap-3 text-[10px] font-semibold leading-5 text-ink-muted"><span className="grid size-5 shrink-0 place-items-center border border-ink text-[8px] font-extrabold text-ink">0{index + 1}</span>{item}</li>)}</ol> : <p className="mt-3 text-[10px] text-ink-faint">Evidence will appear after live Groq classification.</p>}</div>
            <div className="mt-6 border border-line-strong bg-paper">
              <div className="flex items-center justify-between border-b border-line px-4 py-3"><span className="flex items-center gap-2"><BookOpenCheck className="size-3.5" /><strong className="text-[9px] font-extrabold uppercase tracking-[0.09em]">Approved policy sources</strong></span><Badge variant={ticket.policyCitations?.length ? "accent" : "outline"} shape="pill">{ticket.policyCitations?.length || 0} matched</Badge></div>
              <div className="p-4">{ticket.policyCitations?.length ? <div className="space-y-3">{ticket.policyCitations.map((citation) => <div key={citation.id} className="bg-muted-surface p-3"><div className="flex items-center justify-between gap-3"><strong className="text-[10px]">{citation.title}</strong><span className="text-[8px] font-bold text-ink-faint">v{citation.version}</span></div><p className="mt-2 line-clamp-3 text-[9px] leading-4 text-ink-muted">{citation.excerpt}</p></div>)}</div> : <p className="text-[9px] leading-4 text-ink-muted">No approved workspace policy matched this message. The draft must remain human-reviewed.</p>}</div>
            </div>
            {ticket.entities?.transactionId && <div className="mt-5 border border-line-strong bg-paper p-4"><div className="flex items-start justify-between gap-4"><div><span className="flex items-center gap-2 text-[9px] font-extrabold uppercase tracking-[0.09em]"><CreditCard className="size-3.5" />Verified transaction status</span><p className="mt-2 text-[9px] leading-4 text-ink-muted">{ticket.verifiedTransaction ? `${ticket.verifiedTransaction.provider} reports ${ticket.verifiedTransaction.status}. This lookup was read-only.` : "Check the extracted reference against Paystack without moving money."}</p></div><Button size="sm" variant="outline" disabled={actionLoading || !backend.paystack?.configured} onClick={() => onVerifyTransaction(ticket)}>{actionLoading ? <LoaderCircle className="size-3.5 animate-spin" /> : <ShieldCheck className="size-3.5" />}{ticket.verifiedTransaction ? "Verify again" : "Verify"}</Button></div>{!backend.paystack?.configured && <p className="mt-3 text-[8px] font-bold text-ink-faint">Configure PAYSTACK_SECRET_KEY to enable this read-only action.</p>}</div>}
            {ticket.escalationReason && <div className="mt-6 flex gap-3 border border-ink bg-ink p-4 text-paper"><ShieldAlert className="mt-0.5 size-4 shrink-0 text-accent" /><div><strong className="text-[10px] font-extrabold uppercase tracking-[0.08em]">Escalation rule triggered</strong><p className="mt-1 text-[10px] leading-5 text-paper/70">{ticket.escalationReason}</p></div></div>}
          </section>

          <section className="human-panel rounded-[8px] border border-line p-5 sm:p-7" aria-labelledby="human-checkpoint-title">
            <div className="flex items-center gap-2"><UserRoundCheck className="size-4" /><p className="section-label !text-ink">Human checkpoint</p></div>
            <h3 id="human-checkpoint-title" className="mt-2 text-[16px] font-extrabold tracking-[-0.03em]">Review before action</h3>
            <p className="mt-2 text-[11px] leading-5 text-ink-muted">{policy === "auto" ? `This response qualifies for auto-approval at the ${automation.auto_approve_threshold}% threshold.` : policy === "mandatory" ? "Policy requires a human decision before this response can be sent." : "The AI prepared this response. An agent owns the final decision and can edit every word."}</p>
            {!isProcessed(ticket) && !backend.configured && <div className="mt-5 grid gap-3 sm:grid-cols-3"><label className="grid gap-2 text-[9px] font-bold">Intent<Select value={correction.intent || undefined} onValueChange={(value) => setCorrection({ ...correction, intent: value })}><SelectTrigger className="w-full"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{intentOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></label><label className="grid gap-2 text-[9px] font-bold">Urgency<Select value={correction.urgency || undefined} onValueChange={(value) => setCorrection({ ...correction, urgency: value })}><SelectTrigger className="w-full"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{urgencyOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></label><label className="grid gap-2 text-[9px] font-bold">Route<Select value={correction.route || undefined} onValueChange={(value) => setCorrection({ ...correction, route: value })}><SelectTrigger className="w-full"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{teamOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></label></div>}
            <label className="mt-6 block"><span className="mb-2 block text-[9px] font-extrabold uppercase tracking-[0.09em] text-ink-muted">Response draft</span><textarea value={draft} onChange={(event) => setDraft(event.target.value)} disabled={!isProcessed(ticket) && backend.configured} placeholder={!backend.configured ? "Write a human-owned response while AI is unavailable." : "A live Groq draft will appear here."} rows={10} className="w-full resize-none rounded-[8px] border border-line-strong bg-paper p-4 text-[12px] font-medium leading-6 outline-none placeholder:text-ink-faint focus:border-ink focus:ring-2 focus:ring-ring disabled:bg-muted-surface" /></label>
            <div className="mt-4 flex items-center justify-between text-[9px] font-semibold text-ink-faint"><span>{draft.length} characters</span><span>{ticket.customer.notes.some((note) => note.includes("Pidgin")) ? "Pidgin aware" : "English"}</span></div>
            <div className="mt-6 border-t border-line-strong pt-5">
              {!isProcessed(ticket) ? backend.configured ? <Button disabled className="w-full"><LoaderCircle className={cn("size-4", aiLoading && "animate-spin")} />{aiLoading ? "Running live triage" : "Live triage required"}</Button> : <Button disabled={actionLoading || !correction.intent || !correction.urgency || !correction.route || draft.trim().length < 2} onClick={() => onManualAssessment(ticket, { ...correction, response: draft })} className="w-full"><UserRoundCheck className="size-4" />Save manual assessment</Button> : ["sent", "delivered", "replied"].includes(ticket.lifecycle?.state) ? <Button disabled={actionLoading} onClick={() => onResolve(ticket.id)} className="w-full"><CheckCircle2 className="size-4" />Mark resolved</Button> : policy === "mandatory" ? <Button disabled={actionLoading} onClick={() => onEscalate(ticket.id, draft)} variant="default" className="w-full">{actionLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Users className="size-4" />}Assign to specialist</Button> : <div className="grid grid-cols-[auto_1fr] gap-2"><Button disabled={actionLoading} onClick={() => onEscalate(ticket.id, draft)} variant="outline" aria-label="Escalate to a person"><Users className="size-4" /></Button><Button disabled={actionLoading} onClick={() => onApprove(ticket.id, draft)} variant="accent">{actionLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Send className="size-4" />}Approve and send</Button></div>}
              <p className="mt-3 text-center text-[8px] font-bold uppercase tracking-[0.08em] text-ink-faint">No financial action is automated</p>
            </div>
            <div className="mt-6 border-t border-line pt-5">
              <div className="flex items-center justify-between"><div><p className="section-label">Private collaboration</p><h4 className="mt-1 text-[12px] font-extrabold">Internal notes</h4></div><Badge variant="neutral" shape="pill">{notes.length}</Badge></div>
              <div className="mt-4 space-y-2">{notes.slice(0, 3).map((note) => <div key={note.id} className="bg-muted-surface p-3"><div className="flex items-center justify-between gap-3"><strong className="text-[9px]">{note.actor}</strong><time className="text-[8px] text-ink-faint">{new Date(note.created_at).toLocaleString()}</time></div><p className="mt-2 text-[9px] leading-4 text-ink-muted">{note.body}</p></div>)}</div>
              <label className="mt-3 block"><span className="sr-only">Internal note</span><textarea value={noteDraft} onChange={(event) => setNoteDraft(event.target.value)} rows={3} placeholder={`Add a private note. Use @${currentUser?.display_name?.split(" ")[0] || "teammate"} to mention someone.`} className="w-full resize-none rounded-[7px] border border-line-strong bg-paper p-3 text-[10px] outline-none focus:border-ink focus:ring-2 focus:ring-ring" /></label>
              <Button size="sm" variant="outline" className="mt-2" disabled={!noteDraft.trim() || actionLoading} onClick={() => { const mentions = [...noteDraft.matchAll(/@([A-Za-z][\w.-]*)/g)].map((match) => match[1]); onAddNote(ticket.id, noteDraft, mentions); setNoteDraft(""); }}><MessageCircle className="size-3.5" />Add private note</Button>
            </div>
          </section>
        </div>
      </div>
    </article>
  );
}

function CaseDetail({ ticket, onApprove, onEscalate, onRunAI, onFeedback, onResolve, onAssign, onAddNote, onVerifyTransaction, onManualAssessment, onBack, onSensitiveReveal, aiLoading, actionLoading, backend, automation, governance, memoryItems = [], memoryLoading, conversation = [], notes = [], conversationLoading, currentUser }) {
  const [draft, setDraft] = useState(ticket.response || "");
  const [correction, setCorrection] = useState({ intent: "", urgency: "", route: "", reason: "" });
  const [noteDraft, setNoteDraft] = useState("");
  const [revealed, setRevealed] = useState(false);
  useEffect(() => { setDraft(ticket.response || ""); setCorrection({ intent: "", urgency: "", route: "", reason: "" }); setNoteDraft(""); setRevealed(false); }, [ticket.id, ticket.response]);
  const decision = automationDecision(ticket, automation, governance);
  const delivery = ticket.channel === "email" ? governance.integrations?.email : governance.integrations?.whatsapp;
  const canSend = governance.integrations?.mode === "live" && delivery?.configured;
  const sla = slaState(ticket);
  const entities = Object.entries(ticket.entities || {}).filter(([, value]) => value);
  const labels = { amount: "Amount", transactionId: "Transaction ID", orderId: "Order ID", account: "Account", card: "Card" };
  const reveal = () => { setRevealed(true); onSensitiveReveal?.(ticket); };
  return (
    <article className="detail-scroll case-workspace" aria-labelledby="ticket-title">
      <header className="case-header">
        <div className="flex min-w-0 items-center gap-3"><Button variant="ghost" size="icon" className="case-back-button" onClick={onBack} aria-label="Back to queue"><ArrowLeft className="size-4" /></Button><div className="min-w-0"><p className="case-kicker">{ticket.id} · <span className="capitalize">{ticket.channel}</span></p><h2 id="ticket-title">{ticket.customer.name}</h2></div></div>
        <div className="case-header-actions">{ticket.lifecycle?.assigned_to ? <Badge variant="outline"><UserRoundCheck className="size-3" />{ticket.lifecycle.assigned_to}</Badge> : <Button variant="outline" onClick={() => onAssign(ticket.id, "me", null)}><UserPlus className="size-4" />Claim case</Button>}{sla && <Badge variant={sla.overdue ? "strong" : "outline"}><Timer className="size-3" />{sla.label}</Badge>}<DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="More case actions"><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => navigator.clipboard?.writeText(`${window.location.origin}/app?case=${ticket.id}`)}>Copy case link</DropdownMenuItem>{ticket.lifecycle?.assigned_to && <DropdownMenuItem onSelect={() => onAssign(ticket.id, null, ticket.lifecycle.assigned_to)}>Release ownership</DropdownMenuItem>}<DropdownMenuItem>Mark as duplicate</DropdownMenuItem></DropdownMenuContent></DropdownMenu></div>
      </header>
      <div className="case-body">
        <section className="customer-message-section" aria-labelledby="customer-message-title">
          <div className="case-section-heading"><h3 id="customer-message-title">Customer message</h3><span><Clock3 />{ticket.receivedAt}</span></div>
          {ticket.subject && <p className="message-subject">{ticket.subject}</p>}
          <blockquote>“{revealed ? ticket.message : maskSensitive(ticket.message)}”</blockquote>
          {!revealed && ticket.message !== maskSensitive(ticket.message) && <Button variant="ghost" onClick={reveal}><Eye className="size-4" />Reveal sensitive details</Button>}
          {entities.length > 0 && <div className="entity-list">{entities.map(([key, value]) => <EntityTag key={key} label={labels[key]} value={value} />)}</div>}
          {(conversationLoading || conversation.length > 0) && <details className="case-disclosure"><summary><span><MessagesSquare />Conversation history</span><span>{conversation.length} messages <ChevronDown /></span></summary><div className="disclosure-content">{conversationLoading ? <Skeleton className="h-20 w-full" /> : conversation.map((message) => <div key={message.id} className={cn("conversation-message", message.direction === "outbound" && "conversation-message-outbound")}><span>{message.direction === "outbound" ? "Agent response" : "Customer"} · {message.delivery_status}</span><p>{message.body}</p></div>)}</div></details>}
        </section>
        <div className="case-decision-grid">
          <section className="human-decision" aria-labelledby="agent-decision-title">
            <h3 id="agent-decision-title">Agent decision</h3>
            <div className={cn("authoritative-state", decision.state === "auto" && "authoritative-state-safe")}><ShieldAlert /><div><strong>{decision.reason}</strong><p>The agent remains accountable for the next action.</p></div></div>
            {!isProcessed(ticket) && !backend.configured && <div className="classification-fields"><label>Issue<Select value={correction.intent || undefined} onValueChange={(value) => setCorrection({ ...correction, intent: value })}><SelectTrigger><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{intentOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></label><label>Urgency<Select value={correction.urgency || undefined} onValueChange={(value) => setCorrection({ ...correction, urgency: value })}><SelectTrigger><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{urgencyOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></label><label>Team<Select value={correction.route || undefined} onValueChange={(value) => setCorrection({ ...correction, route: value })}><SelectTrigger><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{teamOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></label></div>}
            <label className="draft-field"><span>Response draft</span><textarea value={draft} onChange={(event) => setDraft(event.target.value)} disabled={!isProcessed(ticket) && backend.configured} placeholder={!backend.configured ? "Write a human-owned response while the AI service is unavailable." : "A suggested draft will appear here."} rows={9} /></label>
            <div className="draft-meta"><span>{draft.length} characters</span><span>{ticket.customer.notes.some((note) => note.includes("Pidgin")) ? "Pidgin aware" : "English"}</span></div>
            <div className="case-primary-actions">
              {!isProcessed(ticket) ? backend.configured ? <Button disabled><LoaderCircle className={cn("size-4", aiLoading && "animate-spin")} />{aiLoading ? "Classifying conversation" : "Classification required"}</Button> : <Button disabled={actionLoading || !correction.intent || !correction.urgency || !correction.route || draft.trim().length < 2} onClick={() => onManualAssessment(ticket, { ...correction, response: draft })}><UserRoundCheck className="size-4" />Save assessment</Button> : ["sent", "delivered", "replied"].includes(ticket.lifecycle?.state) ? <Button disabled={actionLoading} onClick={() => onResolve(ticket.id)}><CheckCircle2 className="size-4" />Mark resolved</Button> : <><Button disabled={actionLoading} onClick={() => onEscalate(ticket.id, draft)} variant="outline"><Users className="size-4" />Assign to specialist</Button><Button disabled={actionLoading || !draft.trim()} onClick={() => onApprove(ticket.id, draft)}>{actionLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Check className="size-4" />}{canSend ? "Approve and send" : "Approve draft"}</Button></>}
              {!canSend && isProcessed(ticket) && <p>Approval is recorded in Kora. Nothing is sent until {ticket.channel === "email" ? "email" : "WhatsApp"} is connected.</p>}
            </div>
            <details className="case-disclosure"><summary><span><MessageCircle />Internal notes</span><span>{notes.length} notes <ChevronDown /></span></summary><div className="disclosure-content notes-content">{notes.slice(0, 3).map((note) => <div key={note.id}><strong>{note.actor}</strong><time>{formatDate(note.created_at)}</time><p>{note.body}</p></div>)}<textarea value={noteDraft} onChange={(event) => setNoteDraft(event.target.value)} rows={3} placeholder={`Add a private note. Use @${currentUser?.display_name?.split(" ")[0] || "teammate"} to mention someone.`} /><Button variant="outline" disabled={!noteDraft.trim() || actionLoading} onClick={() => { const mentions = [...noteDraft.matchAll(/@([A-Za-z][\w.-]*)/g)].map((match) => match[1]); onAddNote(ticket.id, noteDraft, mentions); setNoteDraft(""); }}>Add private note</Button></div></details>
          </section>
          <section className="suggestion-panel" aria-labelledby="suggestion-title">
            <div className="suggestion-heading"><div><h3 id="suggestion-title">Suggested classification</h3><p>Supporting information for the agent</p></div>{backend.configured && ticket.source !== "groq" && <Button onClick={() => onRunAI(ticket)} disabled={aiLoading} variant="ghost">{aiLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Sparkles className="size-4" />}Refresh</Button>}</div>
            <dl className="suggestion-summary">{[["Issue", ticket.intent], ["Urgency", ticket.urgency], ["Team", ticket.route], ["Confidence", isProcessed(ticket) ? `${Math.round(ticket.confidence * 100)}%` : "Pending"]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
            {isProcessed(ticket) && <details className="case-disclosure"><summary><span><Wrench />Edit classification</span><ChevronDown /></summary><div className="disclosure-content classification-fields"><label>Issue<Select value={correction.intent || "__keep__"} onValueChange={(value) => setCorrection({ ...correction, intent: value === "__keep__" ? "" : value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__keep__">Keep {ticket.intent}</SelectItem>{intentOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></label><label>Urgency<Select value={correction.urgency || "__keep__"} onValueChange={(value) => setCorrection({ ...correction, urgency: value === "__keep__" ? "" : value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__keep__">Keep {ticket.urgency}</SelectItem>{urgencyOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></label><label>Team<Select value={correction.route || "__keep__"} onValueChange={(value) => setCorrection({ ...correction, route: value === "__keep__" ? "" : value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__keep__">Keep {ticket.route}</SelectItem>{teamOptions.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></label><label>Reason<input value={correction.reason} onChange={(event) => setCorrection({ ...correction, reason: event.target.value })} placeholder="Why is this changing?" /></label><Button variant="outline" disabled={actionLoading || (!correction.intent && !correction.urgency && !correction.route)} onClick={() => onFeedback(ticket.id, correction)}>Save classification</Button></div></details>}
            <details className="case-disclosure"><summary><span><ShieldCheck />Evidence and policy</span><ChevronDown /></summary><div className="disclosure-content evidence-content"><h4>Evidence used</h4>{ticket.evidence.length ? <ol>{ticket.evidence.map((item) => <li key={item}>{item}</li>)}</ol> : <p>No evidence available yet.</p>}<h4>Approved policy sources</h4>{ticket.policyCitations?.length ? ticket.policyCitations.map((citation) => <div key={citation.id}><strong>{citation.title} v{citation.version}</strong><p>{citation.excerpt}</p></div>) : <p>No approved policy matched. The draft must remain human-reviewed.</p>}</div></details>
            <details className="case-disclosure"><summary><span><Database />Customer history</span><span>{ticket.memoryUsed ? "Used" : "Not used"} <ChevronDown /></span></summary><div className="disclosure-content memory-content">{memoryLoading ? <Skeleton className="h-16 w-full" /> : memoryItems.length ? memoryItems.slice(0, 2).map((memory) => <div key={`${memory.case_id}-${memory.created_at}`}><strong>{memory.case_id}</strong><time>{formatDate(memory.created_at)}</time><p>{memory.summary}</p></div>) : <p>No previous case history is available.</p>}</div></details>
            {ticket.entities?.transactionId && <div className="verification-row"><div><strong><CreditCard />Transaction verification</strong><p>{ticket.verifiedTransaction ? `Verified as ${ticket.verifiedTransaction.status}.` : backend.paystack?.configured ? "Verification is available for this reference." : "Transaction verification unavailable."}</p></div><Button variant="outline" disabled={actionLoading || !backend.paystack?.configured} onClick={() => onVerifyTransaction(ticket)}>{ticket.verifiedTransaction ? "Verify again" : "Verify"}</Button></div>}
            <details className="case-disclosure"><summary><span><Activity />Technical details</span><ChevronDown /></summary><div className="disclosure-content technical-details"><p>Source: {ticket.source || "pending"}</p><p>Model: {ticket.model || "not available"}</p><p>Processing time: {ticket.processingMs == null ? "not available" : `${ticket.processingMs} ms`}</p></div></details>
          </section>
        </div>
      </div>
    </article>
  );
}

function TeamView({ tickets, onFilterQueue }) {
  const members = [
    { name: "Ada Okafor", role: "Support manager", teams: ["General Support"], initials: "AO", status: "Online", capacity: 8 },
    { name: "Musa Ibrahim", role: "Payments specialist", teams: ["Transfers", "Billing"], initials: "MI", status: "Busy", capacity: 5 },
    { name: "Nneka Eze", role: "Risk specialist", teams: ["Fraud", "Compliance"], initials: "NE", status: "Offline", capacity: 4 },
    { name: "Bola Martins", role: "Customer operations", teams: ["Logistics", "Account Support"], initials: "BM", status: "Online", capacity: 7 }
  ];
  return (
    <div className="view-padding">
      <div className="page-heading"><p>Primary ownership, current capacity and backup coverage for the open queue.</p></div>
      <div className="table-surface"><Table><TableHeader><TableRow><TableHead>Team member</TableHead><TableHead>Primary coverage</TableHead><TableHead>Assigned</TableHead><TableHead>Capacity</TableHead><TableHead>Availability</TableHead><TableHead><span className="sr-only">Actions</span></TableHead></TableRow></TableHeader><TableBody>{members.map((member) => { const assigned = tickets.filter((ticket) => ticket.lifecycle?.assigned_to === member.name || ticket.assignee === member.name).length; const overloaded = assigned > member.capacity; return <TableRow key={member.name}><TableCell><span className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-full bg-muted-surface text-[11px] font-semibold">{member.initials}</span><span><strong className="block">{member.name}</strong><small>{member.role}</small></span></span></TableCell><TableCell>{member.teams.join(", ")}</TableCell><TableCell><strong>{assigned}</strong> primary</TableCell><TableCell><span className={overloaded ? "text-red-700 font-semibold" : ""}>{assigned} of {member.capacity}{overloaded ? " · Overloaded" : ""}</span></TableCell><TableCell><Badge variant={member.status === "Online" ? "accent" : member.status === "Busy" ? "outline" : "neutral"}>{member.status}</Badge></TableCell><TableCell><Button variant="ghost" onClick={() => onFilterQueue(member.name)}>View queue</Button></TableCell></TableRow>; })}</TableBody></Table></div>
      <p className="mt-4 text-[13px] text-ink-muted">Coverage can overlap, but assignment counts only primary ownership. Total open conversations: {tickets.filter((ticket) => ticket.lifecycle?.state !== "resolved").length}.</p>
    </div>
  );
}

const proofSample = JSON.stringify([
  {
    case_id: "HIST-001",
    channel: "whatsapp",
    language: "pidgin",
    message: "Abeg my transfer TRX-12345 never reach since morning.",
    customer_name: "Historical customer",
    expected: { intent: "Transfer pending", urgency: "high", route: "Transfers" }
  }
], null, 2);

function ProofView({ runs, onRun, running, backend }) {
  const [name, setName] = useState("Pre-launch inbox proof");
  const [source, setSource] = useState(proofSample);
  const [parseError, setParseError] = useState("");
  const latest = runs[0];
  const submit = () => {
    try {
      const cases = JSON.parse(source);
      if (!Array.isArray(cases) || !cases.length) throw new Error("Provide a non-empty JSON array.");
      setParseError("");
      onRun({ name, cases });
    } catch (error) {
      setParseError(error.message);
    }
  };
  return (
    <div className="view-padding max-w-6xl">
      <div className="mb-7"><p className="section-label">Silent historical evaluation</p><h2 className="mt-1 text-[26px] font-extrabold tracking-[-0.05em]">Prove Kora before activation</h2><p className="mt-2 max-w-2xl text-[11px] leading-5 text-ink-muted">Run labelled historical complaints through the live decision system. Proof cases are isolated from the support queue and can never be delivered to customers.</p></div>
      {!backend.configured && <div className="mb-5 flex gap-3 border border-ink bg-ink p-4 text-paper"><WifiOff className="size-4 shrink-0 text-accent" /><div><strong className="text-[10px]">Proof Mode needs the configured Groq model</strong><p className="mt-1 text-[9px] text-paper/65">The live workspace remains available for manual handling while AI is unavailable.</p></div></div>}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,.8fr)]">
        <Card className="p-6">
          <label className="grid gap-2 text-[10px] font-extrabold">Run name<input value={name} onChange={(event) => setName(event.target.value)} className="h-11 rounded-[7px] border border-line-strong bg-paper px-3 text-[11px] outline-none focus:border-ink focus:ring-2 focus:ring-ring" /></label>
          <label className="mt-5 grid gap-2 text-[10px] font-extrabold">Historical cases<textarea value={source} onChange={(event) => setSource(event.target.value)} rows={16} spellCheck={false} className="w-full resize-y rounded-[8px] border border-line-strong bg-shell p-4 font-mono text-[10px] leading-5 text-paper outline-none focus:ring-2 focus:ring-ring" /></label>
          <div className="mt-3 flex items-center justify-between gap-4"><span className="text-[9px] text-ink-faint">Up to 100 cases. Expected labels are optional.</span><Button onClick={submit} disabled={running || !backend.configured}>{running ? <LoaderCircle className="size-4 animate-spin" /> : <ClipboardCheck className="size-4" />}{running ? "Running proof" : "Run silently"}</Button></div>
          {parseError && <p className="mt-3 text-[9px] font-bold">{parseError}</p>}
        </Card>
        <div className="space-y-5">
          <div className="border border-line-strong bg-ai p-6">
            <p className="section-label !text-ink">Latest readiness result</p>
            {latest ? <><div className="mt-4 flex items-end justify-between"><strong className="text-[52px] font-extrabold tracking-[-0.07em]">{latest.report.readiness_score}</strong><Badge variant={latest.report.readiness_score >= 85 ? "accent" : "outline"} shape="pill">/ 100</Badge></div><h3 className="mt-3 text-[14px] font-extrabold">{latest.report.recommendation}</h3><div className="mt-5 divide-y divide-line-strong border-y border-line-strong">{[["Completed", latest.report.completed], ["Label accuracy", latest.report.label_accuracy == null ? "No labels" : `${Math.round(latest.report.label_accuracy * 100)}%`], ["Safe candidates", latest.report.safe_automation_candidates], ["Human review", latest.report.human_review_cases]].map(([label, value]) => <div key={label} className="flex items-center justify-between py-3 text-[10px]"><span className="text-ink-muted">{label}</span><strong>{value}</strong></div>)}</div></> : <div className="py-14 text-center"><ClipboardCheck className="mx-auto size-6 text-ink-faint" /><p className="mt-3 text-[10px] text-ink-muted">No proof run yet.</p></div>}
          </div>
          {runs.slice(1, 4).map((run) => <Card key={run.id} className="flex items-center justify-between p-4"><span><strong className="block text-[10px]">{run.name}</strong><time className="mt-1 block text-[8px] text-ink-faint">{new Date(run.created_at).toLocaleString()}</time></span><strong className="text-[20px]">{run.report.readiness_score}</strong></Card>)}
        </div>
      </div>
    </div>
  );
}

function HistoricalEvaluationView({ runs, onRun, running, backend }) {
  const [name, setName] = useState("Historical support evaluation");
  const [cases, setCases] = useState([]);
  const [source, setSource] = useState(proofSample);
  const [error, setError] = useState("");
  const parseRows = (text, filename = "") => {
    if (filename.toLowerCase().endsWith(".csv")) {
      const lines = text.trim().split(/\r?\n/).filter(Boolean);
      const headers = lines.shift().split(",").map((value) => value.trim());
      return lines.map((line, index) => {
        const values = line.split(",").map((value) => value.trim());
        const row = Object.fromEntries(headers.map((header, column) => [header, values[column] || ""]));
        return { case_id: row.case_id || `ROW-${index + 2}`, channel: row.channel || "email", language: row.language || "english", message: row.message, customer_name: row.customer_name || "Historical customer", expected: row.expected_intent || row.expected_urgency || row.expected_route ? { intent: row.expected_intent || undefined, urgency: row.expected_urgency || undefined, route: row.expected_route || undefined } : undefined };
      });
    }
    return JSON.parse(text);
  };
  const validate = (items) => {
    if (!Array.isArray(items) || !items.length) throw new Error("Add at least one historical case.");
    const invalid = items.map((item, index) => (!item.message || !["email", "whatsapp"].includes(item.channel) ? index + 1 : null)).filter(Boolean);
    if (invalid.length) throw new Error(`Rows ${invalid.join(", ")} need a message and a valid email or whatsapp channel.`);
    if (items.length > 100) throw new Error("Use 100 cases or fewer per evaluation.");
    return items;
  };
  const load = (text, filename) => { try { const parsed = validate(parseRows(text, filename)); setCases(parsed); setSource(JSON.stringify(parsed, null, 2)); setError(""); } catch (loadError) { setCases([]); setError(loadError.message); } };
  const downloadTemplate = () => { const csv = "case_id,channel,language,message,customer_name,expected_intent,expected_urgency,expected_route\nHIST-001,whatsapp,pidgin,Abeg my transfer never reach since morning,Chidinma Okeke,Transfer pending,high,Transfers"; const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); link.download = "kora-evaluation-template.csv"; link.click(); URL.revokeObjectURL(link.href); };
  const latest = runs[0];
  return <div className="view-padding max-w-6xl"><div className="page-heading"><h2>Historical evaluation</h2><p>Upload labelled past conversations to measure routing quality and review requirements without contacting customers.</p></div>{!backend.configured && <div className="system-notice"><WifiOff /><div><strong>AI service unavailable</strong><p>Historical evaluation needs the AI service. The support queue remains available for manual work.</p></div></div>}<div className="evaluation-layout"><section className="evaluation-input"><label>Evaluation name<input value={name} onChange={(event) => setName(event.target.value)} /></label><div className="upload-zone"><ClipboardCheck /><strong>Upload historical cases</strong><p>CSV or JSON, up to 100 cases. Expected labels are optional.</p><label className="upload-button">Choose file<input type="file" accept=".csv,.json,application/json,text/csv" onChange={(event) => { const file = event.target.files?.[0]; if (file) file.text().then((text) => load(text, file.name)); }} /></label><div><Button variant="ghost" onClick={downloadTemplate}><Download />Download template</Button><Button variant="ghost" onClick={() => load(proofSample, "sample.json")}>Use sample data</Button></div></div>{error && <p className="validation-error"><CircleAlert />{error}</p>}{cases.length > 0 && <div className="validation-preview"><strong>{cases.length} cases ready</strong><span>Estimated processing time: {Math.max(1, Math.ceil(cases.length * 2 / 60))} minute{cases.length > 30 ? "s" : ""}</span><div>{cases.slice(0, 4).map((item, index) => <p key={`${item.case_id}-${index}`}><span>{item.case_id}</span><span>{item.channel}</span><span>{item.message}</span><CheckCircle2 /></p>)}</div></div>}<details className="case-disclosure"><summary><span>Advanced: raw JSON editor</span><ChevronDown /></summary><div className="disclosure-content"><textarea value={source} onChange={(event) => setSource(event.target.value)} rows={12} spellCheck={false} /><Button variant="outline" onClick={() => load(source, "advanced.json")}>Validate JSON</Button></div></details><Button onClick={() => onRun({ name, cases })} disabled={running || !backend.configured || !cases.length}>{running ? <LoaderCircle className="animate-spin" /> : <ClipboardCheck />}{running ? "Running evaluation" : "Run historical evaluation"}</Button></section><section className="evaluation-results"><h3>Latest result</h3>{latest ? <><p className="result-date">{formatDate(latest.created_at)} · {latest.report.completed || latest.report.total} cases</p><div className="result-list">{[["Cases processed", latest.report.completed], ["Intent accuracy", latest.report.intent_accuracy == null ? "Not labelled" : `${Math.round(latest.report.intent_accuracy * 100)}%`], ["Urgency accuracy", latest.report.urgency_accuracy == null ? "Not labelled" : `${Math.round(latest.report.urgency_accuracy * 100)}%`], ["Routing accuracy", latest.report.routing_accuracy == null ? "Not labelled" : `${Math.round(latest.report.routing_accuracy * 100)}%`], ["Guardrail failures", latest.report.guardrail_failures || 0], ["Cases requiring review", latest.report.human_review_cases], ["Eligible under safety policy", latest.report.safe_automation_candidates]].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><Button variant="outline"><Download />Download error set</Button></> : <div className="compact-empty"><p>No evaluation has been run. Upload labelled cases to measure routing accuracy and review requirements.</p></div>}</section></div></div>;
}

function SettingsView({ automation, onChange, onSave, saving, tickets, integrations, jobs, policies, onCreatePolicy, onTogglePolicy, policySaving }) {
  const [policyDraft, setPolicyDraft] = useState({ title: "", version: "1.0", source_url: "", content: "" });
  const [confirmSave, setConfirmSave] = useState(false);
  const hasActivePolicies = policies.some((policy) => policy.active);
  const hasDelivery = integrations?.mode === "live" && (integrations?.email?.configured || integrations?.whatsapp?.configured);
  const governanceReady = hasActivePolicies && hasDelivery;
  const autoCount = tickets.filter((ticket) => policyState(ticket, automation, { integrations }) === "auto").length;
  const reviewCount = tickets.filter((ticket) => policyState(ticket, automation, { integrations }) === "mandatory").length;
  const assignedCount = tickets.filter((ticket) => ticket.lifecycle?.assigned_to || ticket.assignee).length;
  return (
    <div className="view-padding max-w-5xl">
      <div className="page-heading"><p>Confidence is only one requirement. Policy, verification, guardrails, information completeness and delivery must also pass.</p></div>
      <div className="grid gap-5 lg:grid-cols-[1.2fr_.8fr]">
        <Card className="p-6">
          <div className="flex items-start justify-between gap-5 border-b border-line pb-5"><div><div className="flex items-center gap-2"><Zap className="size-4" /><h3 className="text-[14px] font-semibold">Auto-approve eligible drafts</h3></div><p className="mt-2 max-w-lg text-[13px] leading-5 text-ink-muted">Eligible cases need an approved policy match, no guardrail, required verification, complete information, connected delivery and sufficient confidence.</p></div><button type="button" role="switch" aria-label="Enable auto-approval" aria-checked={automation.enabled} disabled={!governanceReady && !automation.enabled} onClick={() => onChange({ ...automation, enabled: !automation.enabled })} className={cn("safe-switch", automation.enabled && "safe-switch-on")}><span /></button></div>
          {!governanceReady && <div className="mt-4 rounded-[8px] bg-muted-surface p-4 text-[13px]"><strong>Auto-approval is unavailable</strong><p className="mt-1 text-ink-muted">{!hasActivePolicies ? "Add and activate an approved policy. " : ""}{!hasDelivery ? "Connect email or WhatsApp for live delivery." : ""}</p></div>}
          <label className="mt-6 block"><span className="flex items-center justify-between"><span className="text-[10px] font-extrabold">Auto-approve threshold</span><strong className="text-[20px] tracking-[-0.04em]">{automation.auto_approve_threshold}%</strong></span><input type="range" min="80" max="99" value={automation.auto_approve_threshold} onChange={(event) => onChange({ ...automation, auto_approve_threshold: Number(event.target.value) })} className="mt-4 w-full accent-[var(--color-ink)]" /><span className="mt-2 flex justify-between text-[8px] font-bold text-ink-faint"><span>80%</span><span>99%</span></span></label>
          <label className="mt-7 block border-t border-line pt-6"><span className="flex items-center justify-between"><span className="text-[10px] font-extrabold">Mandatory review below</span><strong className="text-[20px] tracking-[-0.04em]">{automation.mandatory_review_threshold}%</strong></span><input type="range" min="50" max="90" value={automation.mandatory_review_threshold} onChange={(event) => onChange({ ...automation, mandatory_review_threshold: Number(event.target.value) })} className="mt-4 w-full accent-[var(--color-ink)]" /><span className="mt-2 flex justify-between text-[8px] font-bold text-ink-faint"><span>50%</span><span>90%</span></span></label>
          {automation.mandatory_review_threshold >= automation.auto_approve_threshold && <p className="mt-4 flex items-center gap-2 text-[10px] font-bold"><CircleAlert className="size-4" />The lower threshold must remain below auto-approve.</p>}
          {confirmSave ? <div className="mt-5 border-y border-line py-4 text-[13px]"><strong>Policy impact before save</strong><p className="mt-1 text-ink-muted">{autoCount} conversations would be eligible and {reviewCount} would require review. Fraud, security and financial-action cases remain blocked.</p><div className="mt-3 flex gap-2"><Button onClick={() => { onSave(); setConfirmSave(false); }} disabled={saving}><Save className="size-4" />Confirm and save</Button><Button variant="ghost" onClick={() => setConfirmSave(false)}>Cancel</Button></div></div> : <Button onClick={() => setConfirmSave(true)} disabled={saving || automation.mandatory_review_threshold >= automation.auto_approve_threshold || (automation.enabled && !governanceReady)} className="mt-7"><Save className="size-4" />Review changes</Button>}
        </Card>
      <div className="automation-impact p-6"><h3 className="text-[15px] font-semibold">Current queue impact</h3><div className="mt-5 divide-y divide-line">{[["Eligible for auto-approval", autoCount, "All safety conditions pass"], ["Assigned conversations", assignedCount, `Primary owner recorded out of ${tickets.length}`], ["Human review required", reviewCount, "A governance or risk condition blocks automation"]].map(([label, count, meta]) => <div key={label} className="flex items-center justify-between py-4"><span><strong className="block text-[13px]">{label}</strong><small className="mt-1 block text-[12px] text-ink-faint">{meta}</small></span><strong className="text-[22px] font-semibold">{count}</strong></div>)}</div></div>
      </div>
      <div className="mt-5 border border-line-strong bg-paper">
        <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line p-6"><div><h3 className="text-[16px] font-semibold tracking-[-0.03em]">Customer channels</h3><p className="mt-2 max-w-2xl text-[13px] leading-5 text-ink-muted">Only connected live channels can deliver an approved response.</p></div><Badge variant={hasDelivery ? "accent" : "neutral"}>{hasDelivery ? "Delivery available" : "Delivery unavailable"}</Badge></div>
        <div className="grid lg:grid-cols-[1fr_1fr_.8fr]">
          {[["Email", Mail, integrations?.email], ["WhatsApp", MessageCircle, integrations?.whatsapp]].map(([label, Icon, channel]) => <div key={label} className="border-b border-line p-6 lg:border-b-0 lg:border-r"><div className="flex items-center justify-between"><span className="flex items-center gap-2"><Icon className="size-4" /><strong className="text-[13px]">{label}</strong></span><Badge variant={channel?.configured ? "accent" : "neutral"}>{channel?.configured ? "Connected" : "Not connected"}</Badge></div></div>)}
          <div className="p-6"><div className="flex items-center gap-2"><Wrench className="size-4" /><strong className="text-[13px]">System health</strong></div><p className="mt-3 text-[13px] text-ink-muted">{(jobs?.counts?.dead || 0) > 0 ? "Some deliveries need attention" : "System healthy"}</p></div>
        </div>
      </div>
      <div className="mt-5 border border-line-strong bg-paper">
        <div className="border-b border-line p-6"><h3 className="text-[16px] font-semibold tracking-[-0.02em]">Approved response policies</h3><p className="mt-2 max-w-2xl text-[13px] leading-5 text-ink-muted">Kora retrieves matching policy text before drafting and records every cited version in the case audit.</p></div>
        <div className="grid lg:grid-cols-[1fr_1fr]">
          <div className="border-b border-line p-6 lg:border-b-0 lg:border-r">
            <div className="grid gap-3 sm:grid-cols-[1fr_110px]"><label className="grid gap-2 text-[9px] font-bold">Policy title<input value={policyDraft.title} onChange={(event) => setPolicyDraft({ ...policyDraft, title: event.target.value })} placeholder="Transfer reversal timeline" className="h-10 rounded-[7px] border border-line-strong px-3 text-[10px] outline-none focus:ring-2 focus:ring-ring" /></label><label className="grid gap-2 text-[9px] font-bold">Version<input value={policyDraft.version} onChange={(event) => setPolicyDraft({ ...policyDraft, version: event.target.value })} className="h-10 rounded-[7px] border border-line-strong px-3 text-[10px] outline-none focus:ring-2 focus:ring-ring" /></label></div>
            <label className="mt-3 grid gap-2 text-[9px] font-bold">Source URL (optional)<input value={policyDraft.source_url} onChange={(event) => setPolicyDraft({ ...policyDraft, source_url: event.target.value })} placeholder="https://company.example/policy" className="h-10 rounded-[7px] border border-line-strong px-3 text-[10px] outline-none focus:ring-2 focus:ring-ring" /></label>
            <label className="mt-3 grid gap-2 text-[9px] font-bold">Approved content<textarea value={policyDraft.content} onChange={(event) => setPolicyDraft({ ...policyDraft, content: event.target.value })} rows={7} placeholder="Paste the exact approved policy, required information, timeline and escalation path." className="resize-y rounded-[7px] border border-line-strong p-3 text-[10px] leading-5 outline-none focus:ring-2 focus:ring-ring" /></label>
            <Button className="mt-3" disabled={policySaving || policyDraft.title.length < 3 || policyDraft.content.length < 20} onClick={async () => { const saved = await onCreatePolicy({ ...policyDraft, source_url: policyDraft.source_url || null }); if (saved) setPolicyDraft({ title: "", version: "1.0", source_url: "", content: "" }); }}><BookOpenCheck className="size-4" />{policySaving ? "Saving policy" : "Approve policy"}</Button>
          </div>
          <div className="divide-y divide-line">{policies.length ? policies.map((policy) => <div key={policy.id} className="flex items-start justify-between gap-5 p-5"><div className="min-w-0"><div className="flex items-center gap-2"><strong className="truncate text-[13px]">{policy.title}</strong><Badge variant={policy.active ? "accent" : "neutral"} shape="pill">v{policy.version}</Badge></div><p className="mt-2 line-clamp-2 text-[12px] leading-5 text-ink-muted">{policy.content}</p></div><button type="button" role="switch" aria-label={`${policy.active ? "Deactivate" : "Activate"} ${policy.title}`} aria-checked={Boolean(policy.active)} onClick={() => onTogglePolicy(policy.id, !policy.active)} className={cn("relative h-11 w-11 shrink-0 rounded-full border transition-colors focus-visible:ring-2 focus-visible:ring-ring", policy.active ? "border-ink bg-ink" : "border-line-strong bg-muted-surface")}><span className={cn("absolute left-2 top-[13px] size-4 rounded-full bg-paper transition-transform", policy.active ? "translate-x-3" : "translate-x-0")} /></button></div>) : <div className="p-6"><BookOpenCheck className="size-5 text-ink-faint" /><strong className="mt-3 block text-[13px]">No approved policies</strong><p className="mt-1 max-w-md text-[12px] leading-5 text-ink-muted">Drafts remain human-reviewed until the first company policy is added.</p></div>}</div>
        </div>
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

const auditLabels = {
  triage: "Automated classification",
  human_routed: "Routed by agent",
  human_escalated: "Assigned to specialist",
  human_approved: "Approved by agent",
  safety_policy_auto_approved: "Auto-approved by safety policy",
  confidence_auto_approved: "Legacy confidence approval",
  policy_created: "Policy approved",
  proof_run_completed: "Historical evaluation completed",
  sensitive_data_revealed: "Sensitive data revealed"
};
const auditValueLabels = { assigned_to_specialist: "Assigned to specialist", routed: "Routed by agent", approved: "Approved by agent", auto_approved: "Auto-approved" };

function DecisionAuditView({ items, loading }) {
  const [search, setSearch] = useState("");
  const [eventType, setEventType] = useState("all");
  const [actor, setActor] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const displayActor = (item) => item.event_type === "triage" ? "Kora automation" : item.actor || "System";
  const filtered = items.filter((item) => {
    const haystack = `${item.case_id} ${item.customer_id} ${item.event_type} ${displayActor(item)}`.toLowerCase();
    return (!search || haystack.includes(search.toLowerCase())) && (eventType === "all" || item.event_type === eventType) && (actor === "all" || displayActor(item) === actor) && (!dateFrom || new Date(item.created_at) >= new Date(dateFrom));
  });
  const exportCsv = () => { const rows = [["time", "case", "customer", "event", "actor", "decision"], ...filtered.map((item) => [item.created_at, item.case_id, item.customer_id, auditLabels[item.event_type] || item.event_type, item.actor || "System", item.decision.intent || item.decision.status || "Recorded action"])]; const csv = rows.map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")).join("\n"); const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); link.download = "kora-filtered-audit.csv"; link.click(); URL.revokeObjectURL(link.href); };
  const events = [...new Set(items.map((item) => item.event_type))];
  const actors = [...new Set(items.map(displayActor))];
  return <div className="view-padding"><div className="page-heading page-heading-row"><div><h2>Decision audit</h2><p>Search and inspect automated decisions, agent actions and governance changes.</p></div><Button variant="outline" onClick={exportCsv} disabled={!filtered.length}><Download />Export filtered results</Button></div><div className="audit-filters"><label><Search /><span className="sr-only">Search audit trail</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search case, customer or actor" /></label><input type="date" aria-label="Start date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /><Select value={eventType} onValueChange={setEventType}><SelectTrigger aria-label="Event type"><SelectValue placeholder="Event type" /></SelectTrigger><SelectContent><SelectItem value="all">All event types</SelectItem>{events.map((value) => <SelectItem key={value} value={value}>{auditLabels[value] || value.replaceAll("_", " ")}</SelectItem>)}</SelectContent></Select><Select value={actor} onValueChange={setActor}><SelectTrigger aria-label="Actor"><SelectValue placeholder="Actor" /></SelectTrigger><SelectContent><SelectItem value="all">All actors</SelectItem>{actors.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></div><div className="table-surface audit-table">{loading ? <div className="space-y-3 p-5"><Skeleton className="h-12 w-full" /><Skeleton className="h-16 w-full" /></div> : filtered.length ? <Table><TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Case</TableHead><TableHead>Event</TableHead><TableHead>Decision</TableHead><TableHead>Actor</TableHead><TableHead><span className="sr-only">Details</span></TableHead></TableRow></TableHeader><TableBody>{filtered.map((item) => { const summary = item.decision.intent || item.decision.status || "Recorded action"; return <TableRow key={item.id}><TableCell><time>{formatDate(item.created_at)}</time></TableCell><TableCell><strong>{item.case_id}</strong></TableCell><TableCell>{auditLabels[item.event_type] || item.event_type.replaceAll("_", " ")}</TableCell><TableCell>{summary}</TableCell><TableCell>{item.actor || "System"}</TableCell><TableCell><details className="audit-expansion"><summary>View reasoning</summary><div><p><strong>Reason:</strong> {item.guardrails.reason || item.decision.evidence?.join("; ") || "Agent decision"}</p><p><strong>Customer:</strong> {item.customer_id}</p><p><strong>Technical source:</strong> {item.model || "Human action"}</p></div></details></TableCell></TableRow>; })}</TableBody></Table> : <p className="compact-empty">No audit events match these filters.</p>}</div></div>;
}

function DashboardApp() {
  const [signedIn, setSignedIn] = useState(true);
  const [tickets, setTickets] = useState(seedTickets);
  const [activeView, setActiveView] = useState("queue");
  const [selectedId, setSelectedId] = useState(seedTickets.find((ticket) => ticket.urgency === "critical")?.id || seedTickets[0].id);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ review: false, high: false, sla: false, unassigned: false, assignee: "all", channel: "all", urgency: "all", team: "all" });
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
  const [automation, setAutomation] = useState({ enabled: false, auto_approve_threshold: 95, mandatory_review_threshold: 70 });
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);
  const [integrations, setIntegrations] = useState(null);
  const [jobs, setJobs] = useState({ counts: {} });
  const [evaluationSummary, setEvaluationSummary] = useState(null);
  const [evaluationGate, setEvaluationGate] = useState(null);
  const [conversation, setConversation] = useState([]);
  const [caseNotes, setCaseNotes] = useState([]);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [policies, setPolicies] = useState([]);
  const [policySaving, setPolicySaving] = useState(false);
  const [proofRuns, setProofRuns] = useState([]);
  const [proofRunning, setProofRunning] = useState(false);
  const [mobileCaseOpen, setMobileCaseOpen] = useState(false);
  const queueScrollRef = useRef(null);
  const queueScrollPosition = useRef(0);
  const activeFilters = { review: false, high: false, sla: false, unassigned: false, assignee: "all", channel: "all", urgency: "all", team: "all", ...filters };
  const governance = { integrations, policies };

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

  const refreshConversation = async (caseId) => {
    setConversationLoading(true);
    try {
      const result = await getCaseConversation(caseId);
      setConversation(result.messages || []);
      setCaseNotes(result.notes || []);
      setTickets((items) => items.map((ticket) => ticket.id === caseId ? { ...ticket, lifecycle: result.lifecycle || ticket.lifecycle } : ticket));
    } catch {
      setConversation([]);
      setCaseNotes([]);
    } finally {
      setConversationLoading(false);
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
    Promise.all([getCases(), getAutomationSettings(), getBackendAudit(200), getCurrentUser(), getIntegrations(), getEvaluationSummary()])
      .then(async ([caseResult, settingsResult, auditResult, userResult, integrationResult, evaluationResult]) => {
        if (!active) return;
        setTickets(caseResult.items || seedTickets);
        setAutomation(settingsResult);
        setAuditItems(auditResult.items || []);
        setCurrentUser(userResult);
        setIntegrations(integrationResult);
        setEvaluationSummary(evaluationResult);
        const [jobResult, gateResult, policyResult, proofResult] = await Promise.allSettled([getJobs(50), getEvaluationGate(), getPolicies(), getProofRuns()]);
        if (!active) return;
        if (jobResult.status === "fulfilled") setJobs(jobResult.value);
        if (gateResult.status === "fulfilled") setEvaluationGate(gateResult.value);
        if (policyResult.status === "fulfilled") setPolicies(policyResult.value.items || []);
        if (proofResult.status === "fulfilled") setProofRuns(proofResult.value.items || []);
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
      && (!activeFilters.review || policyState(ticket, automation, governance) === "mandatory")
      && (!activeFilters.high || ["critical", "high"].includes(ticket.urgency))
      && (!activeFilters.sla || Boolean(slaState(ticket)))
      && (!activeFilters.unassigned || (!ticket.lifecycle?.assigned_to && !ticket.assignee && ticket.status !== "Assigned"))
      && (activeFilters.assignee === "all" || ticket.lifecycle?.assigned_to === activeFilters.assignee || ticket.assignee === activeFilters.assignee)
      && (activeFilters.channel === "all" || ticket.channel === activeFilters.channel)
      && (activeFilters.urgency === "all" || ticket.urgency === activeFilters.urgency)
      && (activeFilters.team === "all" || ticket.route === activeFilters.team);
  }).sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency] || b.minutesAgo - a.minutesAgo), [tickets, query, activeFilters.review, activeFilters.high, activeFilters.sla, activeFilters.unassigned, activeFilters.assignee, activeFilters.channel, activeFilters.urgency, activeFilters.team, automation, integrations, policies]);

  useEffect(() => { if (visibleTickets.length && !visibleTickets.some((ticket) => ticket.id === selectedId)) setSelectedId(visibleTickets[0].id); }, [visibleTickets, selectedId]);
  const selectedTicket = tickets.find((ticket) => ticket.id === selectedId) || tickets[0];
  useEffect(() => {
    if (backend.state === "online") {
      refreshMemory(selectedTicket.customerId);
      refreshConversation(selectedTicket.id);
    }
  }, [backend.state, selectedTicket.customerId, selectedTicket.id]);
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
        estimatedMinutesSaved: result.estimated_minutes_saved,
        policyCitations: result.policy_citations || []
      };
      const shouldAutoApprove = result.status === "Auto-approved";
      setTickets((items) => items.map((item) => item.id === ticket.id ? { ...updatedTicket, customer: item.customer } : item));
      refreshAudit();
      refreshMemory(ticket.customerId);
      setToast(shouldAutoApprove ? `${ticket.id} passed the active safety policy` : `${ticket.id} classification is ready for review`);
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
      const result = await recordCaseAction(ticket, "approve", draft);
      updateStatus(id, result.status === "queued" ? "Queued to send" : "Approved", false);
      if (result.status === "queued") {
        setTickets((items) => items.map((item) => item.id === id ? { ...item, lifecycle: { ...(item.lifecycle || {}), state: "queued" } } : item));
      }
      refreshAudit();
      refreshConversation(id);
      setToast(result.status === "queued" ? `${id} queued for delivery` : `${id} approval recorded`);
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

  const saveFeedback = async (id, feedback) => {
    const ticket = tickets.find((item) => item.id === id);
    setActionLoadingId(id);
    try {
      await recordCaseFeedback(ticket, feedback);
      setTickets((items) => items.map((item) => item.id === id ? {
        ...item,
        intent: feedback.intent || item.intent,
        urgency: feedback.urgency || item.urgency,
        route: feedback.route || item.route
      } : item));
      const summary = await getEvaluationSummary();
      setEvaluationSummary(summary);
      if (currentUser?.role !== "support_agent") {
        const gate = await getEvaluationGate();
        setEvaluationGate(gate);
      }
      refreshAudit();
      setToast(`${id} correction added to the evaluation set`);
    } catch (error) {
      setToast(error.message || "Could not save the correction");
    } finally {
      setActionLoadingId(null);
    }
  };

  const resolve = async (id) => {
    const ticket = tickets.find((item) => item.id === id);
    setActionLoadingId(id);
    try {
      await resolveCase(ticket, "Agent confirmed the customer issue is resolved.");
      setTickets((items) => items.map((item) => item.id === id ? { ...item, status: "Resolved", lifecycle: { ...(item.lifecycle || {}), state: "resolved" } } : item));
      refreshAudit();
      setToast(`${id} resolved`);
    } catch (error) {
      setToast(error.message || "Could not resolve the case");
    } finally {
      setActionLoadingId(null);
    }
  };

  const toggleSelected = (id) => setSelectedIds((ids) => ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]);
  const selectAll = (ids, checked) => setSelectedIds((current) => checked ? [...new Set([...current, ...ids])] : current.filter((id) => !ids.includes(id)));
  const bulkApprove = async () => {
    const eligible = tickets.filter((ticket) => selectedIds.includes(ticket.id) && lowRisk(ticket, automation, governance));
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
    const selected = tickets.filter((ticket) => selectedIds.includes(ticket.id) && lowRisk(ticket, automation, governance));
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

  const assignCase = async (id, assignee, expectedAssignee) => {
    setActionLoadingId(id);
    try {
      const result = await updateCaseAssignment(id, assignee, expectedAssignee);
      setTickets((items) => items.map((ticket) => ticket.id === id ? { ...ticket, assignee: result.assignee, lifecycle: result.lifecycle } : ticket));
      refreshAudit();
      setToast(result.assignee ? `${id} assigned to ${result.assignee}` : `${id} returned to the shared queue`);
    } catch (error) {
      setToast(error.message || "Case ownership changed before your update");
      refreshConversation(id);
    } finally {
      setActionLoadingId(null);
    }
  };

  const saveCaseNote = async (id, body, mentions) => {
    setActionLoadingId(id);
    try {
      const note = await addCaseNote(id, body, mentions);
      setCaseNotes((items) => [note, ...items]);
      refreshAudit();
      setToast(mentions.length ? `Private note added with ${mentions.length} mention` : "Private note added");
    } catch (error) {
      setToast(error.message || "Could not add the private note");
    } finally {
      setActionLoadingId(null);
    }
  };

  const verifyTransaction = async (ticket) => {
    const reference = ticket.entities?.transactionId;
    if (!reference) return;
    setActionLoadingId(ticket.id);
    try {
      const result = await verifyPaystackTransaction(ticket, reference);
      setTickets((items) => items.map((item) => item.id === ticket.id ? { ...item, verifiedTransaction: result } : item));
      refreshAudit();
      setToast(`${reference} verified as ${result.status}`);
    } catch (error) {
      setToast(error.message || "Transaction verification failed");
    } finally {
      setActionLoadingId(null);
    }
  };

  const saveHumanAssessment = async (ticket, assessment) => {
    setActionLoadingId(ticket.id);
    try {
      const result = await saveManualAssessment(ticket, assessment);
      setTickets((items) => items.map((item) => item.id === ticket.id ? { ...result.ticket, customer: result.ticket.customer || item.customer, lifecycle: result.lifecycle } : item));
      refreshAudit();
      setToast(`${ticket.id} moved to the human-owned manual queue`);
    } catch (error) {
      setToast(error.message || "Could not save the manual assessment");
    } finally {
      setActionLoadingId(null);
    }
  };

  const savePolicy = async (policy) => {
    setPolicySaving(true);
    try {
      const saved = await createPolicy(policy);
      setPolicies((items) => [saved, ...items]);
      refreshAudit();
      setToast(`${saved.title} approved for grounding`);
      return saved;
    } catch (error) {
      setToast(error.message || "Could not save the policy");
      return null;
    } finally {
      setPolicySaving(false);
    }
  };

  const togglePolicy = async (id, active) => {
    try {
      const saved = await setPolicyState(id, active);
      setPolicies((items) => items.map((item) => item.id === id ? saved : item));
      setToast(`${saved.title} ${active ? "activated" : "paused"}`);
    } catch (error) {
      setToast(error.message || "Could not update the policy");
    }
  };

  const runProof = async (payload) => {
    setProofRunning(true);
    try {
      const run = await createProofRun(payload);
      setProofRuns((items) => [run, ...items]);
      refreshAudit();
      setToast(`Proof complete: ${run.report.readiness_score}/100 readiness`);
    } catch (error) {
      setToast(error.message || "Proof run failed");
    } finally {
      setProofRunning(false);
    }
  };

  const selectTicket = (id) => {
    queueScrollPosition.current = queueScrollRef.current?.scrollTop || 0;
    setSelectedId(id);
    setMobileCaseOpen(true);
  };

  const returnToQueue = () => {
    setMobileCaseOpen(false);
    window.requestAnimationFrame(() => {
      if (queueScrollRef.current) queueScrollRef.current.scrollTop = queueScrollPosition.current;
    });
  };

  const filterQueueByPriority = (priority) => {
    setFilters({ review: priority === "review", high: false, sla: priority === "sla", unassigned: priority === "unassigned", assignee: "all", channel: "all", urgency: "all", team: "all" });
    setMobileCaseOpen(false);
  };

  const filterQueueByAssignee = (assignee) => {
    setFilters({ review: false, high: false, sla: false, unassigned: false, assignee, channel: "all", urgency: "all", team: "all" });
    setActiveView("queue");
    setMobileCaseOpen(false);
  };

  const auditSensitiveReveal = async (ticket) => {
    try {
      await recordSensitiveReveal(ticket);
      refreshAudit();
      setToast("Sensitive information revealed and recorded in the audit trail");
    } catch (error) {
      setToast(error.message || "Could not record the sensitive-data reveal");
    }
  };

  const openTicketFromNotification = (id) => {
    setQuery("");
    setFilters({ review: false, high: false, sla: false, unassigned: false, assignee: "all", channel: "all", urgency: "all", team: "all" });
    setActiveView("queue");
    setSelectedId(id);
    setMobileCaseOpen(true);
  };

  if (!signedIn) return <SignedOutView onReturn={() => setSignedIn(true)} />;

  return (
    <div className="workspace-app bg-canvas text-ink">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <Rail activeView={activeView} onView={setActiveView} open={railOpen} onClose={() => setRailOpen(false)} user={currentUser} />
      <div className="workspace-shell lg:pl-[232px]">
        <Header activeView={activeView} onMenu={() => setRailOpen(true)} backend={backend} tickets={tickets} onOpenTicket={openTicketFromNotification} onView={setActiveView} user={currentUser} onLogout={() => { window.localStorage.removeItem("kora_token"); setSignedIn(false); }} />
        {backend.alert && <div className="system-alert"><WifiOff />AI service unavailable. Agents can continue with manual classification and review.</div>}
        <main id="main-content" tabIndex={-1} className={cn("workspace-main", activeView === "queue" ? "workspace-main-queue" : "workspace-main-scroll")}>
          {activeView === "queue" && <div className={cn("queue-view", mobileCaseOpen && "mobile-case-open")}><MetricsStrip tickets={tickets} automation={automation} governance={governance} onFilter={filterQueueByPriority} /><div className="workspace-grid"><QueuePane tickets={visibleTickets} selectedId={selectedId} onSelect={selectTicket} loading={loading} query={query} onQuery={setQuery} filters={activeFilters} onFilters={setFilters} selectedIds={selectedIds} onToggle={toggleSelected} onSelectAll={selectAll} onBulkApprove={bulkApprove} onBulkRoute={bulkRoute} bulkLoading={bulkLoading} automation={automation} governance={governance} scrollRef={queueScrollRef} /><CaseDetail ticket={selectedTicket} onApprove={approve} onEscalate={escalate} onRunAI={runLiveAI} onFeedback={saveFeedback} onResolve={resolve} onAssign={assignCase} onAddNote={saveCaseNote} onVerifyTransaction={verifyTransaction} onManualAssessment={saveHumanAssessment} onBack={returnToQueue} onSensitiveReveal={auditSensitiveReveal} aiLoading={aiLoadingId === selectedTicket.id} actionLoading={actionLoadingId === selectedTicket.id} backend={backend} automation={automation} governance={governance} memoryItems={memoryItems} memoryLoading={memoryLoading} conversation={conversation} notes={caseNotes} conversationLoading={conversationLoading} currentUser={currentUser} /></div></div>}
          {activeView === "insights" && <Suspense fallback={<div className="view-padding"><Skeleton className="h-[420px] w-full" /></div>}><InsightsView tickets={tickets} evaluationSummary={evaluationSummary} /></Suspense>}
          {activeView === "proof" && <HistoricalEvaluationView runs={proofRuns} onRun={runProof} running={proofRunning} backend={backend} />}
          {activeView === "audit" && <DecisionAuditView items={auditItems} loading={auditLoading} />}
          {activeView === "team" && <TeamView tickets={tickets} onFilterQueue={filterQueueByAssignee} />}
          {activeView === "settings" && <SettingsView automation={automation} onChange={setAutomation} onSave={saveAutomation} saving={settingsSaving} tickets={tickets} integrations={integrations} jobs={jobs} policies={policies} onCreatePolicy={savePolicy} onTogglePolicy={togglePolicy} policySaving={policySaving} />}
        </main>
      </div>
      {railOpen && <button className="fixed inset-0 z-30 bg-ink/20 lg:hidden" onClick={() => setRailOpen(false)} aria-label="Close navigation overlay" />}
      <div role="status" aria-live="polite" className={cn("fixed bottom-5 right-5 z-50 flex items-center gap-2 border border-ink bg-ink px-4 py-3 text-[11px] font-bold text-paper shadow-precision transition-all", toast ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-3 opacity-0")}><CheckCircle2 className="size-4 text-accent" />{toast}</div>
    </div>
  );
}

export default function App() {
  return <DashboardApp />;
}
