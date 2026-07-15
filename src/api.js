const JSON_HEADERS = { "Content-Type": "application/json" };

async function api(path, options = {}) {
  const response = await fetch(path, options);
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
