const JSON_HEADERS = { "Content-Type": "application/json" };

async function api(path, options = {}) {
  const token = window.localStorage.getItem("kora_token");
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
    throw new Error(payload.detail || `Request failed with status ${response.status}`);
  }
  return payload;
}

export function getBackendHealth() {
  return api("/api/health");
}

export function getBackendAudit(limit = 100) {
  return api(`/api/audit?limit=${encodeURIComponent(limit)}`);
}

export function getCases() {
  return api("/api/cases");
}

export function getCurrentUser() {
  return api("/api/auth/me");
}

export function getIntegrations() {
  return api("/api/integrations");
}

export function getEvaluationSummary() {
  return api("/api/evaluations/summary");
}

export function getEvaluationGate() {
  return api("/api/evaluations/gate");
}

export function getJobs(limit = 100) {
  return api(`/api/jobs?limit=${encodeURIComponent(limit)}`);
}

export function getCaseConversation(caseId) {
  return api(`/api/cases/${encodeURIComponent(caseId)}/conversation`);
}

export function getPolicies() {
  return api("/api/policies");
}

export function createPolicy(policy) {
  return api("/api/policies", {
    method: "POST",
    body: JSON.stringify(policy)
  });
}

export function setPolicyState(policyId, active) {
  return api(`/api/policies/${encodeURIComponent(policyId)}/state`, {
    method: "PUT",
    body: JSON.stringify({ active })
  });
}

export function getProofRuns() {
  return api("/api/proof-runs");
}

export function createProofRun(run) {
  return api("/api/proof-runs", {
    method: "POST",
    body: JSON.stringify(run)
  });
}

export function updateCaseAssignment(caseId, assignee, expectedAssignee = null) {
  return api(`/api/cases/${encodeURIComponent(caseId)}/assignment`, {
    method: "PUT",
    body: JSON.stringify({
      assignee,
      expected_assignee: expectedAssignee
    })
  });
}

export function getCaseNotes(caseId) {
  return api(`/api/cases/${encodeURIComponent(caseId)}/notes`);
}

export function addCaseNote(caseId, body, mentions = []) {
  return api(`/api/cases/${encodeURIComponent(caseId)}/notes`, {
    method: "POST",
    body: JSON.stringify({ body, mentions })
  });
}

export function verifyPaystackTransaction(ticket, reference) {
  return api(`/api/cases/${encodeURIComponent(ticket.id)}/verify-transaction`, {
    method: "POST",
    body: JSON.stringify({
      customer_id: ticket.customerId,
      reference
    })
  });
}

export function saveManualAssessment(ticket, assessment) {
  return api(`/api/cases/${encodeURIComponent(ticket.id)}/manual-assessment`, {
    method: "POST",
    body: JSON.stringify({
      customer_id: ticket.customerId,
      intent: assessment.intent,
      urgency: assessment.urgency,
      route: assessment.route,
      response: assessment.response
    })
  });
}

export function getAutomationSettings() {
  return api("/api/settings/automation");
}

export function updateAutomationSettings(settings) {
  return api("/api/settings/automation", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(settings)
  });
}

export function getCustomerMemory(customerId) {
  return api(`/api/customers/${encodeURIComponent(customerId)}/memory`);
}

export function runGroqTriage(ticket) {
  return api("/api/triage", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      case_id: ticket.id,
      channel: ticket.channel,
      message: ticket.message,
      subject: ticket.subject || null,
      customer: {
        customer_id: ticket.customerId,
        name: ticket.customer.name,
        previous_context: ticket.customer.previousContext || "",
        notes: ticket.customer.notes || []
      }
    })
  });
}

export function recordCaseAction(ticket, action, response = null, note = null) {
  return api(`/api/cases/${encodeURIComponent(ticket.id)}/${action}`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      actor: "Ada Okafor",
      customer_id: ticket.customerId,
      note,
      response
    })
  });
}

export function recordCaseRoute(ticket, team) {
  return api(`/api/cases/${encodeURIComponent(ticket.id)}/route`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      actor: "Ada Okafor",
      customer_id: ticket.customerId,
      team
    })
  });
}

export function recordCaseFeedback(ticket, feedback) {
  return api(`/api/cases/${encodeURIComponent(ticket.id)}/feedback`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      actor: "Ada Okafor",
      customer_id: ticket.customerId,
      corrected_intent: feedback.intent || null,
      corrected_urgency: feedback.urgency || null,
      corrected_route: feedback.route || null,
      response_accepted: feedback.responseAccepted ?? null,
      reason: feedback.reason || null
    })
  });
}

export function resolveCase(ticket, resolution) {
  return api(`/api/cases/${encodeURIComponent(ticket.id)}/resolve`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      actor: "Ada Okafor",
      customer_id: ticket.customerId,
      resolution
    })
  });
}
