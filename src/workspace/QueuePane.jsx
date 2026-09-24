import { useMemo, useState } from "react";
import {
  Check, ChevronDown, CircleAlert, CircleUserRound, Filter, Inbox, Mail, MessageCircle, RefreshCw, Route,
  Search, ShieldCheck, Square, SquareCheckBig, Timer, UserRoundCheck, X
} from "lucide-react";
import { cn } from "../lib/utils";
import {
  formatRelative, initialsOf, isProcessed, lowRisk, maskSensitive, operationalState, policyState, slaState,
  teamOptions, urgencyOrder
} from "../lib/tickets";
import { Button } from "../components/ui/button";
import { Skeleton } from "../components/ui/skeleton";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "../components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";

export const EMPTY_FILTERS = { review: false, high: false, sla: false, unassigned: false, assignee: "all", channel: "all", urgency: "all", team: "all" };
const isUnassigned = (ticket) => !ticket.lifecycle?.assigned_to && !ticket.assignee;

export function filterTickets(tickets, query, filters, now) {
  const needle = query.trim().toLowerCase();
  return tickets.filter((ticket) => {
    const text = `${ticket.id} ${ticket.customer.name} ${ticket.message} ${ticket.intent}`.toLowerCase();
    return (!needle || text.includes(needle))
      && (!filters.review || policyState(ticket) === "mandatory")
      && (!filters.high || ["critical", "high"].includes(ticket.urgency))
      && (!filters.sla || Boolean(slaState(ticket, now)))
      && (!filters.unassigned || isUnassigned(ticket))
      && (filters.assignee === "all" || ticket.lifecycle?.assigned_to === filters.assignee || ticket.assignee === filters.assignee)
      && (filters.channel === "all" || ticket.channel === filters.channel)
      && (filters.urgency === "all" || ticket.urgency === filters.urgency)
      && (filters.team === "all" || ticket.route === filters.team);
  });
}

export function MetricsStrip({ tickets, filters, onFilter, now }) {
  const open = tickets.filter((ticket) => ticket.lifecycle?.state !== "resolved");
  const views = [
    { key: "all", label: "All conversations", icon: Inbox, value: tickets.length },
    { key: "review", label: "Needs review", icon: UserRoundCheck, value: open.filter((ticket) => policyState(ticket) === "mandatory").length },
    { key: "sla", label: "SLA risk", icon: Timer, value: open.filter((ticket) => slaState(ticket, now)).length },
    { key: "unassigned", label: "Unassigned", icon: CircleUserRound, value: open.filter(isUnassigned).length }
  ];
  const active = filters.review ? "review" : filters.sla ? "sla" : filters.unassigned ? "unassigned" : "all";
  return (
    <section className="queue-overview" aria-label="Queue priorities">
      <div className="queue-intro"><div><span className="section-label">Support inbox</span><h2>Every conversation, in focus.</h2></div><span className="queue-overview-note"><ShieldCheck className="size-4" />AI assisted. Human owned.</span></div>
      <div className="queue-views" aria-label="Conversation views">
        {views.map(({ key, label, icon: Icon, value }) => <button key={key} type="button" data-view={key} className={cn("queue-view-tab", active === key && "is-active")} aria-pressed={active === key} onClick={() => onFilter(key)}><Icon className="size-4" /><span>{label}</span><span className="view-count">{value}</span></button>)}
      </div>
    </section>
  );
}

function QueueLoading() {
  return <div aria-label="Loading tickets" className="divide-y divide-line">{Array.from({ length: 5 }).map((_, index) => <div key={index} className="space-y-3 p-5"><div className="flex justify-between"><Skeleton className="h-3 w-28" /><Skeleton className="h-3 w-8" /></div><Skeleton className="h-4 w-44" /><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-2/3" /></div>)}</div>;
}

function EmptyQueue({ onReset, hasTickets }) {
  return (
    <div className="grid min-h-[430px] place-items-center px-8 text-center">
      <div className="max-w-[280px]"><div className="mx-auto grid size-12 place-items-center border border-line-strong bg-muted-surface"><Inbox className="size-5" /></div>
        {hasTickets
          ? <><h3 className="mt-5 text-[17px] font-extrabold tracking-[-0.03em]">No tickets match this view</h3><p className="mt-2 text-sm leading-6 text-ink-muted">Clear the filters to return to the full support queue.</p><Button onClick={onReset} variant="outline" size="sm" className="mt-5">Reset filters</Button></>
          : <><h3 className="mt-5 text-[17px] font-extrabold tracking-[-0.03em]">No conversations yet</h3><p className="mt-2 text-sm leading-6 text-ink-muted">New WhatsApp and email messages appear here as they arrive.</p></>}
      </div>
    </div>
  );
}

export function QueueError({ message, onRetry }) {
  return (
    <div className="grid min-h-[430px] place-items-center px-8 text-center" role="alert">
      <div className="max-w-[300px]"><CircleAlert className="mx-auto size-6 text-accent-strong" /><h3 className="mt-4 text-[17px] font-extrabold tracking-[-0.03em]">The queue could not load</h3><p className="mt-2 text-sm leading-6 text-ink-muted">{message}</p><Button onClick={onRetry} variant="outline" size="sm" className="mt-5"><RefreshCw className="size-3.5" />Try again</Button></div>
    </div>
  );
}

export function EmptyCaseDetail() {
  return <section className="compact-empty m-4 grid min-h-[320px] place-items-center rounded-[10px] border border-line bg-canvas p-8 text-center"><div><Inbox className="mx-auto mb-3 size-6 text-ink-faint" /><strong className="text-sm">No case selected</strong><p className="mt-2 max-w-sm text-ink-muted">New inbound cases will appear here when they arrive.</p></div></section>;
}

function TicketRow({ ticket, selected, checked, onSelect, onCheck, now }) {
  const sla = slaState(ticket, now);
  const state = operationalState(ticket);
  const Channel = ticket.channel === "email" ? Mail : MessageCircle;
  return (
    <div data-ticket={ticket.id} className={cn("ticket-row group", selected && "bg-selected", checked && "ticket-checked")}>
      <button type="button" onClick={() => onCheck(ticket.id)} aria-label={`${checked ? "Deselect" : "Select"} ${ticket.id}`} aria-pressed={checked} className="ticket-select-control">{checked ? <SquareCheckBig className="size-4" /> : <Square className="size-4" />}</button>
      <button type="button" onClick={() => onSelect(ticket.id)} className="ticket-open" aria-pressed={selected} aria-label={`Open ${ticket.id}, ${ticket.customer.name}`}>
        <span className="ticket-person"><span className={cn("ticket-avatar", ticket.channel === "email" && "ticket-avatar-email")}>{initialsOf(ticket.customer.name)}</span><strong>{ticket.customer.name}</strong><time title={`Waiting ${formatRelative(ticket.minutesAgo)}`}>{formatRelative(ticket.minutesAgo)}</time></span>
        <span className="ticket-subject">{ticket.subject || (isProcessed(ticket) ? ticket.intent : "New support request")}</span>
        <span className="ticket-preview">{maskSensitive(ticket.message)}</span>
        <span className="ticket-footer"><span className="ticket-channel" title={ticket.channel === "email" ? "Email" : "WhatsApp"}><Channel />{ticket.id}</span>{sla ? <span className={cn("ticket-sla", sla.overdue && "is-overdue")}><Timer />{sla.label}</span> : <span className="ticket-state">{state === "pending" ? "Awaiting triage" : state}</span>}{selected && <span className="ticket-current" aria-label="Current conversation" />}</span>
      </button>
    </div>
  );
}

function FilterChip({ label, value, options, onChange }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={`Filter by ${label.toLowerCase()}`} className={cn("h-9 min-w-[118px] bg-paper", value !== "all" && "border-ink bg-selected")}>
        <span className="text-xs font-bold uppercase tracking-[0.06em] text-ink-faint">{label}</span>
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="start">
        {options.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

export default function QueuePane({ tickets, totalCount, now, selectedId, onSelect, loading, loadError, onRetry, query, onQuery, filters, onFilters, selectedIds = [], onToggle, onSelectAll, onBulkApprove, onBulkRoute, bulkLoading, scrollRef }) {
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sort, setSort] = useState("priority");
  const sortedTickets = useMemo(() => [...tickets].sort((a, b) => sort === "newest"
    ? a.minutesAgo - b.minutesAgo
    : sort === "oldest"
      ? b.minutesAgo - a.minutesAgo
      : urgencyOrder[a.urgency] - urgencyOrder[b.urgency] || b.minutesAgo - a.minutesAgo), [tickets, sort]);
  const filterCount = [filters.high, filters.assignee !== "all", filters.channel !== "all", filters.urgency !== "all", filters.team !== "all"].filter(Boolean).length;
  const reset = () => { onQuery(""); onFilters(EMPTY_FILTERS); };
  const allSelected = tickets.length > 0 && tickets.every((ticket) => selectedIds.includes(ticket.id));
  const selected = tickets.filter((ticket) => selectedIds.includes(ticket.id));
  const selectedLowRisk = selected.filter(lowRisk).length;
  const selectedRoutable = selected.filter(isProcessed).length;
  const hasFilters = query || Object.entries(filters).some(([key, value]) => value !== EMPTY_FILTERS[key]);
  return (
    <section className="queue-pane flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-paper" aria-labelledby="queue-heading">
      <div className="queue-tools">
        <div className="flex items-center justify-between"><h2 id="queue-heading" className="text-[16px] font-semibold tracking-[-0.025em]">Conversations <span className="queue-result-count">{tickets.length}</span></h2>
          <Button variant="outline" onClick={() => setFiltersOpen((value) => !value)} aria-expanded={filtersOpen} className="queue-filter-button"><Filter className="size-4" />Filters{filterCount > 0 && <span className="view-count">{filterCount}</span>}</Button>
        </div>
        <label className="queue-search mt-3 flex h-11 items-center gap-2 rounded-[12px] border border-line bg-canvas px-3 focus-within:border-ink focus-within:ring-2 focus-within:ring-ring"><Search className="size-4 text-ink-faint" /><span className="sr-only">Search tickets</span><input value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Search name, case or message" className="min-w-0 flex-1 bg-transparent text-[12px] font-semibold outline-none placeholder:text-ink-faint" /></label>
        <div className={cn("queue-filter-fields mt-3 flex-wrap gap-2", filtersOpen ? "flex" : "hidden")} aria-label="Ticket filters">
          <FilterChip label="Channel" value={filters.channel} options={[{ value: "all", label: "All channels" }, { value: "whatsapp", label: "WhatsApp" }, { value: "email", label: "Email" }]} onChange={(channel) => onFilters({ ...filters, channel })} />
          <FilterChip label="Urgency" value={filters.urgency} options={[{ value: "all", label: "All urgency" }, ...["critical", "high", "medium", "low"].map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) }))]} onChange={(urgency) => onFilters({ ...filters, urgency })} />
          <FilterChip label="Team" value={filters.team} options={[{ value: "all", label: "All teams" }, ...teamOptions.map((value) => ({ value, label: value }))]} onChange={(team) => onFilters({ ...filters, team })} />
          {hasFilters && <Button variant="ghost" size="sm" onClick={reset}><X className="size-3" />Clear</Button>}
        </div>
        <div className="active-filter-chips">
          {filters.review && <button onClick={() => onFilters({ ...filters, review: false })}>Needs review <X /></button>}
          {filters.sla && <button onClick={() => onFilters({ ...filters, sla: false })}>SLA risk <X /></button>}
          {filters.unassigned && <button onClick={() => onFilters({ ...filters, unassigned: false })}>Unassigned <X /></button>}
          {filters.assignee !== "all" && <button onClick={() => onFilters({ ...filters, assignee: "all" })}>{filters.assignee} <X /></button>}
        </div>
      </div>
      <div className="queue-selection-bar flex min-h-10 items-center justify-between border-b border-line px-4 py-1">
        <button type="button" onClick={() => onSelectAll(tickets.map((ticket) => ticket.id), !allSelected)} className="flex items-center gap-2 text-xs font-semibold text-ink-muted">{allSelected ? <SquareCheckBig className="size-4 text-ink" /> : <Square className="size-4" />}{selectedIds.length ? `${selectedIds.length} selected` : "Select all"}</button>
        {selectedIds.length === 0 && <Select value={sort} onValueChange={setSort}><SelectTrigger aria-label="Sort conversations" className="queue-sort"><SelectValue /></SelectTrigger><SelectContent align="end"><SelectItem value="priority">Priority first</SelectItem><SelectItem value="oldest">Oldest first</SelectItem><SelectItem value="newest">Newest first</SelectItem></SelectContent></Select>}
        {selectedIds.length > 0 && <div className="flex items-center gap-1.5">
          <Button size="sm" variant="outline" className="h-8 px-2.5 text-xs" disabled={!selectedLowRisk || bulkLoading} onClick={onBulkApprove} title="Only cases eligible under the automation policy can be bulk approved"><Check className="size-3" />Approve {selectedLowRisk || ""}</Button>
          <DropdownMenu><DropdownMenuTrigger asChild><Button size="sm" className="h-8 px-2.5 text-xs" disabled={bulkLoading || !selectedRoutable}><Route className="size-3" />Route {selectedRoutable || ""}<ChevronDown className="size-3" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">{teamOptions.map((team) => <DropdownMenuItem key={team} onSelect={() => onBulkRoute(team)}>{team}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu>
        </div>}
      </div>
      <div className="queue-scroll" ref={scrollRef}>
        {loading ? <QueueLoading /> : loadError ? <QueueError message={loadError} onRetry={onRetry} /> : tickets.length
          ? sortedTickets.map((ticket) => <TicketRow key={ticket.id} ticket={ticket} now={now} selected={selectedId === ticket.id} checked={selectedIds.includes(ticket.id)} onSelect={onSelect} onCheck={onToggle} />)
          : <EmptyQueue onReset={reset} hasTickets={totalCount > 0} />}
      </div>
    </section>
  );
}
