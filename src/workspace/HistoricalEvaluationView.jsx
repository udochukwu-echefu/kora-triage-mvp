import { useState } from "react";
import { CheckCircle2, ChevronDown, CircleAlert, ClipboardCheck, Download, LoaderCircle, WifiOff } from "lucide-react";
import { csvToProofCases, downloadFile, estimateProofMinutes, formatDate, toCsv, validateProofCases } from "../lib/tickets";
import { Button } from "../components/ui/button";

const proofSample = JSON.stringify([
  {
    case_id: "HIST-001",
    channel: "whatsapp",
    language: "pidgin",
    message: "Abeg my transfer TRX-12345 never reach since morning.",
    customer_name: "Historical customer",
    expected: { intent: "Transfer pending", urgency: "high", route: "Transfers" }
  }
], null, 2);

const TEMPLATE = toCsv([
  ["case_id", "channel", "language", "message", "customer_name", "expected_intent", "expected_urgency", "expected_route"],
  ["HIST-001", "whatsapp", "pidgin", "Abeg my ₦45,000 transfer never reach since morning", "Chidinma Okeke", "Transfer pending", "high", "Transfers"]
]);

const percent = (value) => value == null ? "Not labelled" : `${Math.round(value * 100)}%`;

function errorRows(report) {
  const mismatched = (row) => row.error || ["intent", "urgency", "route"].some((key) => row.expected?.[key] && row.expected[key] !== row.predicted?.[key]);
  return [
    ["case_id", "language", "message", "error", "expected_intent", "predicted_intent", "expected_urgency", "predicted_urgency", "expected_route", "predicted_route", "automation_eligible"],
    ...(report.cases || []).filter(mismatched).map((row) => [
      row.case_id, row.language, row.message, row.error || "",
      row.expected?.intent, row.predicted?.intent, row.expected?.urgency, row.predicted?.urgency,
      row.expected?.route, row.predicted?.route, row.predicted?.automation_eligible
    ])
  ];
}

export default function HistoricalEvaluationView({ runs, onRun, running, backend, demoCaseLimit }) {
  const [name, setName] = useState("Historical support evaluation");
  const [cases, setCases] = useState([]);
  const [source, setSource] = useState(proofSample);
  const [error, setError] = useState("");
  const load = (text, filename = "") => {
    try {
      const parsed = validateProofCases(filename.toLowerCase().endsWith(".csv") ? csvToProofCases(text) : JSON.parse(text));
      if (demoCaseLimit && parsed.length > demoCaseLimit) throw new Error(`The public demo accepts up to ${demoCaseLimit} cases per evaluation.`);
      setCases(parsed);
      setSource(JSON.stringify(parsed, null, 2));
      setError("");
    } catch (loadError) {
      setCases([]);
      setError(loadError instanceof SyntaxError ? "The file is not valid JSON." : loadError.message);
    }
  };
  const latest = runs[0];
  const inProgress = latest?.status === "running";
  const errors = latest && !inProgress ? errorRows(latest.report) : [];
  const minutes = estimateProofMinutes(cases.length);
  return (
    <div className="view-padding max-w-6xl">
      <div className="page-heading"><h2>Historical evaluation</h2><p>Upload labelled past conversations to measure routing quality and review requirements without contacting customers.</p></div>
      {!backend.configured && <div className="system-notice"><WifiOff /><div><strong>AI service unavailable</strong><p>Historical evaluation needs the AI service. The support queue remains available for manual work.</p></div></div>}
      <div className="evaluation-layout">
        <section className="evaluation-input">
          <label>Evaluation name<input value={name} maxLength={160} onChange={(event) => setName(event.target.value)} /></label>
          <div className="upload-zone"><ClipboardCheck /><strong>Upload historical cases</strong><p>CSV or JSON, up to {demoCaseLimit || 100} cases. Expected labels are optional.</p>
            <label className="upload-button">Choose file<input type="file" accept=".csv,.json,application/json,text/csv" onChange={(event) => { const file = event.target.files?.[0]; if (file) file.text().then((text) => load(text, file.name)); event.target.value = ""; }} /></label>
            <div><Button variant="ghost" onClick={() => downloadFile("kora-evaluation-template.csv", TEMPLATE)}><Download />Download template</Button><Button variant="ghost" onClick={() => load(proofSample, "sample.json")}>Use sample data</Button></div>
          </div>
          {error && <p className="validation-error" role="alert"><CircleAlert />{error}</p>}
          {cases.length > 0 && <div className="validation-preview"><strong>{cases.length} cases ready</strong><span>Estimated processing time: about {minutes} minute{minutes === 1 ? "" : "s"}. You can leave this page while it runs.</span><div>{cases.slice(0, 4).map((item, index) => <p key={`${item.case_id}-${index}`}><span>{item.case_id}</span><span>{item.channel}</span><span>{item.message}</span><CheckCircle2 /></p>)}</div></div>}
          <details className="case-disclosure"><summary><span>Advanced: raw JSON editor</span><ChevronDown /></summary><div className="disclosure-content"><textarea value={source} onChange={(event) => setSource(event.target.value)} rows={12} spellCheck={false} /><Button variant="outline" onClick={() => load(source, "advanced.json")}>Validate JSON</Button></div></details>
          <Button onClick={() => onRun({ name, cases })} disabled={running || inProgress || !backend.configured || !cases.length}>{running || inProgress ? <LoaderCircle className="animate-spin" /> : <ClipboardCheck />}{running || inProgress ? "Evaluation running" : "Run historical evaluation"}</Button>
        </section>
        <section className="evaluation-results">
          <h3>Latest result</h3>
          {!latest && <div className="compact-empty"><p>No evaluation has been run. Upload labelled cases to measure routing accuracy and review requirements.</p></div>}
          {inProgress && <div role="status"><p className="result-date">{latest.name} · started {formatDate(latest.created_at)}</p><div className="result-list"><div><span>Progress</span><strong>{latest.report.processed || 0} / {latest.report.total || "…"}</strong></div><div><span>Failed so far</span><strong>{latest.report.failed || 0}</strong></div></div><p className="mt-3 text-[13px] text-ink-muted">Results appear here automatically when the run finishes.</p></div>}
          {latest && !inProgress && (latest.status === "failed" || latest.status === "interrupted"
            ? <div className="compact-empty" role="alert"><p>{latest.status === "interrupted" ? "This evaluation was interrupted by a server restart. Run it again." : latest.report.error || "This evaluation could not run."}</p></div>
            : <>
              <p className="result-date">{formatDate(latest.created_at)} · {latest.report.completed ?? latest.report.total} cases</p>
              <div className="result-list">{[
                ["Readiness score", `${latest.report.readiness_score} / 100`],
                ["Cases processed", latest.report.completed],
                ["Intent accuracy", percent(latest.report.intent_accuracy)],
                ["Urgency accuracy", percent(latest.report.urgency_accuracy)],
                ["Routing accuracy", percent(latest.report.routing_accuracy)],
                ["Unsafe automation candidates", latest.report.unsafe_automation_candidates ?? latest.report.guardrail_failures ?? 0],
                ["Cases requiring review", latest.report.human_review_cases],
                ["Would be auto-approved (simulated)", latest.report.safe_automation_candidates]
              ].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
              <Button variant="outline" disabled={errors.length <= 1} onClick={() => downloadFile(`kora-evaluation-${latest.id}-errors.csv`, toCsv(errors))}><Download />Download error set ({Math.max(0, errors.length - 1)})</Button>
            </>)}
        </section>
      </div>
    </div>
  );
}
