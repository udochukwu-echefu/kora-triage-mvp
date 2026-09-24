import { Check, CircleAlert, Clock3, FileCheck2, Send, UserRoundCheck } from "lucide-react";
import { cn } from "../../lib/utils";

function traceState(ticket, automation, decision) {
  if (!ticket.source || ticket.source === "pending") return { label: "Blocked", detail: "Classification has not been completed.", tone: "blocked" };
  const confidence = Math.round(ticket.confidence * 100);
  if (decision.state === "auto") return { label: "Safe candidate", detail: `${confidence}% confidence meets the ${automation.auto_approve_threshold}% automation threshold and all current safeguards.`, tone: "safe" };
  if (confidence < automation.mandatory_review_threshold) return { label: "Uncertain", detail: `${confidence}% confidence is below the ${automation.mandatory_review_threshold}% mandatory-review threshold.`, tone: "review" };
  return { label: "Human check", detail: decision.reason, tone: "review" };
}

export function DecisionTrace({ ticket, automation, decision, delivery }) {
  const confidenceState = traceState(ticket, automation, decision);
  const lifecycle = ticket.lifecycle?.state || "triaged";
  const deliveryLabel = lifecycle === "failed" ? "Delivery failed" : lifecycle === "queued" ? "Pending delivery" : ["sent", "delivered", "replied"].includes(lifecycle) ? lifecycle.replaceAll("_", " ") : delivery?.configured ? "Not sent" : "Channel not connected";
  const steps = [
    { icon: FileCheck2, label: "Customer evidence", value: ticket.evidence?.length ? `${ticket.evidence.length} signals recorded` : "No evidence recorded", complete: Boolean(ticket.evidence?.length) },
    { icon: Check, label: "Classification", value: ticket.source && ticket.source !== "pending" ? `${ticket.intent} · ${ticket.route}` : "Pending", complete: ticket.source && ticket.source !== "pending" },
    { icon: CircleAlert, label: "Confidence", value: `${confidenceState.label}: ${confidenceState.detail}`, tone: confidenceState.tone, complete: confidenceState.tone === "safe" },
    ...(ticket.policyCitations?.length ? [{ icon: FileCheck2, label: "Policy", value: `${ticket.policyCitations[0].title} v${ticket.policyCitations[0].version}`, complete: true }] : []),
    { icon: UserRoundCheck, label: "Human checkpoint", value: ticket.lifecycle?.assigned_to || ticket.assignee || "Agent decision required", complete: Boolean(ticket.lifecycle?.assigned_to || ticket.assignee) },
    { icon: lifecycle === "queued" ? Clock3 : Send, label: "Delivery", value: deliveryLabel, tone: lifecycle === "failed" ? "blocked" : lifecycle === "queued" ? "review" : undefined, complete: ["sent", "delivered", "replied"].includes(lifecycle) }
  ];
  return (
    <section className="decision-trace" aria-labelledby={`decision-trace-${ticket.id}`}>
      <div className="decision-trace-heading">
        <h4 id={`decision-trace-${ticket.id}`}>Decision trace</h4>
        <span>Recorded path, no inferred steps</span>
      </div>
      <ol>
        {steps.map(({ icon: Icon, label, value, tone, complete }) => <li key={label} className={cn(tone && `decision-trace-${tone}`)}>
          <span className="decision-trace-marker">{complete ? <Check /> : <Icon />}</span>
          <span><strong>{label}</strong><small>{value}</small></span>
        </li>)}
      </ol>
    </section>
  );
}
