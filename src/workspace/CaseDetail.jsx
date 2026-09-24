import { useEffect, useRef, useState } from "react";
import {
  Activity, ArrowLeft, Check, CheckCircle2, ChevronDown, CircleAlert, Clock3, CreditCard, Database, Eye,
  LoaderCircle, MessageCircle, MessagesSquare, MoreHorizontal, Route, ShieldAlert, ShieldCheck, Sparkles, Timer,
  UserPlus, UserRoundCheck, Users, Wrench
} from "lucide-react";
import { cn } from "../lib/utils";
import {
  HANDLED_STATES, MAX_NOTE_LENGTH, MAX_REPLY_LENGTH, automationDecision, formatClock, formatDate, formatRelative,
  intentOptions, isGuardrailEscalated, isProcessed, maskSensitive, operationalState, slaState, teamOptions, urgencyOptions
} from "../lib/tickets";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Skeleton } from "../components/ui/skeleton";
import { ScrollArea } from "../components/ui/scroll-area";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "../components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";

const labels = { amount: "Amount", transactionId: "Transaction ID", orderId: "Order ID", account: "Account", card: "Card" };
const EMPTY_CORRECTION = { intent: "", urgency: "", route: "", reason: "" };
const MIN_OVERRIDE_NOTE = 10;

function EntityTag({ label, value }) {
  return <div className="rounded-[11px] bg-muted-surface px-3 py-2.5"><span className="block text-[12px] text-ink-faint">{label}</span><strong className="mt-1 block text-[13px] font-semibold">{maskSensitive(value)}</strong></div>;
}

function OptionSelect({ label, value, options, onChange, keepLabel }) {
  return (
    <label>{label}
      <Select value={value || (keepLabel ? "__keep__" : undefined)} onValueChange={(next) => onChange(next === "__keep__" ? "" : next)}>
        <SelectTrigger><SelectValue placeholder="Select" /></SelectTrigger>
        <SelectContent>
          {keepLabel && <SelectItem value="__keep__">Keep {keepLabel}</SelectItem>}
          {options.map((option) => <SelectItem key={option} value={option}>{option}</SelectItem>)}
        </SelectContent>
      </Select>
    </label>
  );
}

const handledCopy = {
  approved: "Reply approved and recorded. Nothing is sent until a delivery channel is connected.",
  queued: "Reply approved and queued for delivery.",
  sent: "Reply sent. Waiting on the customer.",
  delivered: "Reply delivered. Waiting on the customer."
};

export default function CaseDetail({
  ticket, now, onApprove, onEscalate, onRunAI, onFeedback, onResolve, onAssign, onAddNote, onVerifyTransaction,
  onManualAssessment, onBack, onSensitiveReveal, aiLoading, actionLoading, backend, integrations,
  memoryItems = [], memoryLoading, conversation = [], notes = [], conversationLoading, currentUser
}) {
  const [draft, setDraft] = useState(ticket.response || "");
  const [correction, setCorrection] = useState(EMPTY_CORRECTION);
  const [noteDraft, setNoteDraft] = useState("");
  const [overrideNote, setOverrideNote] = useState("");
  const [revealed, setRevealed] = useState(false);
  const conversationViewportRef = useRef(null);
  useEffect(() => {
    setDraft(ticket.response || "");
    setCorrection(EMPTY_CORRECTION);
    setNoteDraft("");
    setOverrideNote("");
    setRevealed(false);
  }, [ticket.id, ticket.response]);

  const decision = automationDecision(ticket);
  const delivery = ticket.channel === "email" ? integrations?.email : integrations?.whatsapp;
  const canSend = integrations?.mode === "live" && delivery?.configured;
  const paystackReady = Boolean(integrations?.paystack?.configured);
  const sla = slaState(ticket, now);
  const entities = Object.entries(ticket.entities || {}).filter(([, value]) => value);
  const lifecycleState = ticket.lifecycle?.state;
  const resolved = lifecycleState === "resolved";
  const handled = HANDLED_STATES.has(lifecycleState);
  const guardrail = isGuardrailEscalated(ticket);
  const isManager = ["support_manager", "admin"].includes(currentUser?.role);
  const canOverride = isManager || (ticket.lifecycle?.assigned_to && ticket.lifecycle.assigned_to === currentUser?.display_name);
  const mask = (value) => (revealed ? value : maskSensitive(value));
  const hasMaskedContent = ticket.message !== maskSensitive(ticket.message) || conversation.some((message) => message.body !== maskSensitive(message.body));
  const reveal = () => { setRevealed(true); onSensitiveReveal?.(ticket); };
  const scrollConversationToLatest = () => window.requestAnimationFrame(() => {
    const viewport = conversationViewportRef.current;
    if (viewport) viewport.scrollTo({ top: viewport.scrollHeight, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });
  useEffect(() => { if (!conversationLoading && conversation.length) scrollConversationToLatest(); }, [conversationLoading, conversation.length, ticket.id]);
  const addNote = async () => {
    const mentions = [...noteDraft.matchAll(/@([A-Za-z][\w.-]*)/g)].map((match) => match[1]);
    if (await onAddNote(ticket.id, noteDraft, mentions)) setNoteDraft("");
  };

  let primaryActions;
  if (!isProcessed(ticket)) {
    primaryActions = backend.configured
      ? <Button disabled><LoaderCircle className={cn("size-4", aiLoading && "animate-spin")} />{aiLoading ? "Classifying conversation" : "Classification in progress"}</Button>
      : <Button disabled={actionLoading || !correction.intent || !correction.urgency || !correction.route || draft.trim().length < 2} onClick={() => onManualAssessment(ticket, { ...correction, response: draft })}><UserRoundCheck className="size-4" />Save assessment</Button>;
  } else if (resolved) {
    primaryActions = <p><CheckCircle2 className="inline size-4" /> This case is resolved. A new customer message will reopen it.</p>;
  } else if (handled) {
    primaryActions = <><p>{handledCopy[lifecycleState]}</p><Button disabled={actionLoading} onClick={() => onResolve(ticket.id)}><CheckCircle2 className="size-4" />Mark resolved</Button></>;
  } else if (guardrail && !canOverride) {
    primaryActions = <><p>A guardrail flagged this case. Only the assigned specialist or a manager can approve a reply.</p><Button disabled={actionLoading} onClick={() => onEscalate(ticket.id, draft)} variant="outline"><Users className="size-4" />Assign to specialist</Button></>;
  } else {
    const overrideReady = !guardrail || overrideNote.trim().length >= MIN_OVERRIDE_NOTE;
    primaryActions = <>
      {guardrail && <label className="draft-field"><span>Specialist review note (required)</span><textarea value={overrideNote} onChange={(event) => setOverrideNote(event.target.value)} maxLength={1000} rows={2} placeholder="Why is this reply safe to send despite the guardrail?" /></label>}
      <Button disabled={actionLoading} onClick={() => onEscalate(ticket.id, draft)} variant="outline"><Users className="size-4" />Assign to specialist</Button>
      <Button disabled={actionLoading || !draft.trim() || !overrideReady} onClick={() => onApprove(ticket.id, draft, guardrail ? overrideNote.trim() : null)}>{actionLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Check className="size-4" />}{guardrail ? "Approve reviewed reply" : canSend ? "Approve and send" : "Approve draft"}</Button>
    </>;
  }

  return (
    <article className="detail-scroll case-workspace" aria-labelledby="ticket-title">
      <header className="case-header">
        <div className="flex min-w-0 items-center gap-3"><Button variant="ghost" size="icon" className="case-back-button" onClick={onBack} aria-label="Back to queue"><ArrowLeft className="size-4" /></Button><div className="min-w-0"><p className="case-kicker">{ticket.id} · <span className="capitalize">{ticket.channel}</span></p><h2 id="ticket-title">{ticket.customer.name}</h2></div></div>
        <div className="case-header-actions">
          {ticket.lifecycle?.assigned_to ? <Badge variant="outline"><UserRoundCheck className="size-3" />{ticket.lifecycle.assigned_to}</Badge> : <Button variant="outline" disabled={actionLoading} onClick={() => onAssign(ticket.id, "me", null)}><UserPlus className="size-4" />Claim case</Button>}
          {sla && <Badge variant={sla.overdue ? "strong" : "outline"}><Timer className="size-3" />{sla.label}</Badge>}
          <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="More case actions"><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => navigator.clipboard?.writeText(`${window.location.origin}/app?case=${encodeURIComponent(ticket.id)}`)}>Copy case link</DropdownMenuItem>
            {ticket.lifecycle?.assigned_to && <DropdownMenuItem onSelect={() => onAssign(ticket.id, null, ticket.lifecycle.assigned_to)}>Release ownership</DropdownMenuItem>}
            {isProcessed(ticket) && !resolved && <DropdownMenuItem onSelect={() => onResolve(ticket.id)}>Mark resolved</DropdownMenuItem>}
          </DropdownMenuContent></DropdownMenu>
        </div>
      </header>
      <div className="case-context-bar"><span><span className="context-dot" />{operationalState(ticket) === "pending" ? "Awaiting triage" : operationalState(ticket)}</span><span><Route className="size-3.5" />{ticket.route}</span><span><Clock3 className="size-3.5" />Waiting {formatRelative(ticket.minutesAgo)}</span></div>
      <div className="case-body">
        <section className="customer-message-section" aria-labelledby="customer-message-title">
          <div className="case-section-heading"><h3 id="customer-message-title">Customer message</h3><span><Clock3 />{formatClock(ticket)}</span></div>
          {ticket.subject && <p className="message-subject">{ticket.subject}</p>}
          <blockquote>“{mask(ticket.message)}”</blockquote>
          {!revealed && hasMaskedContent && <Button variant="ghost" onClick={reveal}><Eye className="size-4" />Reveal sensitive details</Button>}
          {entities.length > 0 && <div className="entity-list">{entities.map(([key, value]) => <EntityTag key={key} label={labels[key]} value={value} />)}</div>}
          {(conversationLoading || conversation.length > 0) && <details className="case-disclosure" onToggle={(event) => event.currentTarget.open && scrollConversationToLatest()}><summary><span><MessagesSquare />Conversation history</span><span>{conversation.length} messages <ChevronDown /></span></summary><ScrollArea className="conversation-scroll" viewportRef={conversationViewportRef}><div className="disclosure-content">{conversationLoading ? <Skeleton className="h-20 w-full" /> : conversation.map((message) => <div key={message.id} className={cn("conversation-message", message.direction === "outbound" && "conversation-message-outbound")}><span>{message.direction === "outbound" ? "Agent response" : "Customer"} · {message.delivery_status}</span><p>{mask(message.body)}</p></div>)}</div></ScrollArea></details>}
        </section>
        <div className="case-decision-grid">
          <section className="human-decision" aria-labelledby="agent-decision-title">
            <h3 id="agent-decision-title">Review & respond</h3>
            <div className={cn("authoritative-state", decision.state === "auto" && "authoritative-state-safe")}><ShieldAlert /><div><strong>{guardrail ? ticket.escalationReason : decision.reason}</strong><p>The agent remains accountable for the next action.</p></div></div>
            {ticket.deliveryNote && <div className="authoritative-state" role="status"><CircleAlert /><div><strong>{ticket.status}</strong><p>{ticket.deliveryNote}</p></div></div>}
            {!isProcessed(ticket) && !backend.configured && <div className="classification-fields">
              <OptionSelect label="Issue" value={correction.intent} options={intentOptions} onChange={(intent) => setCorrection({ ...correction, intent })} />
              <OptionSelect label="Urgency" value={correction.urgency} options={urgencyOptions} onChange={(urgency) => setCorrection({ ...correction, urgency })} />
              <OptionSelect label="Team" value={correction.route} options={teamOptions} onChange={(route) => setCorrection({ ...correction, route })} />
            </div>}
            <label className="draft-field"><span>Response draft</span><textarea value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={MAX_REPLY_LENGTH} disabled={(!isProcessed(ticket) && backend.configured) || resolved || handled} placeholder={!backend.configured ? "Write a human-owned response while the AI service is unavailable." : "A suggested draft will appear here."} rows={5} /></label>
            <div className="draft-meta"><span aria-live="polite">{draft.length} / {MAX_REPLY_LENGTH} characters</span><span>{ticket.customer.notes?.some((note) => note.includes("Pidgin")) ? "Pidgin aware" : "English"}</span></div>
            <div className="case-primary-actions">
              {primaryActions}
              {!canSend && isProcessed(ticket) && !resolved && !handled && <p>Approval is recorded in Kora. Nothing is sent until {ticket.channel === "email" ? "email" : "WhatsApp"} is connected.</p>}
            </div>
            <details className="case-disclosure"><summary><span><MessageCircle />Internal notes</span><span>{notes.length} notes <ChevronDown /></span></summary><div className="disclosure-content notes-content">{notes.slice(0, 3).map((note) => <div key={note.id}><strong>{note.actor}</strong><time>{formatDate(note.created_at)}</time><p>{note.body}</p></div>)}<textarea value={noteDraft} onChange={(event) => setNoteDraft(event.target.value)} maxLength={MAX_NOTE_LENGTH} rows={3} placeholder={`Add a private note. Use @${currentUser?.display_name?.split(" ")[0] || "teammate"} to mention someone.`} /><Button variant="outline" disabled={noteDraft.trim().length < 2 || actionLoading} onClick={addNote}>Add private note</Button></div></details>
          </section>
          <section className="suggestion-panel" aria-labelledby="suggestion-title">
            <div className="suggestion-heading"><div><h3 id="suggestion-title"><Sparkles className="size-4" /> Triage intelligence</h3><p>Classification, evidence and customer context</p></div>{backend.configured && ticket.source !== "groq" && <Button onClick={() => onRunAI(ticket)} disabled={aiLoading} variant="ghost">{aiLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Sparkles className="size-4" />}Refresh</Button>}</div>
            <dl className="suggestion-summary">{[["Issue", ticket.intent], ["Urgency", ticket.urgency], ["Team", ticket.route], ["Confidence", isProcessed(ticket) ? `${Math.round(ticket.confidence * 100)}%` : "Pending"]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
            {isProcessed(ticket) && <details className="case-disclosure"><summary><span><Wrench />Edit classification</span><ChevronDown /></summary><div className="disclosure-content classification-fields">
              <OptionSelect label="Issue" value={correction.intent} options={intentOptions} keepLabel={ticket.intent} onChange={(intent) => setCorrection({ ...correction, intent })} />
              <OptionSelect label="Urgency" value={correction.urgency} options={urgencyOptions} keepLabel={ticket.urgency} onChange={(urgency) => setCorrection({ ...correction, urgency })} />
              <OptionSelect label="Team" value={correction.route} options={teamOptions} keepLabel={ticket.route} onChange={(route) => setCorrection({ ...correction, route })} />
              <label>Reason<input value={correction.reason} maxLength={1000} onChange={(event) => setCorrection({ ...correction, reason: event.target.value })} placeholder="Why is this changing?" /></label>
              <Button variant="outline" disabled={actionLoading || (!correction.intent && !correction.urgency && !correction.route)} onClick={() => onFeedback(ticket.id, correction)}>Save classification</Button>
            </div></details>}
            <details className="case-disclosure"><summary><span><ShieldCheck />Evidence and policy</span><ChevronDown /></summary><div className="disclosure-content evidence-content"><h4>Evidence used</h4>{ticket.evidence?.length ? <ol>{ticket.evidence.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ol> : <p>No evidence available yet.</p>}<h4>Approved policy sources</h4>{ticket.policyCitations?.length ? ticket.policyCitations.map((citation) => <div key={citation.id}><strong>{citation.title} v{citation.version}</strong><p>{citation.excerpt}</p></div>) : <p>No approved policy matched. The draft must remain human-reviewed.</p>}</div></details>
            <details className="case-disclosure"><summary><span><Database />Customer history</span><span>{ticket.memoryUsed ? "Used" : "Not used"} <ChevronDown /></span></summary><div className="disclosure-content memory-content">{memoryLoading ? <Skeleton className="h-16 w-full" /> : memoryItems.length ? memoryItems.slice(0, 2).map((memory) => <div key={`${memory.case_id}-${memory.created_at}`}><strong>{memory.case_id}</strong><time>{formatDate(memory.created_at)}</time><p>{memory.summary}</p></div>) : <p>No previous case history is available.</p>}</div></details>
            {ticket.entities?.transactionId && <div className="verification-row"><div><strong><CreditCard />Transaction verification</strong><p>{ticket.verifiedTransaction ? `Paystack reports ${ticket.verifiedTransaction.status}.` : paystackReady ? "Verification is available for this reference." : "Transaction verification unavailable."}</p></div><Button variant="outline" disabled={actionLoading || !paystackReady} onClick={() => onVerifyTransaction(ticket)}>{ticket.verifiedTransaction ? "Verify again" : "Verify"}</Button></div>}
            <details className="case-disclosure"><summary><span><Activity />Technical details</span><ChevronDown /></summary><div className="disclosure-content technical-details"><p>Source: {ticket.source || "pending"}</p><p>Model: {ticket.model || "not available"}</p><p>Processing time: {ticket.processingMs == null ? "not available" : `${ticket.processingMs} ms`}</p></div></details>
          </section>
        </div>
      </div>
    </article>
  );
}
