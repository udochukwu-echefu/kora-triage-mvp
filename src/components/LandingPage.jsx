import {
  ArrowDownRight,
  ArrowRight,
  BadgeCheck,
  Bot,
  Check,
  CircleDot,
  Database,
  FileClock,
  Inbox,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

const caseSteps = [
  { label: "Intent", value: "Transfer pending", detail: "Matched dispute workflow" },
  { label: "Urgency", value: "High", detail: "Funds unavailable for 6h" },
  { label: "Route", value: "Transfers", detail: "Specialist queue · SLA 48m" },
];

const workflow = [
  { number: "01", title: "Receive", body: "WhatsApp and email complaints enter one operating queue." },
  { number: "02", title: "Understand", body: "Groq classifies intent, urgency, sentiment, and key entities." },
  { number: "03", title: "Control", body: "Python guardrails apply confidence and hostility rules." },
  { number: "04", title: "Resolve", body: "Agents approve, edit, route, or escalate with the rationale preserved." },
];

const controlRows = [
  {
    icon: ShieldCheck,
    title: "Guardrails before automation",
    body: "Low-confidence and hostile messages cannot slip into auto-send. Thresholds stay visible and configurable.",
    meta: "Deterministic Python policy",
  },
  {
    icon: Database,
    title: "Customer context that persists",
    body: "SQLite memory carries forward facts a customer already supplied, so repeat contacts are not restarted from zero.",
    meta: "Case-linked customer memory",
  },
  {
    icon: FileClock,
    title: "An audit trail with reasons",
    body: "Model output, evidence, guardrail state, route, draft, and human action are recorded as one inspectable decision.",
    meta: "Model and human decisions",
  },
];

function WorkspaceLink({ onOpenWorkspace, className = "", children }) {
  return (
    <a
      href="/app"
      onClick={(event) => {
        event.preventDefault();
        onOpenWorkspace();
      }}
      className={className}
    >
      {children}
    </a>
  );
}

function Wordmark() {
  return (
    <span className="flex items-center gap-3" aria-label="Kora">
      <span className="grid size-9 place-items-center bg-ink text-[10px] font-extrabold tracking-[-0.03em] text-paper">KR</span>
      <span>
        <strong className="block text-[14px] font-extrabold tracking-[-0.04em]">Kora</strong>
        <small className="block text-[7px] font-extrabold uppercase tracking-[0.15em] text-ink-faint">Support operations</small>
      </span>
    </span>
  );
}

function DecisionPreview() {
  return (
    <div className="landing-console" aria-label="Example Kora triage decision">
      <div className="flex items-center justify-between border-b border-line bg-paper px-4 py-3 sm:px-5">
        <div className="flex items-center gap-2.5">
          <span className="relative flex size-2.5">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-50" />
            <span className="relative inline-flex size-2.5 rounded-full bg-accent-strong" />
          </span>
          <span className="text-[9px] font-extrabold uppercase tracking-[0.14em]">Decision stream</span>
        </div>
        <span className="text-[9px] font-bold text-ink-faint">Case KR-2048</span>
      </div>

      <div className="grid min-h-[470px] grid-rows-[auto_1fr_auto] sm:min-h-[520px]">
        <div className="border-b border-line bg-muted-surface/60 p-4 sm:p-6">
          <div className="mb-3 flex items-center justify-between gap-4">
            <span className="inline-flex items-center gap-2 text-[9px] font-extrabold uppercase tracking-[0.12em] text-ink-muted">
              <MessageSquareText className="size-3.5" /> WhatsApp · 10:42
            </span>
            <span className="border border-line-strong px-2 py-1 text-[8px] font-extrabold uppercase tracking-[0.1em]">New</span>
          </div>
          <blockquote className="max-w-[31rem] text-[15px] font-semibold leading-6 tracking-[-0.02em] sm:text-[18px] sm:leading-7">
            “I transfer ₦45,000 since morning, receiver never see am. Abeg check wetin happen.”
          </blockquote>
          <p className="mt-3 text-[9px] font-bold text-ink-faint">Chidinma Okeke · returning customer</p>
        </div>

        <div className="relative px-4 py-5 sm:px-6 sm:py-7">
          <div className="decision-current" aria-hidden="true" />
          <div className="relative space-y-2.5">
            {caseSteps.map((step, index) => (
              <div key={step.label} className="decision-step landing-reveal" style={{ "--delay": `${180 + index * 110}ms` }}>
                <span className="grid size-7 shrink-0 place-items-center border border-ink bg-paper text-[8px] font-extrabold">0{index + 1}</span>
                <div className="min-w-0 flex-1">
                  <span className="text-[8px] font-extrabold uppercase tracking-[0.13em] text-ink-faint">{step.label}</span>
                  <p className="mt-0.5 text-[12px] font-extrabold tracking-[-0.02em] sm:text-[13px]">{step.value}</p>
                </div>
                <span className="hidden text-right text-[8px] font-bold text-ink-faint sm:block">{step.detail}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-[1fr_auto] border-t border-ink bg-ink text-paper">
          <div className="p-4 sm:p-5">
            <p className="text-[8px] font-extrabold uppercase tracking-[0.14em] text-paper/50">AI recommendation</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <strong className="text-[13px] font-extrabold tracking-[-0.02em]">Human review</strong>
              <span className="bg-accent px-2 py-1 text-[8px] font-extrabold text-accent-ink">94% confidence</span>
            </div>
          </div>
          <div className="grid place-items-center border-l border-paper/20 px-4 text-accent sm:px-6">
            <ArrowDownRight className="size-5" />
          </div>
        </div>
      </div>
    </div>
  );
}

function ProductWindow() {
  const queue = [
    { name: "Chidinma Okeke", issue: "Transfer pending", time: "4m", tone: "High", active: true },
    { name: "Emeka Nwosu", issue: "Unauthorized debit", time: "11m", tone: "Critical" },
    { name: "Aisha Bello", issue: "Delivery delayed", time: "18m", tone: "Medium" },
    { name: "Tunde Martins", issue: "Duplicate charge", time: "25m", tone: "Low" },
  ];

  return (
    <div className="product-window">
      <div className="flex h-14 items-center justify-between border-b border-line bg-paper px-4 sm:px-6">
        <div className="flex items-center gap-2">
          <Inbox className="size-4" />
          <span className="text-[11px] font-extrabold">Triage queue</span>
        </div>
        <div className="flex items-center gap-3 text-[8px] font-extrabold uppercase tracking-[0.1em] text-ink-faint">
          <span className="hidden sm:inline">18 open cases</span>
          <span className="flex items-center gap-1.5 text-ink"><span className="size-2 rounded-full bg-accent-strong" /> Groq ready</span>
        </div>
      </div>

      <div className="grid lg:grid-cols-[0.78fr_1.22fr]">
        <div className="border-b border-line bg-paper lg:border-b-0 lg:border-r">
          <div className="grid grid-cols-[1fr_auto] border-b border-line px-4 py-3 text-[8px] font-extrabold uppercase tracking-[0.12em] text-ink-faint">
            <span>Priority queue</span><span>Waiting</span>
          </div>
          {queue.map((item) => (
            <div key={item.name} className={`grid grid-cols-[auto_1fr_auto] gap-3 border-b border-line px-4 py-4 ${item.active ? "bg-selected" : ""}`}>
              <span className={`mt-1 size-2 ${item.tone === "Critical" ? "rotate-45 bg-ink" : "rounded-full bg-accent-strong"}`} />
              <div className="min-w-0">
                <p className="truncate text-[10px] font-extrabold sm:text-[11px]">{item.name}</p>
                <p className="mt-1 truncate text-[9px] font-semibold text-ink-muted">{item.issue}</p>
                <span className="mt-2 inline-flex border border-line-strong px-1.5 py-0.5 text-[7px] font-extrabold uppercase tracking-[0.08em]">{item.tone}</span>
              </div>
              <span className="text-[8px] font-bold text-ink-faint">{item.time}</span>
            </div>
          ))}
        </div>

        <div className="bg-canvas">
          <div className="border-b border-line bg-paper px-5 py-5 sm:px-7">
            <p className="text-[8px] font-extrabold uppercase tracking-[0.13em] text-ink-faint">Raw customer message</p>
            <p className="mt-3 max-w-xl text-[12px] font-semibold leading-5 sm:text-[14px] sm:leading-6">I transfer ₦45,000 since morning, receiver never see am. Abeg help me confirm.</p>
          </div>
          <div className="grid gap-4 p-5 sm:p-7">
            <div className="border-l-[3px] border-accent-strong bg-ai p-4 sm:p-5">
              <div className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2 text-[9px] font-extrabold uppercase tracking-[0.12em]"><Bot className="size-4" /> AI assessment</span>
                <span className="bg-ink px-2 py-1 text-[8px] font-extrabold text-paper">94%</span>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-3">
                <div><p className="product-label">Intent</p><strong className="product-value">Transfer pending</strong></div>
                <div><p className="product-label">Urgency</p><strong className="product-value">High</strong></div>
                <div><p className="product-label">Route</p><strong className="product-value">Transfers</strong></div>
              </div>
              <div className="mt-5 border-t border-line-strong pt-4">
                <p className="product-label">Why</p>
                <p className="mt-1.5 text-[9px] font-semibold leading-4 text-ink-muted">Transaction amount and failed receipt are explicit. Six-hour delay raises urgency. Confidence is below the 95% auto-send threshold.</p>
              </div>
            </div>
            <div className="flex flex-col gap-3 border border-line bg-paper p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-[9px] font-extrabold">Human approval required</p>
                <p className="mt-1 text-[8px] font-semibold text-ink-faint">Draft is ready. Ada still owns the final action.</p>
              </div>
              <div className="flex gap-2">
                <span className="border border-line-strong px-3 py-2 text-[8px] font-extrabold">Edit draft</span>
                <span className="bg-ink px-3 py-2 text-[8px] font-extrabold text-paper">Approve response</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LandingPage({ onOpenWorkspace }) {
  return (
    <div className="landing-shell min-h-screen bg-canvas text-ink">
      <a href="#landing-main" className="skip-link">Skip to content</a>

      <header className="landing-nav">
        <a href="#top" className="focus-visible:ring-2 focus-visible:ring-ring" aria-label="Kora home"><Wordmark /></a>
        <nav className="hidden items-center gap-8 md:flex" aria-label="Landing page">
          <a href="#product" className="landing-nav-link">Product</a>
          <a href="#workflow" className="landing-nav-link">Workflow</a>
          <a href="#controls" className="landing-nav-link">Controls</a>
        </nav>
        <WorkspaceLink onOpenWorkspace={onOpenWorkspace} className="landing-nav-cta">
          Open workspace <ArrowRight className="size-3.5" />
        </WorkspaceLink>
      </header>

      <main id="landing-main" tabIndex={-1}>
        <section id="top" className="landing-hero">
          <div className="landing-hero-copy">
            <div className="landing-reveal" style={{ "--delay": "40ms" }}>
              <span className="landing-kicker"><Sparkles className="size-3.5" /> Support operations, with receipts</span>
            </div>
            <h1 className="landing-title landing-reveal" style={{ "--delay": "90ms" }}>
              Every complaint,
              <span>routed with a reason.</span>
            </h1>
            <p className="landing-lede landing-reveal" style={{ "--delay": "140ms" }}>
              Kora turns WhatsApp and email complaints into classified, auditable support actions while keeping the human in control.
            </p>
            <div className="landing-actions landing-reveal" style={{ "--delay": "190ms" }}>
              <WorkspaceLink onOpenWorkspace={onOpenWorkspace} className="landing-primary-cta">
                Open live workspace <ArrowRight className="size-4" />
              </WorkspaceLink>
              <a href="#workflow" className="landing-secondary-cta">
                See how it decides <ArrowDownRight className="size-4" />
              </a>
            </div>
            <div className="landing-proof landing-reveal" style={{ "--delay": "240ms" }} aria-label="Product proof">
              <div><strong>18</strong><span>labelled evaluation cases</span></div>
              <div><strong>89%</strong><span>intent + urgency accuracy</span></div>
              <div><strong>14</strong><span>backend tests</span></div>
            </div>
          </div>

          <div className="landing-hero-visual landing-reveal" style={{ "--delay": "130ms" }}>
            <div className="landing-orbit-label landing-orbit-label-top"><CircleDot className="size-3" /> Live classifier</div>
            <DecisionPreview />
            <div className="landing-orbit-label landing-orbit-label-bottom"><BadgeCheck className="size-3" /> Human-controlled</div>
          </div>
        </section>

        <section className="landing-proof-rail" aria-label="Kora capabilities">
          <p>Built for Nigerian support teams</p>
          <div className="landing-proof-list">
            <span>Pidgin + English</span><span>Groq structured output</span><span>SQLite memory</span><span>Deterministic guardrails</span>
          </div>
        </section>

        <section id="product" className="landing-section landing-product-section">
          <div className="landing-section-heading">
            <div><p className="landing-eyebrow">The operating surface</p><h2>A queue that explains itself.</h2></div>
            <p>Agents see the raw message, the model’s assessment, the evidence behind it, and the action that still needs human approval.</p>
          </div>
          <ProductWindow />
        </section>

        <section id="workflow" className="landing-section landing-workflow-section">
          <div className="landing-section-heading landing-section-heading-light">
            <div><p className="landing-eyebrow">One continuous workflow</p><h2>From complaint to controlled action.</h2></div>
            <p>Kora reduces handling time without turning judgment into a black box.</p>
          </div>
          <div className="workflow-grid">
            {workflow.map((item, index) => (
              <article key={item.number} className="workflow-item">
                <div className="workflow-marker"><span>{item.number}</span>{index < workflow.length - 1 && <span className="workflow-line" aria-hidden="true" />}</div>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
              </article>
            ))}
          </div>
          <div className="workflow-result">
            <span className="flex items-center gap-2"><Check className="size-4" /> The model proposes</span>
            <span className="flex items-center gap-2"><Check className="size-4" /> Policy constrains</span>
            <span className="flex items-center gap-2"><Check className="size-4" /> A human remains accountable</span>
          </div>
        </section>

        <section id="controls" className="landing-section landing-controls-section">
          <div className="controls-intro">
            <p className="landing-eyebrow">Designed for trust</p>
            <h2>Automation you can inspect, interrupt, and improve.</h2>
            <p className="controls-lede">The value is not that Kora uses AI. The value is that every AI-assisted action remains operationally legible.</p>
            <div className="controls-confidence" aria-label="Confidence policy example">
              <div className="flex items-center justify-between"><span>Mandatory review</span><strong>&lt;70%</strong></div>
              <div className="confidence-track"><span /><span /><span /></div>
              <div className="flex items-center justify-between"><span>Normal queue</span><span>Auto-send ≥95%</span></div>
            </div>
          </div>
          <div className="control-list">
            {controlRows.map(({ icon: Icon, title, body, meta }, index) => (
              <article key={title} className="control-row">
                <div className="control-index">0{index + 1}</div>
                <Icon className="control-icon" />
                <div><h3>{title}</h3><p>{body}</p><span>{meta}</span></div>
              </article>
            ))}
          </div>
        </section>

        <section className="landing-final-cta">
          <div>
            <p className="landing-eyebrow text-paper/55">See the system, not a sales demo</p>
            <h2>Open the queue. Inspect every decision.</h2>
          </div>
          <WorkspaceLink onOpenWorkspace={onOpenWorkspace} className="landing-final-link">
            Enter Kora <ArrowRight className="size-5" />
          </WorkspaceLink>
        </section>
      </main>

      <footer className="landing-footer">
        <Wordmark />
        <p>AI-assisted support triage with visible human control.</p>
        <a href="#top" className="landing-nav-link">Back to top ↑</a>
      </footer>
    </div>
  );
}
