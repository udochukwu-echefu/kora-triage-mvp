const JSON_HEADERS = { "Content-Type": "application/json" };
const TOKEN_KEY = "kora_token";
export const UNAUTHORIZED_EVENT = "kora:unauthorized";

// Session storage by default; local storage only when the user asks to be remembered.
export function getToken() {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY) || window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token, remember = false) {
  try {
    clearToken();
    (remember ? window.localStorage : window.sessionStorage).setItem(TOKEN_KEY, token);
  } catch {
    /* Storage can be unavailable in private windows; the session then lasts one page load. */
  }
}

export function clearToken() {
  try {
    window.sessionStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* Nothing stored. */
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function detailMessage(detail, status) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) return detail.map((item) => item.msg || String(item)).join("; ");
  if (status === 429) return "Too many requests. Please wait a moment and try again.";
  return `Request failed with status ${status}`;
}

async function api(path, options = {}) {
  const token = getToken();
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? JSON_HEADERS : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {})
    }
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(detailMessage(payload.detail, response.status), response.status);
  }
  return payload;
}

const post = (path, body, method = "POST") => api(path, { method, body: JSON.stringify(body) });
const casePath = (ticket, action) => `/api/cases/${encodeURIComponent(ticket.id)}/${action}`;

export const getBackendHealth = () => api("/api/health");
export const getBackendAudit = (limit = 100) => api(`/api/audit?limit=${encodeURIComponent(limit)}`);
export const getCases = () => api("/api/cases");
export const getCurrentUser = () => api("/api/auth/me");
export const getIntegrations = () => api("/api/integrations");
export const getEvaluationSummary = () => api("/api/evaluations/summary");
export const getEvaluationGate = () => api("/api/evaluations/gate");
export const getJobs = (limit = 100) => api(`/api/jobs?limit=${encodeURIComponent(limit)}`);
export const getCaseConversation = (caseId) => api(`/api/cases/${encodeURIComponent(caseId)}/conversation`);
export const getPolicies = () => api("/api/policies");
export const createPolicy = (policy) => post("/api/policies", policy);
export const setPolicyState = (policyId, active) => post(`/api/policies/${encodeURIComponent(policyId)}/state`, { active }, "PUT");
export const getProofRuns = () => api("/api/proof-runs");
export const createProofRun = (run) => post("/api/proof-runs", run);
export const getTeam = () => api("/api/team");
export const setTeamAvailability = (memberId, availability) => post(`/api/team/${encodeURIComponent(memberId)}/availability`, { availability }, "PUT");
export const getAutomationSettings = () => api("/api/settings/automation");
export const updateAutomationSettings = (settings) => post("/api/settings/automation", settings, "PUT");
export const getCustomerMemory = (customerId) => api(`/api/customers/${encodeURIComponent(customerId)}/memory`);

export const updateCaseAssignment = (caseId, assignee, expectedAssignee = null) =>
  post(`/api/cases/${encodeURIComponent(caseId)}/assignment`, { assignee, expected_assignee: expectedAssignee }, "PUT");

export const addCaseNote = (caseId, body, mentions = []) =>
  post(`/api/cases/${encodeURIComponent(caseId)}/notes`, { body, mentions });

export const verifyPaystackTransaction = (ticket, reference) =>
  post(casePath(ticket, "verify-transaction"), { customer_id: ticket.customerId, reference });

export const saveManualAssessment = (ticket, assessment) =>
  post(casePath(ticket, "manual-assessment"), {
    customer_id: ticket.customerId,
    intent: assessment.intent,
    urgency: assessment.urgency,
    route: assessment.route,
    response: assessment.response
  });

// The server re-reads the case; only identifiers are sent.
export const runGroqTriage = (ticket) => post("/api/triage", { case_id: ticket.id, customer_id: ticket.customerId });

export const recordCaseAction = (ticket, action, response = null, note = null, options = {}) =>
  post(casePath(ticket, action), {
    customer_id: ticket.customerId,
    note,
    response,
    require_automation_eligible: Boolean(options.requireAutomationEligible)
  });

export const recordSensitiveReveal = (ticket) =>
  post(casePath(ticket, "sensitive-reveal"), {
    customer_id: ticket.customerId,
    note: "Agent revealed masked customer information"
  });

export const recordCaseRoute = (ticket, team) => post(casePath(ticket, "route"), { customer_id: ticket.customerId, team });

export const recordCaseFeedback = (ticket, feedback) =>
  post(casePath(ticket, "feedback"), {
    customer_id: ticket.customerId,
    corrected_intent: feedback.intent || null,
    corrected_urgency: feedback.urgency || null,
    corrected_route: feedback.route || null,
    response_accepted: feedback.responseAccepted ?? null,
    reason: feedback.reason || null
  });

export const resolveCase = (ticket, resolution) =>
  post(casePath(ticket, "resolve"), { customer_id: ticket.customerId, resolution });
