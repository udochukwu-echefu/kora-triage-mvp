import {
  CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip as RechartsTooltip, XAxis, YAxis
} from "recharts";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader } from "./ui/card";

const percent = (value) => value == null ? "Not enough data" : `${Math.round(value * 100)}%`;

export default function InsightsView({ tickets, evaluationSummary, evaluationGate }) {
  const live = tickets.filter((ticket) => ticket.source && ticket.source !== "pending");
  const evaluation = live.filter((ticket) => ticket.truthIntent !== "Unlabelled").map((ticket) => ({
    case: ticket.id.replace("KOR-", ""),
    accuracy: Math.round(
      (Number(ticket.intent === ticket.truthIntent) + Number(ticket.urgency === ticket.truthUrgency))
      / 2 * 100
    ),
    confidence: Math.round(ticket.confidence * 100)
  }));
  const routes = Object.entries(
    live.reduce(
      (acc, ticket) => ({ ...acc, [ticket.route]: (acc[ticket.route] || 0) + 1 }),
      {}
    )
  ).map(([name, volume]) => ({ name, volume }));
  const maxVolume = Math.max(...routes.map((item) => item.volume));

  return (
    <div className="view-padding">
      <div className="mb-7 flex items-end justify-between">
        <div><p className="section-label">Processed model runs</p><h2 className="mt-1 text-[24px] font-extrabold tracking-[-0.05em]">Operational performance</h2></div>
        <Badge variant="accent" shape="pill"><span className="size-1.5 rounded-full bg-current" />{live.length} processed</Badge>
      </div>
      <div className="mb-5 grid border border-line-strong bg-line-strong sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Intent accuracy", percent(evaluationSummary?.intent_accuracy), `${evaluationSummary?.labelled || 0} labelled cases`],
          ["Draft edit rate", percent(evaluationSummary?.draft_edit_rate), "Human-reviewed replies"],
          ["Routing corrections", percent(evaluationSummary?.routing_correction_rate), "Model route overrides"],
          ["Release gate", evaluationGate?.passed ? "Passing" : "Review", evaluationGate?.passed ? "No threshold regressions" : "One or more checks failed"]
        ].map(([label, value, note]) => <div key={label} className="bg-paper px-5 py-4"><p className="section-label">{label}</p><strong className="mt-2 block text-[18px] font-extrabold tracking-[-0.04em]">{value}</strong><span className="mt-1 block text-[9px] text-ink-faint">{note}</span></div>)}
      </div>
      <div className="grid gap-5 xl:grid-cols-[1.4fr_.6fr]">
        <Card>
          <CardHeader><div><p className="section-label">Evaluation</p><h3 className="mt-1 text-sm font-extrabold">Accuracy and confidence by case</h3></div></CardHeader>
          <CardContent className="h-[340px] min-w-0">
            {evaluation.length ? <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <LineChart data={evaluation} margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
                <CartesianGrid stroke="var(--color-line)" vertical={false} />
                <XAxis dataKey="case" axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: "var(--color-ink-faint)" }} />
                <YAxis domain={[0, 100]} axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: "var(--color-ink-faint)" }} />
                <RechartsTooltip contentStyle={{ border: "1px solid var(--color-line-strong)", borderRadius: 0, boxShadow: "none", fontSize: 10 }} />
                <Line dataKey="accuracy" stroke="var(--color-ink)" strokeWidth={2} dot={{ r: 3, fill: "var(--color-ink)" }} />
                <Line dataKey="confidence" stroke="var(--color-accent)" strokeWidth={2} dot={{ r: 3, fill: "var(--color-accent-ink)" }} />
              </LineChart>
            </ResponsiveContainer> : <div className="grid h-full place-items-center text-center"><div><strong className="text-sm font-extrabold">No evaluation yet</strong><p className="mt-2 text-[10px] text-ink-muted">Processed cases populate this chart automatically.</p></div></div>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><div><p className="section-label">Routing mix</p><h3 className="mt-1 text-sm font-extrabold">Volume by team</h3></div></CardHeader>
          <CardContent className="space-y-5">
            {routes.length ? routes.map((route) => <div key={route.name}><div className="flex justify-between text-[10px] font-bold"><span>{route.name}</span><span>{route.volume}</span></div><div className="mt-2 h-1.5 bg-muted-surface"><span className="block h-full bg-ink" style={{ width: `${route.volume / maxVolume * 100}%` }} /></div></div>) : <p className="text-[10px] text-ink-muted">Routing volume appears after processed cases are available.</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
