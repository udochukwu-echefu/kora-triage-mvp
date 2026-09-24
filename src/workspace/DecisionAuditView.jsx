import { lazy, Suspense, useState } from "react";
import { Activity, BookOpenCheck, Bot, ChevronDown, ChevronRight, Download, Search, UserRoundCheck, X } from "lucide-react";
import { cn } from "../lib/utils";
import { downloadFile, toCsv } from "../lib/tickets";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Skeleton } from "../components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";

const AuditDatePicker = lazy(() => import("../components/AuditDatePicker"));

const auditLabels = {
  triage: "Automated classification",
  human_routed: "Routed by agent",
  human_escalated: "Assigned to specialist",
  human_approved: "Approved by agent",
  safety_policy_auto_approved: "Auto-approved by safety policy",
  confidence_auto_approved: "Legacy confidence approval",
  policy_created: "Policy approved",
  proof_run_completed: "Historical evaluation completed",
  sensitive_data_revealed: "Sensitive data revealed",
  message_received: "Customer message received",
  response_sent: "Reply sent",
  delivery_updated: "Delivery receipt",
  delivery_cancelled: "Send cancelled for re-review",
  delivery_failed: "Delivery failed",
  delivery_retry_scheduled: "Delivery retry scheduled",
  case_resolved: "Case resolved",
  case_assignment_changed: "Ownership changed",
  internal_note_added: "Internal note added",
  human_feedback: "Classification corrected",
  manual_triage: "Manual assessment",
  transaction_verified: "Transaction verified",
  automation_settings_changed: "Automation settings changed",
  policy_activated: "Policy activated",
  policy_paused: "Policy paused"
};
export default function DecisionAuditView({ items, loading }) {
  const [search, setSearch] = useState("");
  const [eventType, setEventType] = useState("all");
  const [actor, setActor] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [scope, setScope] = useState("all");
  const [selectedEventId, setSelectedEventId] = useState(null);
  const displayActor = (item) => item.event_type === "triage" ? "Kora automation" : item.actor || "System";
  const eventScope = (item) => {
    if (["triage", "safety_policy_auto_approved", "confidence_auto_approved"].includes(item.event_type)) return "automation";
    if (["policy_created", "policy_activated", "policy_paused", "proof_run_completed", "automation_settings_changed"].includes(item.event_type)) return "governance";
    return "human";
  };
  const eventName = (item) => auditLabels[item.event_type] || item.event_type.replaceAll("_", " ");
  const decisionSummary = (item) => item.decision?.intent || item.decision?.status || "Recorded action";
  const reason = (item) => item.guardrails?.reason || item.decision?.evidence?.join("; ") || "Agent decision";
  const filtered = items.filter((item) => {
    const haystack = `${item.case_id} ${item.customer_id} ${item.event_type} ${eventName(item)} ${decisionSummary(item)} ${displayActor(item)} ${reason(item)}`.toLowerCase();
    return (!search || haystack.includes(search.toLowerCase())) && (scope === "all" || eventScope(item) === scope) && (eventType === "all" || item.event_type === eventType) && (actor === "all" || displayActor(item) === actor) && (!dateFrom || new Date(item.created_at) >= new Date(`${dateFrom}T00:00:00`));
  });
  const exportCsv = () => downloadFile("kora-filtered-audit.csv", toCsv([["time", "case", "customer", "event", "actor", "decision", "reason"], ...filtered.map((item) => [item.created_at, item.case_id, item.customer_id, eventName(item), displayActor(item), decisionSummary(item), reason(item)])]));
  const events = [...new Set(items.map((item) => item.event_type))];
  const actors = [...new Set(items.map(displayActor))];
  const hasFilters = Boolean(search || dateFrom || eventType !== "all" || actor !== "all" || scope !== "all");
  const clearFilters = () => { setSearch(""); setDateFrom(""); setEventType("all"); setActor("all"); setScope("all"); };
  const selectedItem = filtered.find((item) => item.id === selectedEventId) || filtered[0] || null;
  const scopeOptions = [
    { key: "all", label: "All activity", description: "Complete decision record", icon: Activity, count: items.length },
    { key: "automation", label: "Automation", description: "Classifications and policy actions", icon: Bot, count: items.filter((item) => eventScope(item) === "automation").length },
    { key: "human", label: "Human actions", description: "Agent decisions and access", icon: UserRoundCheck, count: items.filter((item) => eventScope(item) === "human").length },
    { key: "governance", label: "Governance", description: "Policies and evaluations", icon: BookOpenCheck, count: items.filter((item) => eventScope(item) === "governance").length }
  ];
  const scopeIcon = (item) => eventScope(item) === "automation" ? Bot : eventScope(item) === "governance" ? BookOpenCheck : UserRoundCheck;
  const dateLabel = (value) => new Date(value).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  const timeLabel = (value) => new Date(value).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return (
    <div className="view-padding audit-page-v2">
      <section className="audit-overview" aria-labelledby="audit-overview-title">
        <div className="audit-overview-heading">
          <div><p className="section-label">Persisted decision record</p><h2 id="audit-overview-title">Every decision, traceable</h2><p>Investigate automated decisions, human interventions, and governance changes without losing the surrounding context.</p></div>
          <Button variant="outline" onClick={exportCsv} disabled={!filtered.length}><Download className="size-4" />Export results</Button>
        </div>
        <div className="audit-scope-grid" aria-label="Filter audit events by activity scope">
          {scopeOptions.map(({ key, label, description, icon: Icon, count }) => <button key={key} type="button" className={cn(scope === key && "is-active")} aria-pressed={scope === key} onClick={() => setScope(key)}><span className="audit-scope-icon"><Icon aria-hidden="true" /></span><span><strong>{label}</strong><small>{description}</small></span><b>{count}</b></button>)}
        </div>
      </section>

      <section className="audit-log-shell" aria-labelledby="activity-log-title">
        <header className="audit-log-header"><div><h2 id="activity-log-title">Activity log</h2><p>Newest events first · loaded from Kora’s persisted record</p></div><span><strong>{filtered.length}</strong> of {items.length} events</span></header>
        <div className="audit-filter-panel" aria-label="Audit filters">
          <div className="audit-filters">
            <div className="audit-search"><Search className="size-4" aria-hidden="true" /><span className="sr-only">Search audit trail</span><Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search case, decision, actor or reason" /></div>
            <Suspense fallback={<Skeleton className="h-11 w-full" />}><AuditDatePicker value={dateFrom} onChange={setDateFrom} /></Suspense>
            <Select value={eventType} onValueChange={setEventType}><SelectTrigger aria-label="Event type"><SelectValue placeholder="Event type" /></SelectTrigger><SelectContent><SelectItem value="all">All event types</SelectItem>{events.map((value) => <SelectItem key={value} value={value}>{auditLabels[value] || value.replaceAll("_", " ")}</SelectItem>)}</SelectContent></Select>
            <Select value={actor} onValueChange={setActor}><SelectTrigger aria-label="Actor"><SelectValue placeholder="Actor" /></SelectTrigger><SelectContent><SelectItem value="all">All actors</SelectItem>{actors.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select>
          </div>
          <div className="audit-filter-summary"><p>{hasFilters ? "Filters are narrowing the persisted record." : "Search or filter to begin an investigation."}</p>{hasFilters && <Button variant="ghost" size="sm" onClick={clearFilters}><X className="size-4" />Clear filters</Button>}</div>
        </div>

        {loading ? <div className="audit-loading"><Skeleton className="h-12 w-full" /><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /></div> : filtered.length ? <>
          <div className="audit-desktop-workspace">
            <div className="audit-table-scroll" tabIndex={0} role="region" aria-label="Decision audit events. Scroll horizontally to see all columns on smaller screens.">
              <Table className="audit-investigation-table" aria-labelledby="activity-log-title"><caption className="sr-only">Persisted automated, human, and governance activity in Kora.</caption><TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Activity</TableHead><TableHead>Case</TableHead><TableHead>Actor</TableHead><TableHead><span className="sr-only">Inspect event</span></TableHead></TableRow></TableHeader><TableBody>{filtered.map((item) => {
                const Icon = scopeIcon(item);
                const isSelected = selectedItem?.id === item.id;
                return <TableRow key={item.id} className={cn("audit-event-row", isSelected && "is-selected")} aria-selected={isSelected}><TableCell className="audit-time-cell"><time dateTime={item.created_at}><strong>{timeLabel(item.created_at)}</strong><small>{dateLabel(item.created_at)}</small></time></TableCell><TableCell className="audit-activity-cell"><span className={cn("audit-event-icon", `audit-event-icon-${eventScope(item)}`)}><Icon aria-hidden="true" /></span><span><strong>{eventName(item)}</strong><small>{decisionSummary(item)}</small></span></TableCell><TableCell className="audit-case-cell"><strong>{item.case_id}</strong><small>{item.customer_id}</small></TableCell><TableCell className="audit-actor-cell">{displayActor(item)}</TableCell><TableCell className="audit-inspect-cell"><Button variant="quiet" size="sm" onClick={() => setSelectedEventId(item.id)} aria-label={`Inspect ${eventName(item)} for ${item.case_id}`}>{isSelected ? "Selected" : "Inspect"}<ChevronRight aria-hidden="true" /></Button></TableCell></TableRow>;
              })}</TableBody></Table>
            </div>
            <aside className="audit-inspector" aria-labelledby="audit-inspector-title">
              {selectedItem && <><header><div><p className="section-label">Event details</p><h3 id="audit-inspector-title">{eventName(selectedItem)}</h3></div><span className={cn("audit-event-icon", `audit-event-icon-${eventScope(selectedItem)}`)}>{(() => { const Icon = scopeIcon(selectedItem); return <Icon aria-hidden="true" />; })()}</span></header><p className="audit-inspector-summary">{decisionSummary(selectedItem)}</p><dl><div><dt>Case</dt><dd>{selectedItem.case_id}<small>{selectedItem.customer_id}</small></dd></div><div><dt>Actor</dt><dd>{displayActor(selectedItem)}</dd></div><div><dt>Recorded</dt><dd>{dateLabel(selectedItem.created_at)}<small>{timeLabel(selectedItem.created_at)}</small></dd></div><div><dt>Technical source</dt><dd>{selectedItem.model || "Human action"}</dd></div></dl><div className="audit-reason"><span>Evidence or reason</span><p>{reason(selectedItem)}</p></div></>}
            </aside>
          </div>
          <div className="audit-mobile-list">{filtered.map((item) => { const Icon = scopeIcon(item); return <article key={item.id} className="audit-mobile-record"><div className="audit-record-heading"><span className={cn("audit-event-icon", `audit-event-icon-${eventScope(item)}`)}><Icon aria-hidden="true" /></span><div><span>{eventName(item)}</span><strong>{decisionSummary(item)}</strong></div><time dateTime={item.created_at}>{dateLabel(item.created_at)}<small>{timeLabel(item.created_at)}</small></time></div><dl><div><dt>Case</dt><dd>{item.case_id}</dd></div><div><dt>Actor</dt><dd>{displayActor(item)}</dd></div></dl><details className="audit-expansion"><summary>Inspect event <ChevronDown className="size-4" /></summary><div><p><strong>Evidence or reason:</strong> {reason(item)}</p><p><strong>Customer:</strong> {item.customer_id}</p><p><strong>Technical source:</strong> {item.model || "Human action"}</p></div></details></article>; })}</div>
        </> : <div className="audit-empty"><Search aria-hidden="true" /><strong>{items.length ? "No events match this investigation" : "No persisted decisions yet"}</strong><p>{items.length ? "Adjust the search, activity scope, date, event type, or actor to broaden the result." : "Run live triage to create the first auditable decision record."}</p>{hasFilters && <Button variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button>}</div>}
      </section>
    </div>
  );
}
