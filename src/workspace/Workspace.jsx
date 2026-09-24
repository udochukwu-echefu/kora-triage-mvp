import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { WifiOff } from "lucide-react";
import { cn } from "../lib/utils";
import { isProcessed, lowRisk, ticketAgeMinutes, urgencyOrder } from "../lib/tickets";
import { Skeleton } from "../components/ui/skeleton";
import {
  UNAUTHORIZED_EVENT, addCaseNote, clearToken, createPolicy, createProofRun, getAutomationSettings, getBackendAudit,
  getBackendHealth, getCases, getCaseConversation, getCurrentUser, getCustomerMemory, getEvaluationSummary,
  getIntegrations, getPolicies, getProofRuns, getTeam, getToken, recordCaseAction, recordCaseFeedback, recordCaseRoute,
  recordSensitiveReveal, resolveCase, runGroqTriage, saveManualAssessment, setPolicyState, setTeamAvailability,
  setToken, updateAutomationSettings, updateCaseAssignment, verifyPaystackTransaction
} from "../api";
import Rail from "./Rail";
import Header from "./Header";
import Toast from "./Toast";
import QueuePane, { EMPTY_FILTERS, EmptyCaseDetail, MetricsStrip, filterTickets } from "./QueuePane";
import CaseDetail from "./CaseDetail";
import { DemoSignedOutView, SignInView } from "./AccessViews";

const InsightsView = lazy(() => import("../components/InsightsView"));
const HistoricalEvaluationView = lazy(() => import("./HistoricalEvaluationView"));
const DecisionAuditView = lazy(() => import("./DecisionAuditView"));
const TeamView = lazy(() => import("./TeamView"));
const SettingsView = lazy(() => import("./SettingsView"));

const POLL_MS = 15000;
const CLOCK_MS = 30000;
const DEFAULT_AUTOMATION = { enabled: false, auto_approve_threshold: 95, mandatory_review_threshold: 70 };

function usePageVisible() {
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return visible;
}

function ViewFallback() {
  return <div className="view-padding space-y-3"><Skeleton className="h-10 w-1/3" /><Skeleton className="h-40 w-full" /></div>;
}

export default function Workspace() {
  const [auth, setAuth] = useState({ state: "checking", error: "" });
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || "light");
  const [tickets, setTickets] = useState([]);
  const [activeView, setActiveView] = useState("queue");
  const [selectedId, setSelectedId] = useState(null);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [selectedIds, setSelectedIds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [railOpen, setRailOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const [backend, setBackend] = useState({ state: "checking", configured: false });
  const [now, setNow] = useState(() => Date.now());
  const [aiLoadingId, setAiLoadingId] = useState(null);
  const [actionLoadingId, setActionLoadingId] = useState(null);
  const [auditItems, setAuditItems] = useState([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [memoryItems, setMemoryItems] = useState([]);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [automation, setAutomation] = useState(DEFAULT_AUTOMATION);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);
  const [integrations, setIntegrations] = useState(null);
  const [evaluationSummary, setEvaluationSummary] = useState(null);
  const [conversation, setConversation] = useState([]);
  const [caseNotes, setCaseNotes] = useState([]);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [policies, setPolicies] = useState([]);
  const [policySaving, setPolicySaving] = useState(false);
  const [proofRuns, setProofRuns] = useState([]);
  const [proofRunning, setProofRunning] = useState(false);
  const [team, setTeam] = useState({ items: [], loading: true });
  const [mobileCaseOpen, setMobileCaseOpen] = useState(false);
  const visible = usePageVisible();
  const queueScrollRef = useRef(null);
  const queueScrollPosition = useRef(0);
  const memoryRequestId = useRef(0);
  const conversationRequestId = useRef(0);
  const linkedCaseId = useRef(new URLSearchParams(window.location.search).get("case"));
  const linkedCaseHandled = useRef(false);

  const notify = useCallback((message, tone = "success") => setToast({ message, tone, id: Date.now() }), []);
  const notifyError = useCallback((error, fallback) => notify(error?.message || fallback, "error"), [notify]);
  const dismissToast = useCallback(() => setToast(null), []);
  const isManager = ["support_manager", "admin"].includes(currentUser?.role);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#211d21" : "#fafaf9");
    try { window.localStorage.setItem("kora_theme", theme); } catch { /* Theme persistence is optional. */ }
  }, [theme]);

  // A tick keeps waiting times and SLA badges current between server polls.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const signOut = () => setAuth((current) => current.state === "signed-in" ? { state: "signed-out", error: "Your session is no longer valid. Sign in again." } : current);
    window.addEventListener(UNAUTHORIZED_EVENT, signOut);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, signOut);
  }, []);

  const checkSession = useCallback(async () => {
    try {
      const user = await getCurrentUser();
      setCurrentUser(user);
      setAuth({ state: "signed-in", error: "" });
      return true;
    } catch (error) {
      setAuth({ state: "signed-out", error: error.status === 401 ? (getToken() ? "That access token was not accepted." : "") : error.message });
      setLoading(false);
      return false;
    }
  }, []);

  useEffect(() => {
    let active = true;
    getBackendHealth()
      .then((health) => { if (active) { setBackend({ state: "online", ...health }); checkSession(); } })
      .catch(() => { if (active) { setBackend({ state: "offline", configured: false }); setLoading(false); setLoadError("The Kora API is not reachable. Check that the backend is running."); setAuth({ state: "signed-in", error: "" }); } });
    return () => { active = false; };
  }, [checkSession]);

  const refreshCases = useCallback(async ({ quiet = false } = {}) => {
    try {
      const result = await getCases();
      setTickets(result.items || []);
      setLoadError("");
    } catch (error) {
      if (!quiet) setLoadError(error.message || "Could not load conversations.");
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshAudit = useCallback(async () => {
    setAuditLoading(true);
    try {
      const result = await getBackendAudit(200);
      setAuditItems(result.items || []);
    } catch (error) {
      notifyError(error, "Could not load the audit trail");
    } finally {
      setAuditLoading(false);
    }
  }, [notifyError]);

  const refreshMemory = async (customerId) => {
    const requestId = ++memoryRequestId.current;
    setMemoryLoading(true);
    try {
      const result = await getCustomerMemory(customerId);
      if (requestId === memoryRequestId.current) setMemoryItems(result.items || []);
    } catch {
      if (requestId === memoryRequestId.current) setMemoryItems([]);
    } finally {
      if (requestId === memoryRequestId.current) setMemoryLoading(false);
    }
  };

  const refreshConversation = async (caseId, { quiet = false } = {}) => {
    const requestId = ++conversationRequestId.current;
    if (!quiet) setConversationLoading(true);
    try {
      const result = await getCaseConversation(caseId);
      if (requestId !== conversationRequestId.current) return;
      setConversation(result.messages || []);
      setCaseNotes(result.notes || []);
      setTickets((items) => items.map((ticket) => ticket.id === caseId && result.lifecycle ? { ...ticket, lifecycle: result.lifecycle } : ticket));
    } catch {
      if (requestId === conversationRequestId.current && !quiet) { setConversation([]); setCaseNotes([]); }
    } finally {
      if (requestId === conversationRequestId.current) setConversationLoading(false);
    }
  };

  // Initial load: the queue is essential; everything else degrades independently.
  useEffect(() => {
    if (auth.state !== "signed-in" || backend.state !== "online") return;
    let active = true;
    refreshCases();
    Promise.allSettled([getAutomationSettings(), getIntegrations(), getEvaluationSummary(), getTeam(), getPolicies(), isManager ? getProofRuns() : Promise.resolve({ items: [] })])
      .then(([settingsResult, integrationResult, evaluationResult, teamResult, policyResult, proofResult]) => {
        if (!active) return;
        if (settingsResult.status === "fulfilled") setAutomation(settingsResult.value);
        if (integrationResult.status === "fulfilled") setIntegrations(integrationResult.value);
        if (evaluationResult.status === "fulfilled") setEvaluationSummary(evaluationResult.value);
        setTeam({ items: teamResult.status === "fulfilled" ? teamResult.value.items || [] : [], loading: false });
        if (policyResult.status === "fulfilled") setPolicies(policyResult.value.items || []);
        if (proofResult.status === "fulfilled") setProofRuns(proofResult.value.items || []);
      });
    return () => { active = false; };
  }, [auth.state, backend.state, isManager, refreshCases]);

  // New inbound messages and background triage results appear without a reload.
  useEffect(() => {
    if (auth.state !== "signed-in" || backend.state !== "online" || !visible) return undefined;
    const timer = setInterval(() => {
      refreshCases({ quiet: true });
      if (selectedId) refreshConversation(selectedId, { quiet: true });
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [auth.state, backend.state, visible, selectedId, refreshCases]);

  // Poll a running historical evaluation until it finishes.
  const proofInProgress = proofRuns[0]?.status === "running";
  useEffect(() => {
    if (!proofInProgress || !visible) return undefined;
    const timer = setInterval(async () => {
      try {
        const result = await getProofRuns();
        setProofRuns(result.items || []);
        const latest = result.items?.[0];
        if (latest && latest.status !== "running") notify(latest.status.startsWith("complete") ? `Evaluation complete: ${latest.report.readiness_score}/100 readiness` : "Evaluation stopped before finishing", latest.status.startsWith("complete") ? "success" : "error");
      } catch { /* The next tick retries. */ }
    }, 5000);
    return () => clearInterval(timer);
  }, [proofInProgress, visible, notify]);

  useEffect(() => {
    if (activeView === "audit" && auth.state === "signed-in" && backend.state === "online") refreshAudit();
  }, [activeView, auth.state, backend.state, refreshAudit]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
    document.getElementById("main-content")?.scrollTo({ top: 0, behavior: "auto" });
  }, [activeView]);

  const liveTickets = useMemo(() => tickets.map((ticket) => ({ ...ticket, minutesAgo: ticketAgeMinutes(ticket, now) })), [tickets, now]);
  const visibleTickets = useMemo(
    () => filterTickets(liveTickets, query, filters, now).sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency] || b.minutesAgo - a.minutesAgo),
    [liveTickets, query, filters, now]
  );

  useEffect(() => {
    if (visibleTickets.length && !visibleTickets.some((ticket) => ticket.id === selectedId)) setSelectedId(visibleTickets[0].id);
  }, [visibleTickets, selectedId]);
  useEffect(() => {
    if (linkedCaseHandled.current || loading) return;
    const linkedTicket = tickets.find((ticket) => ticket.id === linkedCaseId.current);
    if (linkedTicket) {
      setSelectedId(linkedTicket.id);
      setMobileCaseOpen(true);
    }
    linkedCaseHandled.current = true;
  }, [loading, tickets]);
  const selectedTicket = liveTickets.find((ticket) => ticket.id === selectedId) || null;
  useEffect(() => {
    if (backend.state === "online" && auth.state === "signed-in" && selectedTicket) {
      refreshMemory(selectedTicket.customerId);
      refreshConversation(selectedTicket.id);
    } else if (!selectedTicket) {
      memoryRequestId.current += 1;
      conversationRequestId.current += 1;
      setMemoryItems([]);
      setConversation([]);
      setCaseNotes([]);
      setMemoryLoading(false);
      setConversationLoading(false);
    }
    // Only a different case (or customer) should trigger a reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backend.state, auth.state, selectedTicket?.customerId, selectedTicket?.id]);

  const patchTicket = (id, patch) => setTickets((items) => items.map((ticket) => ticket.id === id ? { ...ticket, ...(typeof patch === "function" ? patch(ticket) : patch) } : ticket));
  const withAction = async (id, work, fallback) => {
    setActionLoadingId(id);
    try {
      return await work();
    } catch (error) {
      notifyError(error, fallback);
      return null;
    } finally {
      setActionLoadingId(null);
    }
  };

  const runLiveAI = async (ticket) => {
    setAiLoadingId(ticket.id);
    try {
      await runGroqTriage(ticket);
      await refreshCases({ quiet: true });
      refreshAudit();
      refreshMemory(ticket.customerId);
      notify(`${ticket.id} classification is ready for review`);
    } catch (error) {
      notifyError(error, "Live triage failed");
    } finally {
      setAiLoadingId(null);
    }
  };

  const approve = (id, draft, note = null) => withAction(id, async () => {
    const ticket = tickets.find((item) => item.id === id);
    const result = await recordCaseAction(ticket, "approve", draft, note);
    patchTicket(id, (item) => ({ status: result.status === "queued" ? "Queued to send" : "Approved", escalated: false, lifecycle: { ...(item.lifecycle || {}), state: result.status === "queued" ? "queued" : "approved" } }));
    refreshAudit();
    refreshConversation(id, { quiet: true });
    notify(result.status === "queued" ? `${id} queued for delivery` : `${id} approval recorded`);
  }, "Approval failed");

  const escalate = (id, draft) => withAction(id, async () => {
    const ticket = tickets.find((item) => item.id === id);
    const result = await recordCaseAction(ticket, "escalate", draft);
    patchTicket(id, { status: "Assigned", escalated: true, ...(result.lifecycle ? { lifecycle: result.lifecycle } : {}) });
    refreshAudit();
    notify(`${id} assigned and recorded`);
  }, "Escalation failed");

  const saveFeedback = (id, feedback) => withAction(id, async () => {
    const ticket = tickets.find((item) => item.id === id);
    await recordCaseFeedback(ticket, feedback);
    patchTicket(id, (item) => ({ intent: feedback.intent || item.intent, urgency: feedback.urgency || item.urgency, route: feedback.route || item.route }));
    getEvaluationSummary().then(setEvaluationSummary).catch(() => {});
    refreshAudit();
    notify(`${id} correction recorded`);
  }, "Could not save the correction");

  const resolve = (id) => withAction(id, async () => {
    const ticket = tickets.find((item) => item.id === id);
    const result = await resolveCase(ticket, "Agent confirmed the customer issue is resolved.");
    patchTicket(id, { status: "Resolved", lifecycle: result.lifecycle });
    refreshAudit();
    notify(`${id} resolved`);
  }, "Could not resolve the case");

  const toggleSelected = (id) => setSelectedIds((ids) => ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]);
  const selectAll = (ids, checked) => setSelectedIds((current) => checked ? [...new Set([...current, ...ids])] : current.filter((id) => !ids.includes(id)));

  const runBulk = async (targets, action, describe) => {
    if (!targets.length) return;
    setBulkLoading(true);
    try {
      const results = await Promise.allSettled(targets.map(action));
      const succeeded = targets.filter((_, index) => results[index].status === "fulfilled").map((ticket) => ticket.id);
      const failed = targets.length - succeeded.length;
      setSelectedIds((ids) => ids.filter((id) => !succeeded.includes(id)));
      await refreshCases({ quiet: true });
      refreshAudit();
      notify(failed ? `${succeeded.length} ${describe}; ${failed} failed and remain selected` : `${succeeded.length} ${succeeded.length === 1 ? "case" : "cases"} ${describe}`, failed ? "error" : "success");
    } finally {
      setBulkLoading(false);
    }
  };
  const bulkApprove = () => runBulk(
    tickets.filter((ticket) => selectedIds.includes(ticket.id) && lowRisk(ticket)),
    (ticket) => recordCaseAction(ticket, "approve", ticket.response, null, { requireAutomationEligible: true }),
    "approved"
  );
  const bulkRoute = (team) => runBulk(
    tickets.filter((ticket) => selectedIds.includes(ticket.id) && isProcessed(ticket)),
    (ticket) => recordCaseRoute(ticket, team),
    `routed to ${team}`
  );

  const saveAutomation = async () => {
    setSettingsSaving(true);
    try {
      setAutomation(await updateAutomationSettings(automation));
      notify("Automation policy saved");
    } catch (error) {
      notifyError(error, "Could not save automation policy");
    } finally {
      setSettingsSaving(false);
    }
  };

  const assignCase = (id, assignee, expectedAssignee) => withAction(id, async () => {
    try {
      const result = await updateCaseAssignment(id, assignee, expectedAssignee);
      patchTicket(id, { assignee: result.assignee, lifecycle: result.lifecycle });
      refreshAudit();
      notify(result.assignee ? `${id} assigned to ${result.assignee}` : `${id} returned to the shared queue`);
    } catch (error) {
      refreshConversation(id, { quiet: true });
      throw error;
    }
  }, "Case ownership changed before your update");

  const saveCaseNote = async (id, body, mentions) => Boolean(await withAction(id, async () => {
    const note = await addCaseNote(id, body, mentions);
    setCaseNotes((items) => [note, ...items]);
    refreshAudit();
    notify(mentions.length ? `Private note added with ${mentions.length} mention${mentions.length === 1 ? "" : "s"}` : "Private note added");
    return true;
  }, "Could not add the private note"));

  const verifyTransaction = (ticket) => withAction(ticket.id, async () => {
    const reference = ticket.entities?.transactionId;
    if (!reference) return;
    const result = await verifyPaystackTransaction(ticket, reference);
    patchTicket(ticket.id, { verifiedTransaction: result });
    refreshAudit();
    notify(`${reference} verified as ${result.status}`);
  }, "Transaction verification failed");

  const saveHumanAssessment = (ticket, assessment) => withAction(ticket.id, async () => {
    const result = await saveManualAssessment(ticket, assessment);
    patchTicket(ticket.id, { ...result.ticket, lifecycle: result.lifecycle });
    refreshAudit();
    notify(`${ticket.id} moved to the human-owned manual queue`);
  }, "Could not save the manual assessment");

  const savePolicy = async (policy) => {
    setPolicySaving(true);
    try {
      const saved = await createPolicy(policy);
      setPolicies((items) => [saved, ...items]);
      refreshAudit();
      notify(`${saved.title} approved for grounding`);
      return saved;
    } catch (error) {
      notifyError(error, "Could not save the policy");
      return null;
    } finally {
      setPolicySaving(false);
    }
  };

  const togglePolicy = async (id, active) => {
    try {
      const saved = await setPolicyState(id, active);
      setPolicies((items) => items.map((item) => item.id === id ? saved : item));
      notify(`${saved.title} ${active ? "activated" : "paused"}`);
    } catch (error) {
      notifyError(error, "Could not update the policy");
    }
  };

  const runProof = async (payload) => {
    setProofRunning(true);
    try {
      const run = await createProofRun(payload);
      setProofRuns((items) => [run, ...items]);
      notify("Evaluation started. Results appear here when it finishes.");
    } catch (error) {
      notifyError(error, "Evaluation could not start");
    } finally {
      setProofRunning(false);
    }
  };

  const updateAvailability = async (memberId, availability) => {
    try {
      const saved = await setTeamAvailability(memberId, availability);
      setTeam((current) => ({ ...current, items: current.items.map((member) => member.id === memberId ? saved : member) }));
    } catch (error) {
      notifyError(error, "Could not update availability");
    }
  };

  const selectTicket = (id) => {
    queueScrollPosition.current = queueScrollRef.current?.scrollTop || 0;
    setSelectedId(id);
    setMobileCaseOpen(true);
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "auto" }));
  };

  const returnToQueue = () => {
    setMobileCaseOpen(false);
    window.requestAnimationFrame(() => {
      if (queueScrollRef.current) queueScrollRef.current.scrollTop = queueScrollPosition.current;
    });
  };

  const filterQueueByPriority = (priority) => {
    setFilters({ ...EMPTY_FILTERS, review: priority === "review", sla: priority === "sla", unassigned: priority === "unassigned" });
    setMobileCaseOpen(false);
  };

  const filterQueueByAssignee = (assignee) => {
    setFilters({ ...EMPTY_FILTERS, assignee });
    setActiveView("queue");
    setMobileCaseOpen(false);
  };

  const auditSensitiveReveal = async (ticket) => {
    try {
      await recordSensitiveReveal(ticket);
      refreshAudit();
      notify("Sensitive information revealed and recorded in the audit trail");
    } catch (error) {
      notifyError(error, "Could not record the sensitive-data reveal");
    }
  };

  const openTicketFromNotification = (id) => {
    setQuery("");
    setFilters(EMPTY_FILTERS);
    setActiveView("queue");
    setSelectedId(id);
    setMobileCaseOpen(true);
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "auto" }));
  };

  const logout = () => {
    clearToken();
    setTickets([]);
    setCurrentUser(null);
    setAuth({ state: currentUser?.auth_mode === "demo" ? "demo-left" : "signed-out", error: "" });
  };

  const signIn = async (token, remember) => {
    setToken(token, remember);
    setLoading(true);
    await checkSession();
  };

  if (auth.state === "checking") return <main className="grid min-h-screen place-items-center bg-canvas"><Skeleton className="h-10 w-48" /></main>;
  if (auth.state === "demo-left") return <DemoSignedOutView onReturn={() => { setLoading(true); checkSession(); }} />;
  if (auth.state === "signed-out") return <SignInView onSignIn={signIn} error={auth.error} />;

  return (
    <div className="workspace-app bg-canvas text-ink">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <Rail activeView={activeView} onView={setActiveView} open={railOpen} onClose={() => setRailOpen(false)} user={currentUser} />
      <div className="workspace-shell lg:pl-[268px]">
        <Header activeView={activeView} onMenu={() => setRailOpen(true)} backend={backend} tickets={liveTickets} now={now} onOpenTicket={openTicketFromNotification} onView={setActiveView} user={currentUser} theme={theme} onThemeToggle={() => setTheme((value) => value === "dark" ? "light" : "dark")} onLogout={logout} />
        {backend.alert && <div className="system-alert"><WifiOff />AI service unavailable. Agents can continue with manual classification and review.</div>}
        <main id="main-content" tabIndex={-1} className={cn("workspace-main", activeView === "queue" ? "workspace-main-queue" : "workspace-main-scroll")}>
          {activeView === "queue" && <div className={cn("queue-view", mobileCaseOpen && "mobile-case-open")}>
            <MetricsStrip tickets={liveTickets} filters={filters} onFilter={filterQueueByPriority} now={now} />
            <div className="workspace-grid">
              <QueuePane tickets={visibleTickets} totalCount={tickets.length} now={now} selectedId={selectedId} onSelect={selectTicket} loading={loading} loadError={loadError} onRetry={() => { setLoading(true); refreshCases(); }} query={query} onQuery={setQuery} filters={filters} onFilters={setFilters} selectedIds={selectedIds} onToggle={toggleSelected} onSelectAll={selectAll} onBulkApprove={bulkApprove} onBulkRoute={bulkRoute} bulkLoading={bulkLoading} scrollRef={queueScrollRef} />
              {selectedTicket ? <CaseDetail ticket={selectedTicket} now={now} onApprove={approve} onEscalate={escalate} onRunAI={runLiveAI} onFeedback={saveFeedback} onResolve={resolve} onAssign={assignCase} onAddNote={saveCaseNote} onVerifyTransaction={verifyTransaction} onManualAssessment={saveHumanAssessment} onBack={returnToQueue} onSensitiveReveal={auditSensitiveReveal} aiLoading={aiLoadingId === selectedTicket.id} actionLoading={actionLoadingId === selectedTicket.id} backend={backend} integrations={integrations} memoryItems={memoryItems} memoryLoading={memoryLoading} conversation={conversation} notes={caseNotes} conversationLoading={conversationLoading} currentUser={currentUser} /> : <EmptyCaseDetail />}
            </div>
          </div>}
          <Suspense fallback={<ViewFallback />}>
            {activeView === "insights" && <InsightsView tickets={liveTickets} evaluationSummary={evaluationSummary} now={now} />}
            {activeView === "proof" && (isManager
              ? <HistoricalEvaluationView runs={proofRuns} onRun={runProof} running={proofRunning} backend={backend} demoCaseLimit={currentUser?.auth_mode === "demo" ? integrations?.limits?.proof_cases : null} />
              : <div className="view-padding"><p className="text-ink-muted">Historical evaluation is available to support managers.</p></div>)}
            {activeView === "audit" && <DecisionAuditView items={auditItems} loading={auditLoading} />}
            {activeView === "team" && <TeamView tickets={liveTickets} members={team.items} loading={team.loading} currentUser={currentUser} onFilterQueue={filterQueueByAssignee} onSetAvailability={updateAvailability} />}
            {activeView === "settings" && <SettingsView automation={automation} onChange={setAutomation} onSave={saveAutomation} saving={settingsSaving} tickets={liveTickets} integrations={integrations} policies={policies} onCreatePolicy={savePolicy} onTogglePolicy={togglePolicy} policySaving={policySaving} canManage={isManager} />}
          </Suspense>
        </main>
      </div>
      {railOpen && <button className="fixed inset-0 z-30 bg-ink/20 lg:hidden" onClick={() => setRailOpen(false)} aria-label="Close navigation overlay" />}
      <Toast toast={toast} onDismiss={dismissToast} />
    </div>
  );
}
