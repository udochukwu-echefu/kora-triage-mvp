import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis
} from "recharts";
import {
  ArrowDownRight, ArrowUpRight, CheckCircle2, CircleAlert,
  Gauge, Route, ShieldCheck, Timer, UserRoundCheck
} from "lucide-react";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader } from "./ui/card";
import { cn } from "../lib/utils";

const percent = (value) => value == null ? "Not enough data" : `${Math.round(value * 100)}%`;
const processed = (ticket) => ticket.source && ticket.source !== "pending";

function InsightTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-36 rounded-[8px] border border-line-strong bg-paper p-3 shadow-float">
      <p className="text-[9px] font-bold uppercase tracking-[0.07em] text-ink-faint">Case {label}</p>
      <div className="mt-2 space-y-1.5">
        {payload.map((item) => (
          <div key={item.dataKey} className="flex items-center justify-between gap-5 text-[10px] font-semibold">
            <span className="capitalize text-ink-muted">{item.dataKey}</span>
            <strong>{item.value}%</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function Signal({ icon: Icon, label, value, note, tone = "neutral" }) {
  return (
    <div className={cn("insight-signal", tone === "accent" && "insight-signal-accent", tone === "dark" && "insight-signal-dark")}>
      <div className="flex items-center justify-between gap-3"><span className="text-[9px] font-bold uppercase tracking-[0.07em] opacity-60">{label}</span><Icon className="size-4 opacity-55" /></div>
      <strong>{value}</strong>
      <p>{note}</p>
    </div>
  );
}

export default function InsightsView({ tickets, evaluationSummary, evaluationGate }) {
  const live = tickets.filter(processed);
  const evaluation = live.filter((ticket) => ticket.truthIntent !== "Unlabelled").map((ticket) => ({
    case: ticket.id.replace("KOR-", ""),
    accuracy: Math.round((Number(ticket.intent === ticket.truthIntent) + Number(ticket.urgency === ticket.truthUrgency)) / 2 * 100),
    confidence: Math.round(ticket.confidence * 100)
  }));
  const routes = Object.entries(live.reduce((acc, ticket) => ({ ...acc, [ticket.route]: (acc[ticket.route] || 0) + 1 }), {}))
    .map(([name, volume]) => ({ name, volume }))
    .sort((a, b) => b.volume - a.volume);
  const labelled = live.filter((ticket) => ticket.truthIntent !== "Unlabelled");
  const totalLabels = evaluation.length * 2;
  const correctLabels = labelled.reduce((total, ticket) => total + Number(ticket.intent === ticket.truthIntent) + Number(ticket.urgency === ticket.truthUrgency), 0);
  const combinedAccuracy = totalLabels ? Math.round(correctLabels / totalLabels * 100) : 0;
  const averageConfidence = live.length ? Math.round(live.reduce((sum, ticket) => sum + ticket.confidence, 0) / live.length * 100) : 0;
  const humanOwned = live.filter((ticket) => ticket.escalated).length;
  const averageSaved = live.length ? live.reduce((sum, ticket) => sum + (ticket.estimatedMinutesSaved || 0), 0) / live.length : 0;
  const reviewCases = [...live]
    .sort((a, b) => Number(b.escalated) - Number(a.escalated) || a.confidence - b.confidence)
    .slice(0, 5);

  return (
    <div className="view-padding insights-page">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="section-label">Quality and throughput</p>
          <h2 className="mt-1 text-[26px] font-extrabold tracking-[-0.05em]">Support insights</h2>
          <p className="mt-2 max-w-2xl text-[11px] leading-5 text-ink-muted">A truthful view of model quality, human intervention, routing demand, and handling time.</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={evaluationGate?.passed ? "accent" : "outline"} shape="pill">
            {evaluationGate?.passed ? <CheckCircle2 className="size-3" /> : <CircleAlert className="size-3" />}
            {evaluationGate?.passed ? "Release gate passing" : "Gate needs review"}
          </Badge>
          <Badge variant="neutral" shape="pill">{live.length} processed</Badge>
        </div>
      </div>

      <section className="insight-signal-grid" aria-label="Performance summary">
        <Signal icon={ShieldCheck} label="Combined accuracy" value={`${combinedAccuracy}%`} note={`${correctLabels} of ${totalLabels || 0} labelled decisions correct`} tone="dark" />
        <Signal icon={Gauge} label="Average confidence" value={`${averageConfidence}%`} note="Classification certainty across processed cases" tone="accent" />
        <Signal icon={UserRoundCheck} label="Human-owned" value={humanOwned} note={`${live.length ? Math.round(humanOwned / live.length * 100) : 0}% of processed conversations`} />
        <Signal icon={Timer} label="Handling saved" value={`${averageSaved.toFixed(1)}m`} note="Estimated time saved per conversation" />
      </section>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(300px,.55fr)]">
        <Card className="overflow-hidden">
          <CardHeader className="items-end">
            <div><p className="section-label">Evaluation sequence</p><h3 className="mt-1 text-[15px] font-extrabold">Accuracy compared with confidence</h3><p className="mt-1 text-[10px] text-ink-faint">The distance between the lines reveals overconfidence and uncertain classifications.</p></div>
            <div className="hidden items-center gap-4 text-[9px] font-semibold text-ink-muted sm:flex"><span className="flex items-center gap-2"><i className="size-2 rounded-full bg-ink" />Accuracy</span><span className="flex items-center gap-2"><i className="size-2 rounded-full bg-accent-strong" />Confidence</span></div>
          </CardHeader>
          <CardContent className="h-[360px] min-w-0 px-3 pb-4 pt-5 sm:px-5">
            {evaluation.length ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <LineChart data={evaluation} margin={{ top: 12, right: 16, bottom: 4, left: -18 }}>
                  <CartesianGrid stroke="var(--color-line)" vertical={false} strokeDasharray="3 5" />
                  <XAxis dataKey="case" axisLine={false} tickLine={false} tickMargin={10} tick={{ fontSize: 9, fill: "var(--color-ink-faint)" }} />
                  <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: "var(--color-ink-faint)" }} />
                  <ReferenceLine y={70} stroke="var(--color-line-strong)" strokeDasharray="4 5" />
                  <RechartsTooltip content={<InsightTooltip />} cursor={{ stroke: "var(--color-line-strong)", strokeDasharray: "3 4" }} />
                  <Line type="monotone" dataKey="accuracy" stroke="var(--color-ink)" strokeWidth={2.2} dot={{ r: 3, fill: "var(--color-paper)", stroke: "var(--color-ink)", strokeWidth: 2 }} activeDot={{ r: 5 }} />
                  <Line type="monotone" dataKey="confidence" stroke="var(--color-accent-strong)" strokeWidth={2.2} dot={false} activeDot={{ r: 5, fill: "var(--color-accent-strong)" }} />
                </LineChart>
              </ResponsiveContainer>
            ) : <div className="grid h-full place-items-center text-center"><div><strong className="text-sm font-extrabold">No evaluation yet</strong><p className="mt-2 text-[10px] text-ink-muted">Processed cases populate this view automatically.</p></div></div>}
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader><div><p className="section-label">Routing demand</p><h3 className="mt-1 text-[15px] font-extrabold">Volume by team</h3></div><Route className="size-4 text-ink-faint" /></CardHeader>
          <CardContent className="h-[360px] min-w-0 px-2 pb-5 pt-5">
            {routes.length ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                <BarChart data={routes} layout="vertical" margin={{ top: 0, right: 18, bottom: 0, left: 8 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="name" width={92} axisLine={false} tickLine={false} tick={{ fontSize: 9, fontWeight: 650, fill: "var(--color-ink-muted)" }} />
                  <RechartsTooltip cursor={{ fill: "var(--color-muted-surface)" }} contentStyle={{ border: "1px solid var(--color-line-strong)", borderRadius: 8, boxShadow: "var(--shadow-float)", fontSize: 10 }} />
                  <Bar dataKey="volume" fill="var(--color-ink)" radius={[0, 5, 5, 0]} barSize={16} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="grid h-full place-items-center px-8 text-center text-[10px] text-ink-muted">Routing volume appears after processed cases are available.</div>}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-5 overflow-hidden">
        <CardHeader>
          <div><p className="section-label">Review signals</p><h3 className="mt-1 text-[15px] font-extrabold">Cases worth a second look</h3><p className="mt-1 text-[10px] text-ink-faint">Escalated and lower-confidence decisions appear first.</p></div>
          <span className="text-[9px] font-semibold text-ink-faint">{percent(evaluationSummary?.draft_edit_rate)} draft edit rate</span>
        </CardHeader>
        <div className="divide-y divide-line">
          {reviewCases.length ? reviewCases.map((ticket) => {
            const correct = ticket.intent === ticket.truthIntent && ticket.urgency === ticket.truthUrgency;
            return (
              <div key={ticket.id} className="insight-review-row">
                <div><strong>{ticket.id}</strong><span>{ticket.customer.name}</span></div>
                <div><span className="text-ink-faint">Decision</span><strong>{ticket.intent}</strong></div>
                <div><span className="text-ink-faint">Route</span><strong>{ticket.route}</strong></div>
                <div><span className="text-ink-faint">Confidence</span><strong>{Math.round(ticket.confidence * 100)}%</strong></div>
                <div className={cn("insight-verdict", correct ? "insight-verdict-good" : "insight-verdict-review")}>
                  {correct ? <ArrowUpRight className="size-3.5" /> : <ArrowDownRight className="size-3.5" />}
                  {correct ? "On label" : "Review"}
                </div>
              </div>
            );
          }) : <p className="p-8 text-center text-[10px] text-ink-muted">Review signals appear after cases are processed.</p>}
        </div>
      </Card>
    </div>
  );
}
