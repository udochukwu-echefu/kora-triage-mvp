import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { OperationalEmptyState } from "./states/OperationalEmptyState";

const processed = (ticket) => ticket.source && ticket.source !== "pending";
const minimumLabelledSample = 20;

function dateScope(tickets) {
  const dates = tickets.map((ticket) => ticket.createdAt || ticket.created_at).filter(Boolean).map((value) => new Date(value)).filter((date) => !Number.isNaN(date.valueOf()));
  if (!dates.length) return "Current demo dataset";
  const format = new Intl.DateTimeFormat("en-NG", { day: "2-digit", month: "short", year: "numeric" });
  return `${format.format(new Date(Math.min(...dates)))} to ${format.format(new Date(Math.max(...dates)))}`;
}

function InsightSection({ title, description, scope, children, wide = false }) {
  return <section className={`insight-section${wide ? " insight-section-wide" : ""}`}><header><h3>{title}</h3>{description && <p>{description}</p>}<small>{scope}</small></header>{children}</section>;
}

export default function InsightsView({ tickets, evaluationSummary }) {
  const live = tickets.filter(processed);
  const labelled = live.filter((ticket) => ticket.truthIntent && ticket.truthIntent !== "Unlabelled");
  const scope = dateScope(live);
  const enoughLabels = labelled.length >= minimumLabelledSample;
  const humanOwned = live.filter((ticket) => ticket.escalated || ticket.lifecycle?.state === "review_required").length;
  const feedbackCount = evaluationSummary?.feedback_count || 0;
  const slaRisk = tickets.filter((ticket) => {
    if (["Approved", "Auto-approved"].includes(ticket.status)) return false;
    const target = { critical: 24, high: 48, medium: 120, low: 240 }[ticket.urgency] || 120;
    return target - ticket.minutesAgo <= Math.max(12, target * .2);
  }).length;
  const bands = [[0, 60], [60, 70], [70, 80], [80, 90], [90, 101]].map(([min, max]) => {
    const rows = labelled.filter((ticket) => ticket.confidence * 100 >= min && ticket.confidence * 100 < max);
    const correct = rows.filter((ticket) => ticket.intent === ticket.truthIntent && ticket.urgency === ticket.truthUrgency).length;
    return { band: `${min}-${max === 101 ? 100 : max}%`, confidence: rows.length ? Math.round(rows.reduce((sum, ticket) => sum + ticket.confidence, 0) / rows.length * 100) : 0, accuracy: rows.length ? Math.round(correct / rows.length * 100) : 0, cases: rows.length };
  });
  const groups = (key, truthKey) => Object.values(labelled.reduce((result, ticket) => {
    const name = ticket[key];
    const group = result[name] || { name, total: 0, correct: 0 };
    group.total += 1;
    group.correct += Number(ticket[key] === ticket[truthKey] || !ticket[truthKey]);
    result[name] = group;
    return result;
  }, {})).map((group) => ({ ...group, accuracy: Math.round(group.correct / group.total * 100) })).filter((group) => group.total >= 5).sort((a, b) => b.total - a.total);
  const byIssue = groups("intent", "truthIntent");
  const byTeam = groups("route", "truthRoute");
  const volumes = Object.entries(live.reduce((result, ticket) => {
    const value = ticket.createdAt || ticket.created_at;
    if (!value) return result;
    const day = new Intl.DateTimeFormat("en-NG", { day: "2-digit", month: "short" }).format(new Date(value));
    result[day] = (result[day] || 0) + 1;
    return result;
  }, {})).map(([day, volume]) => ({ day, volume }));
  const corrections = [
    { reason: "Incorrect specialist route", value: evaluationSummary?.routing_corrections || 0 },
    { reason: "Draft needed editing", value: Math.round((evaluationSummary?.draft_edit_rate || 0) * feedbackCount) },
    { reason: "Urgency changed", value: evaluationSummary?.urgency_corrections || 0 }
  ].filter((item) => item.value > 0);
  const tooltip = { contentStyle: { border: "1px solid var(--color-border-strong)", borderRadius: 8, boxShadow: "var(--shadow-float)", fontSize: 13 } };
  const emptyLabels = <OperationalEmptyState type="insufficient-data" title="Accuracy needs more labelled conversations" description={`Kora has ${labelled.length} labelled conversations. Review at least ${minimumLabelledSample} before comparing confidence with measured accuracy.`} compact />;
  return (
    <div className="view-padding insights-page">
      <div className="page-heading"><h2>Insights</h2><p>Operational quality and workload outcomes. Every claim identifies its period, sample and measurement status.</p></div>
      <section className="insight-operational-summary" aria-label="Operational summary">
        <div><span>Human intervention rate</span><strong>{live.length ? `${Math.round(humanOwned / live.length * 100)}%` : "Unavailable"}</strong><small>Measured · {live.length} processed · {scope}</small></div>
        <div><span>Draft edit rate</span><strong>{feedbackCount ? `${Math.round(evaluationSummary.draft_edit_rate * 100)}%` : "Unavailable"}</strong><small>{feedbackCount ? `Measured · ${feedbackCount} reviewed responses` : "No reviewed responses"} · {scope}</small></div>
        <div><span>SLA breached or at risk</span><strong>{slaRisk}</strong><small>Measured · {tickets.length} open and recent · current clock</small></div>
      </section>
      <div className="insight-grid">
        <InsightSection wide title="Confidence calibration" description="Confidence is model certainty. Accuracy is measured only against labelled outcomes." scope={`${labelled.length} labelled conversations · ${scope}`}>
          {enoughLabels && bands.filter((band) => band.cases).length >= 2 ? <><div className="chart-frame"><ResponsiveContainer width="100%" height="100%"><BarChart data={bands} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}><CartesianGrid stroke="var(--color-border)" vertical={false} /><XAxis dataKey="band" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} /><YAxis domain={[0, 100]} tick={{ fontSize: 12 }} axisLine={false} tickLine={false} /><Tooltip {...tooltip} /><Bar name="Average confidence" dataKey="confidence" fill="var(--color-ai-assessment-strong)" radius={[4, 4, 0, 0]} /><Bar name="Measured accuracy" dataKey="accuracy" fill="var(--color-text-primary)" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div><div className="chart-legend"><span><i className="bg-accent-strong" />Average confidence</span><span><i className="bg-ink" />Measured accuracy</span></div></> : emptyLabels}
        </InsightSection>
        <InsightSection title="Accuracy by issue" description="Only issues with at least five labelled conversations are shown." scope={`${labelled.length} labelled conversations · ${scope}`}>{enoughLabels && byIssue.length ? <div className="ranked-list">{byIssue.map((item) => <div key={item.name}><span>{item.name}<small>{item.total} labelled cases</small></span><strong>{item.accuracy}%</strong><i><b style={{ width: `${item.accuracy}%` }} /></i></div>)}</div> : emptyLabels}</InsightSection>
        <InsightSection title="Accuracy by team" description="Only teams with at least five labelled routed conversations are shown." scope={`${labelled.length} labelled conversations · ${scope}`}>{enoughLabels && byTeam.length ? <div className="ranked-list">{byTeam.map((item) => <div key={item.name}><span>{item.name}<small>{item.total} labelled cases</small></span><strong>{item.accuracy}%</strong><i><b style={{ width: `${item.accuracy}%` }} /></i></div>)}</div> : emptyLabels}</InsightSection>
        <InsightSection title="Volume trend" description="Processed conversation volume by day." scope={`${live.length} processed conversations · ${scope}`}>{volumes.length >= 2 ? <div className="chart-frame chart-frame-small"><ResponsiveContainer width="100%" height="100%"><BarChart data={volumes} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}><CartesianGrid stroke="var(--color-border)" vertical={false} /><XAxis dataKey="day" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} /><YAxis allowDecimals={false} tick={{ fontSize: 12 }} axisLine={false} tickLine={false} /><Tooltip {...tooltip} /><Bar name="Processed volume" dataKey="volume" fill="var(--color-text-primary)" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div> : <OperationalEmptyState type="insufficient-data" title="A trend needs more than one day" description="All processed conversations in this dataset belong to one period. Add another day before interpreting volume movement." compact />}</InsightSection>
        <InsightSection title="Correction reasons" description="Reasons recorded when agents change Kora's output." scope={`${feedbackCount} reviewed conversations · ${scope}`}>{corrections.length ? <div className="correction-list">{corrections.map((item) => <div key={item.reason}><span>{item.reason}</span><strong>{item.value}</strong></div>)}</div> : <OperationalEmptyState type="no-labels" title="No correction reasons are recorded" description="Save an agent correction with a reason to start measuring recurring quality issues." compact />}</InsightSection>
      </div>
    </div>
  );
}
