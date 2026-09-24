// Shared, framework-free ticket logic. Covered by src/lib/tickets.test.js.

export const MAX_REPLY_LENGTH = 1200;
export const MAX_NOTE_LENGTH = 2000;
export const MAX_PROOF_CASES = 100;

export const urgencyOrder = { critical: 0, high: 1, medium: 2, low: 3, pending: 4 };
export const intentShort = {
  "Transfer pending": "Transfer", "Payment failed": "Payment", "Duplicate debit": "Card debit",
  "Fraud report": "Fraud", "Delivery delayed": "Delivery", "Delivery missing": "Delivery",
  "Delivery change": "Delivery", "Account access": "Account", "Account verification": "KYC",
  "Refund pending": "Refund"
};
export const teamOptions = ["Transfers", "Fraud", "Logistics", "Billing", "Account Support", "Compliance", "General Support"];
export const intentOptions = ["Transfer pending", "Payment failed", "Duplicate debit", "Fraud report", "Delivery delayed", "Delivery missing", "Delivery change", "Account access", "Account verification", "Refund pending", "General enquiry"];
export const urgencyOptions = ["low", "medium", "high", "critical"];

// Minutes allowed before the first/next reply, by urgency.
export const SLA_TARGET_MINUTES = { critical: 24, high: 48, medium: 120, low: 240 };
// Lifecycle states in which the customer is still waiting on the team.
export const AWAITING_REPLY_STATES = new Set(["new", "triaged", "review_required", "replied", "reopened", "failed"]);
// States in which a reply was already approved or sent.
export const HANDLED_STATES = new Set(["approved", "queued", "sent", "delivered"]);

export const isProcessed = (ticket) => Boolean(ticket?.source) && ticket.source !== "pending";

export function automationDecision(ticket) {
  if (!isProcessed(ticket)) return { state: "pending", reason: "Classification pending." };
  const recorded = ticket.automation;
  if (!recorded || typeof recorded.eligible !== "boolean" || !recorded.reason) {
    return { state: "mandatory", reason: "Human review required: this case has not been evaluated by the automation policy.", code: "not_evaluated" };
  }
  return { state: recorded.eligible ? "auto" : "mandatory", reason: recorded.reason, code: recorded.code };
}

export const policyState = (ticket) => automationDecision(ticket).state;
export const lowRisk = (ticket) => policyState(ticket) === "auto";

// A guardrail (not just a person) flagged this case; approving needs a specialist.
export const isGuardrailEscalated = (ticket) => Boolean(ticket?.escalated && ticket?.escalationReason);

export function minutesSince(value, now = Date.now()) {
  if (!value) return null;
  const time = new Date(value).getTime();
  if (Number.isNaN(time)) return null;
  return Math.max(0, Math.floor((now - time) / 60000));
}

// Age of the customer's latest message, recomputed on every clock tick.
export function ticketAgeMinutes(ticket, now = Date.now()) {
  return minutesSince(ticket?.lastMessageAt, now) ?? Number(ticket?.minutesAgo ?? 0);
}

export function slaState(ticket, now = Date.now()) {
  const state = ticket?.lifecycle?.state;
  if (state && !AWAITING_REPLY_STATES.has(state)) return null;
  if (["Approved", "Auto-approved", "Resolved", "Sent", "Queued to send"].includes(ticket?.status)) return null;
  const target = SLA_TARGET_MINUTES[ticket?.urgency] || 120;
  const remaining = target - ticketAgeMinutes(ticket, now);
  if (remaining <= 0) return { label: `${formatRelative(Math.abs(remaining))} overdue`, overdue: true };
  if (remaining <= Math.max(12, target * 0.2)) return { label: `${formatRelative(remaining)} to SLA`, overdue: false };
  return null;
}

export function operationalState(ticket) {
  if (!isProcessed(ticket)) return "pending";
  const lifecycle = ticket.lifecycle?.state;
  if (lifecycle === "resolved") return "Resolved";
  if (lifecycle === "queued") return "Queued to send";
  if (lifecycle === "approved") return "Approved";
  if (["sent", "delivered"].includes(lifecycle)) return "Waiting on customer";
  if (lifecycle === "replied" || lifecycle === "reopened") return "Customer replied";
  if (ticket.escalated || lifecycle === "review_required") return "Escalated";
  if (ticket.lifecycle?.assigned_to || ticket.assignee) return "Assigned";
  if (policyState(ticket) === "auto") return "Eligible for auto-approval";
  return "Needs review";
}

const digitsOf = (value) => value.replace(/\D/g, "");

// Mask identifiers before display. Mirrors backend/app/privacy.py.
export function maskSensitive(value = "") {
  return String(value ?? "")
    .replace(/\b([A-Z0-9._%+-])[A-Z0-9._%+-]*@([A-Z0-9.-]+\.[A-Z]{2,})\b/gi, "$1•••@$2")
    .replace(/(?<![\w-])(?:\+?234[\s.-]?|0)[789][01]\d(?:[\s.-]?\d){7}(?!\w)/g, (match) => `•••• ${digitsOf(match).slice(-4)}`)
    .replace(/(?<![\w-])\d(?:[\s-]?\d){12,18}(?!\w)/g, (match) => `•••• ${digitsOf(match).slice(-4)}`)
    .replace(/(?<![\w-])\d{11}(?!\w)/g, "•••••••••••")
    .replace(/(?<![\w-])\d{6}(\d{4})(?!\w)/g, "••••$1")
    .replace(/\b([A-Z]{2,5}-?\d{2,})(\d{4})\b/gi, (_, prefix, last4) => `${prefix.slice(0, 3)}•••${last4}`);
}

export function formatRelative(minutes) {
  const value = Math.max(0, Math.round(Number(minutes) || 0));
  if (value < 60) return `${value}m`;
  if (value < 1440) return `${Math.floor(value / 60)}h ${value % 60}m`;
  return `${Math.floor(value / 1440)}d ${Math.floor((value % 1440) / 60)}h`;
}

export function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Unknown date";
  return new Intl.DateTimeFormat("en-NG", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(date).replace(",", "");
}

// Local time of the latest customer message (server timestamps are UTC).
export function formatClock(ticket) {
  const date = new Date(ticket?.lastMessageAt || ticket?.receivedAt);
  if (Number.isNaN(date.valueOf())) return ticket?.receivedAt || "";
  return new Intl.DateTimeFormat("en-NG", { hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

export const initialsOf = (name = "") => name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();

// RFC 4180 CSV parsing: quoted fields may contain commas, quotes and newlines.
export function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  const source = String(text ?? "").replace(/^\uFEFF/, "");
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (quoted) {
      if (character === '"' && source[index + 1] === '"') { field += '"'; index += 1; }
      else if (character === '"') quoted = false;
      else field += character;
    } else if (character === '"') quoted = true;
    else if (character === ",") { row.push(field); field = ""; }
    else if (character === "\n" || character === "\r") {
      if (character === "\r" && source[index + 1] === "\n") index += 1;
      row.push(field); rows.push(row); row = []; field = "";
    } else field += character;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  return rows.filter((cells) => cells.some((cell) => cell.trim() !== ""));
}

export function csvToProofCases(text) {
  const [headerRow = [], ...rows] = parseCsv(text);
  const headers = headerRow.map((value) => value.trim().toLowerCase());
  return rows.map((cells, index) => {
    const row = Object.fromEntries(headers.map((header, column) => [header, (cells[column] ?? "").trim()]));
    const expected = row.expected_intent || row.expected_urgency || row.expected_route
      ? { intent: row.expected_intent || undefined, urgency: row.expected_urgency || undefined, route: row.expected_route || undefined }
      : undefined;
    return {
      case_id: row.case_id || `ROW-${index + 2}`,
      channel: (row.channel || "email").toLowerCase(),
      language: row.language || "unspecified",
      message: row.message,
      customer_name: row.customer_name || "Historical customer",
      expected
    };
  });
}

export function validateProofCases(items) {
  if (!Array.isArray(items) || !items.length) throw new Error("Add at least one historical case.");
  if (items.length > MAX_PROOF_CASES) throw new Error(`Use ${MAX_PROOF_CASES} cases or fewer per evaluation.`);
  const invalid = items.map((item, index) => (!item?.message || !["email", "whatsapp"].includes(item?.channel) ? index + 1 : null)).filter(Boolean);
  if (invalid.length) throw new Error(`Rows ${invalid.join(", ")} need a message and a valid email or whatsapp channel.`);
  return items;
}

// Spreadsheet apps execute cells starting with these characters as formulas.
const FORMULA_PREFIX = /^[=+\-@\t\r]/;

export function toCsv(rows) {
  return rows
    .map((row) => row.map((value) => {
      let text = String(value ?? "");
      if (FORMULA_PREFIX.test(text)) text = `'${text}`;
      return `"${text.replaceAll('"', '""')}"`;
    }).join(","))
    .join("\n");
}

export function downloadFile(filename, content, type = "text/csv") {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([content], { type }));
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 0);
}

// Seconds per case observed in the live smoke run, divided across workers.
export function estimateProofMinutes(caseCount, concurrency = 4, secondsPerCase = 15) {
  return Math.max(1, Math.ceil((caseCount * secondsPerCase) / Math.max(1, concurrency) / 60));
}
