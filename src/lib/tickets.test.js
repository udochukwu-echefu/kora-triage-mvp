import { describe, expect, it } from "vitest";
import {
  csvToProofCases, estimateProofMinutes, isGuardrailEscalated, maskSensitive, operationalState, parseCsv,
  slaState, ticketAgeMinutes, toCsv, validateProofCases
} from "./tickets";

const NOW = Date.parse("2026-09-24T12:00:00Z");
const minutesBefore = (minutes) => new Date(NOW - minutes * 60000).toISOString();
const ticket = (overrides = {}) => ({
  id: "KOR-1", source: "groq", urgency: "high", status: "AI draft ready",
  lastMessageAt: minutesBefore(10), lifecycle: { state: "triaged" }, ...overrides
});

describe("SLA age", () => {
  it("is computed from the latest customer message, not a frozen counter", () => {
    expect(ticketAgeMinutes(ticket({ minutesAgo: 0, lastMessageAt: minutesBefore(95) }), NOW)).toBe(95);
  });

  it("flags inbound cases that go overdue as time passes", () => {
    const inbound = ticket({ urgency: "critical", minutesAgo: 0, lastMessageAt: minutesBefore(5) });
    expect(slaState(inbound, NOW)).toBeNull();
    expect(slaState(inbound, NOW + 15 * 60000)).toEqual({ label: "4m to SLA", overdue: false });
    expect(slaState(inbound, NOW + 60 * 60000)).toEqual({ label: "41m overdue", overdue: true });
  });

  it("stops counting once a reply is approved, sent, or the case is resolved", () => {
    const overdue = { urgency: "critical", lastMessageAt: minutesBefore(600) };
    for (const state of ["approved", "queued", "sent", "delivered", "resolved"]) {
      expect(slaState(ticket({ ...overdue, lifecycle: { state } }), NOW)).toBeNull();
    }
    expect(slaState(ticket({ ...overdue, lifecycle: { state: "replied" } }), NOW)?.overdue).toBe(true);
  });
});

describe("masking", () => {
  it.each([
    ["Card 5399 8312 3456 7890 charged", "5399 8312 3456 7890", "•••• 7890"],
    ["card 5399831234567890", "5399831234567890", "•••• 7890"],
    ["BVN 22212345678", "22212345678", "•••••••••••"],
    ["call 0803 123 4567", "0803 123 4567", "•••• 4567"],
    ["call +2348031234567", "+2348031234567", "•••• 4567"],
    ["account 0192846671", "0192846671", "••••6671"],
    ["mail chika@example.com", "chika@example.com", "c•••@example.com"]
  ])("hides %s", (text, secret, replacement) => {
    const masked = maskSensitive(text);
    expect(masked).not.toContain(secret);
    expect(masked).toContain(replacement);
  });

  it("keeps amounts readable", () => {
    expect(maskSensitive("I sent ₦1,250,000 yesterday")).toBe("I sent ₦1,250,000 yesterday");
  });
});

describe("case state", () => {
  it("distinguishes guardrail escalations from human escalations", () => {
    expect(isGuardrailEscalated(ticket({ escalated: true, escalationReason: "Fraud reports cannot be resolved automatically" }))).toBe(true);
    expect(isGuardrailEscalated(ticket({ escalated: true, escalationReason: null }))).toBe(false);
  });

  it("describes customer replies and approvals", () => {
    expect(operationalState(ticket({ lifecycle: { state: "replied" } }))).toBe("Customer replied");
    expect(operationalState(ticket({ lifecycle: { state: "approved" } }))).toBe("Approved");
  });
});

describe("CSV import and export", () => {
  it("keeps commas, quotes and line breaks inside quoted fields", () => {
    const csv = 'case_id,channel,message,expected_intent\nH-1,whatsapp,"I sent ₦45,000 and ""nothing"" came\nstill waiting",Transfer pending\r\n';
    expect(parseCsv(csv)).toEqual([
      ["case_id", "channel", "message", "expected_intent"],
      ["H-1", "whatsapp", 'I sent ₦45,000 and "nothing" came\nstill waiting', "Transfer pending"]
    ]);
    const [row] = csvToProofCases(csv);
    expect(row.message).toContain("₦45,000");
    expect(row.expected).toEqual({ intent: "Transfer pending", urgency: undefined, route: undefined });
  });

  it("round-trips its own output and neutralises spreadsheet formulas", () => {
    const csv = toCsv([["message", "note"], ["₦45,000, pending", "=HYPERLINK(\"http://x\")"]]);
    expect(parseCsv(csv)[1]).toEqual(["₦45,000, pending", "'=HYPERLINK(\"http://x\")"]);
  });

  it("validates cases before upload", () => {
    expect(() => validateProofCases([])).toThrow("at least one");
    expect(() => validateProofCases([{ channel: "sms", message: "hi" }])).toThrow("Rows 1");
    expect(() => validateProofCases(Array.from({ length: 101 }, () => ({ channel: "email", message: "x" })))).toThrow("100");
  });

  it("estimates run time from the measured model latency", () => {
    expect(estimateProofMinutes(100, 4)).toBe(7);
    expect(estimateProofMinutes(1, 4)).toBe(1);
  });
});
