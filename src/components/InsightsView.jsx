const processed = (ticket) => ticket.source && ticket.source !== "pending";
const finite = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const percent = (value) => value == null ? "No sample" : `${Math.round(finite(value) * 100)}%`;
const dateFormatter = new Intl.DateTimeFormat("en-NG", { day: "2-digit", month: "short", year: "numeric" });
const shortDateFormatter = new Intl.DateTimeFormat("en-NG", { day: "2-digit", month: "short" });

function EmptyChart({ children }) {
  return <div className="insight-empty-chart"><span>No chart yet</span><p>{children}</p></div>;
}

function RankedBars({ rows, emptyMessage, tone = "berry" }) {
  if (!rows.length) return <EmptyChart>{emptyMessage}</EmptyChart>;
  return (
    <div className="insight-ranked-bars">
      {rows.map((row) => (
        <div key={row.name} className="insight-ranked-row">
          <div><strong>{row.name}</strong><span>{row.cases} case{row.cases === 1 ? "" : "s"}</span></div>
          <b>{row.accuracy}%</b>
          <i aria-hidden="true"><span className={`is-${tone}`} style={{ width: `${row.accuracy}%` }} /></i>
        </div>
      ))}
    </div>
  );
}

export default function InsightsView({ tickets = [], evaluationSummary }) {
  const live = tickets.filter(processed);
  const labelled = live.filter((ticket) => ticket.truthIntent && ticket.truthIntent !== "Unlabelled");
  const sampleLabel = `${live.length} processed conversation${live.length === 1 ? "" : "s"}`;
  const dateValues = live.map((ticket) => ticket.createdAt || ticket.created_at).filter(Boolean).map((value) => new Date(value)).filter((date) => !Number.isNaN(date.valueOf()));
  const dateRange = dateValues.length ? `${dateFormatter.format(new Date(Math.min(...dateValues)))} to ${dateFormatter.format(new Date(Math.max(...dateValues)))}` : "Current demo dataset";

  const bands = [[0, 60], [60, 70], [70, 80], [80, 90], [90, 101]].map(([min, max]) => {
    const rows = labelled.filter((ticket) => finite(ticket.confidence) * 100 >= min && finite(ticket.confidence) * 100 < max);
    const correct = rows.filter((ticket) => ticket.intent === ticket.truthIntent && ticket.urgency === ticket.truthUrgency).length;
    const confidence = rows.length ? Math.round(rows.reduce((sum, ticket) => sum + finite(ticket.confidence), 0) / rows.length * 100) : 0;
    const accuracy = rows.length ? Math.round(correct / rows.length * 100) : 0;
    const gap = rows.length ? Math.abs(confidence - accuracy) : null;
    const state = gap == null ? "No sample" : gap <= 5 ? "Aligned" : gap <= 12 ? "Watch" : "Review";
    return { band: `${min}–${max === 101 ? 100 : max}%`, confidence, accuracy, cases: rows.length, gap, state };
  });

  const byIntent = Object.values(labelled.reduce((groups, ticket) => {
    const key = ticket.truthIntent;
    const group = groups[key] || { name: key, total: 0, correct: 0 };
    group.total += 1;
    group.correct += Number(ticket.intent === ticket.truthIntent);
    groups[key] = group;
    return groups;
  }, {})).map((group) => ({ name: group.name, accuracy: Math.round(group.correct / group.total * 100), cases: group.total })).sort((a, b) => b.cases - a.cases).slice(0, 6);

  const byTeam = Object.values(labelled.reduce((groups, ticket) => {
    const key = ticket.route || "Unassigned";
    const group = groups[key] || { name: key, total: 0, correct: 0 };
    group.total += 1;
    group.correct += Number(ticket.route === ticket.truthRoute || !ticket.truthRoute);
    groups[key] = group;
    return groups;
  }, {})).map((group) => ({ name: group.name, accuracy: Math.round(group.correct / group.total * 100), cases: group.total })).sort((a, b) => b.cases - a.cases).slice(0, 6);

  const humanOwned = live.filter((ticket) => ticket.escalated || ticket.lifecycle?.state === "review_required").length;
  const humanRate = live.length ? Math.round(humanOwned / live.length * 100) : 0;
  const automated = Math.max(0, live.length - humanOwned);
  const slaRisk = tickets.filter((ticket) => {
    if (["Approved", "Auto-approved"].includes(ticket.status)) return false;
    const target = { critical: 24, high: 48, medium: 120, low: 240 }[ticket.urgency] || 120;
    return target - finite(ticket.minutesAgo) <= Math.max(12, target * .2);
  }).length;

  const volumes = Object.entries(live.reduce((groups, ticket) => {
    const value = ticket.createdAt || ticket.created_at;
    const date = value ? new Date(value) : null;
    const day = date && !Number.isNaN(date.valueOf()) ? shortDateFormatter.format(date) : "Current";
    groups[day] = (groups[day] || 0) + 1;
    return groups;
  }, {})).map(([day, volume]) => ({ day, volume }));
  const maxVolume = Math.max(1, ...volumes.map((item) => item.volume));

  const corrections = [
    { name: "Incorrect specialist route", value: finite(evaluationSummary?.routing_corrections) },
    { name: "Draft needed editing", value: Math.round(finite(evaluationSummary?.draft_edit_rate) * finite(evaluationSummary?.feedback_count)) },
    { name: "Urgency changed", value: finite(evaluationSummary?.urgency_corrections) }
  ];
  const maxCorrections = Math.max(1, ...corrections.map((item) => item.value));

  return (
    <div className="view-padding insights-dashboard">
      <div className="insights-intro">
        <div><p className="section-label">Operational quality</p><h2>Decisions you can inspect</h2><p>Measured outcomes from labelled conversations, human review, and the active queue.</p></div>
        <span>{dateRange}</span>
      </div>

      <section className="insight-summary-strip" aria-label="Operational summary">
        <div><span>Human intervention</span><strong>{live.length ? `${humanRate}%` : "No sample"}</strong><small>{sampleLabel}</small></div>
        <div><span>Draft edit rate</span><strong>{percent(evaluationSummary?.draft_edit_rate)}</strong><small>{finite(evaluationSummary?.feedback_count)} reviewed responses</small></div>
        <div><span>SLA at risk</span><strong>{slaRisk}</strong><small>{tickets.length} open and recent conversations</small></div>
      </section>

      <section className="insight-calibration" aria-labelledby="calibration-title">
        <header><div><p className="insight-eyebrow">Primary quality check</p><h3 id="calibration-title">Confidence calibration</h3><p>Confidence should stay close to measured accuracy. Large gaps signal that automated decisions need review.</p></div><span>{labelled.length} labelled</span></header>
        <div className="calibration-chart" role="img" aria-label={`Confidence calibration across five bands, based on ${labelled.length} labelled conversations`}>
          <div className="calibration-y-axis" aria-hidden="true"><span>100%</span><span>75%</span><span>50%</span><span>25%</span><span>0</span></div>
          <div className="calibration-plot">
            <div className="calibration-gridlines" aria-hidden="true"><i /><i /><i /><i /><i /></div>
            <div className="calibration-columns">
              {bands.map((row) => <div key={row.band} className="calibration-column" aria-label={`${row.band}: ${row.cases} cases, ${row.confidence}% average confidence, ${row.accuracy}% measured accuracy`}>
                <div className="calibration-bars">
                  <i className="is-confidence" style={{ height: row.cases ? `${Math.max(3, row.confidence)}%` : 0 }}><span>{row.cases ? `${row.confidence}%` : ""}</span></i>
                  <i className="is-accuracy" style={{ height: row.cases ? `${Math.max(3, row.accuracy)}%` : 0 }}><span>{row.cases ? `${row.accuracy}%` : ""}</span></i>
                </div>
                <strong>{row.band}</strong>
                <small>{row.cases} case{row.cases === 1 ? "" : "s"}</small>
              </div>)}
            </div>
            {!labelled.length && <div className="calibration-empty"><strong>Waiting for labelled data</strong><span>The chart will compare confidence with measured accuracy after evaluation.</span></div>}
          </div>
        </div>
        <div className="calibration-legend"><span><i className="is-confidence" />Average confidence</span><span><i className="is-accuracy" />Measured accuracy</span></div>
      </section>

      <div className="insight-visual-grid">
        <section className="insight-visual insight-handling" aria-labelledby="handling-title">
          <header><h3 id="handling-title">Handling mix</h3><span>{sampleLabel}</span></header>
          {live.length ? <div className="handling-chart"><div className="handling-donut" style={{ background: `conic-gradient(var(--color-berry) 0 ${humanRate}%, var(--color-blue) ${humanRate}% 100%)` }}><span><strong>{humanRate}%</strong>human</span></div><div className="handling-legend"><p><i className="is-human" /><span>Human reviewed<small>{humanOwned} conversations</small></span></p><p><i className="is-automated" /><span>System handled<small>{automated} conversations</small></span></p></div></div> : <EmptyChart>Process conversations to compare human and automated handling.</EmptyChart>}
        </section>

        <section className="insight-visual insight-volume" aria-labelledby="volume-title">
          <header><h3 id="volume-title">Processed volume</h3><span>{dateRange}</span></header>
          {volumes.length ? <div className="volume-bars">{volumes.map((item) => <div key={item.day} className="volume-column" aria-label={`${item.day}: ${item.volume} conversations`}><span>{item.volume}</span><i><b style={{ height: `${Math.max(8, item.volume / maxVolume * 100)}%` }} /></i><small>{item.day}</small></div>)}</div> : <EmptyChart>Daily volume appears after the first conversation is processed.</EmptyChart>}
        </section>

        <section className="insight-visual" aria-labelledby="issue-title">
          <header><h3 id="issue-title">Accuracy by issue</h3><span>{labelled.length} labelled</span></header>
          <RankedBars rows={byIntent} emptyMessage="Add expected issue labels to compare classification accuracy." />
        </section>

        <section className="insight-visual" aria-labelledby="team-title">
          <header><h3 id="team-title">Accuracy by team</h3><span>{labelled.length} labelled</span></header>
          <RankedBars rows={byTeam} tone="olive" emptyMessage="Add expected routes to compare team assignment accuracy." />
        </section>

        <section className="insight-visual insight-corrections" aria-labelledby="correction-title">
          <header><h3 id="correction-title">Correction reasons</h3><span>{finite(evaluationSummary?.feedback_count)} reviewed</span></header>
          <div className="correction-bars">{corrections.map((item) => <div key={item.name}><span>{item.name}</span><i><b style={{ width: `${item.value / maxCorrections * 100}%` }} /></i><strong>{item.value}</strong></div>)}</div>
        </section>
      </div>
    </div>
  );
}
