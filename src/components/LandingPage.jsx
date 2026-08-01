import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  CircleDot,
  Database,
  FileCheck2,
  Inbox,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
  UserRoundCheck,
} from "lucide-react";

const queue = [
  { id: "KOR-2408", name: "Chidinma Okeke", issue: "Transfer pending", urgency: "high", wait: "4m", active: true },
  { id: "KOR-2412", name: "Emeka Nwosu", issue: "Unauthorised debit", urgency: "critical", wait: "11m" },
  { id: "KOR-2399", name: "Aisha Bello", issue: "Delivery delayed", urgency: "medium", wait: "18m" },
  { id: "KOR-2386", name: "Tunde Martins", issue: "Duplicate charge", urgency: "low", wait: "25m" },
];

const systemRows = [
  {
    icon: MessageSquareText,
    title: "Understands the complaint",
    body: "Intent, urgency, sentiment, and transaction context from English, Pidgin, or both.",
    output: "Groq structured output",
  },
  {
    icon: ShieldCheck,
    title: "Constrains the decision",
    body: "Confidence, fraud, hostility, and unsafe action claims are checked before a draft can move.",
    output: "Deterministic policy",
  },
  {
    icon: UserRoundCheck,
    title: "Leaves ownership visible",
    body: "Agents can approve, edit, route, or escalate. Every intervention becomes part of the record.",
    output: "Human checkpoint",
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

function Wordmark({ inverse = false }) {
  return (
    <span className="kora-wordmark" aria-label="Kora">
      <span className={inverse ? "kora-glyph kora-glyph-inverse" : "kora-glyph"}>K</span>
      <span>
        <strong>Kora</strong>
        <small>Support operations</small>
      </span>
    </span>
  );
}

function ProductStage() {
  return (
    <div className="stage-window" aria-label="Kora support queue and AI decision preview">
      <div className="stage-bar">
        <span className="stage-title"><Inbox className="size-4" /> Priority queue</span>
        <span className="stage-live"><CircleDot className="size-3.5" /> Groq ready</span>
      </div>

      <div className="stage-grid">
        <div className="stage-queue">
          <div className="stage-queue-label"><span>18 open</span><span>Waiting</span></div>
          {queue.map((item) => (
            <div key={item.id} className={`stage-ticket ${item.active ? "stage-ticket-active" : ""}`}>
              <span className={`stage-urgency stage-urgency-${item.urgency}`} />
              <div>
                <strong>{item.name}</strong>
                <span>{item.issue}</span>
                <small>{item.id}</small>
              </div>
              <time>{item.wait}</time>
            </div>
          ))}
        </div>

        <div className="stage-detail">
          <div className="stage-message">
            <div>
              <span>WhatsApp · 10:42</span>
              <small>Returning customer</small>
            </div>
            <blockquote>
              “I transfer ₦45,000 since morning, receiver never see am. Abeg check wetin happen.”
            </blockquote>
          </div>

          <div className="stage-decision">
            <div className="stage-decision-head">
              <span><Sparkles className="size-4" /> Kora assessment</span>
              <strong>94%</strong>
            </div>
            <dl>
              <div><dt>Intent</dt><dd>Transfer pending</dd></div>
              <div><dt>Urgency</dt><dd><span className="status-dot" />High</dd></div>
              <div><dt>Route</dt><dd>Transfers</dd></div>
            </dl>
            <div className="stage-why">
              <span>Decision evidence</span>
              <p>Amount and transaction delay are explicit. Confidence sits below the auto-send threshold.</p>
            </div>
          </div>

          <div className="stage-action">
            <div>
              <strong>Human approval required</strong>
              <span>Draft ready, no financial action taken</span>
            </div>
            <button type="button">Review draft <ArrowRight className="size-3.5" /></button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LandingPage({ onOpenWorkspace }) {
  return (
    <div className="site-shell">
      <a href="#landing-main" className="skip-link">Skip to content</a>

      <header className="site-nav">
        <a href="#top" aria-label="Kora home"><Wordmark inverse /></a>
        <nav aria-label="Landing page">
          <a href="#product">Product</a>
          <a href="#system">How it works</a>
          <a href="#proof">Proof</a>
        </nav>
        <WorkspaceLink onOpenWorkspace={onOpenWorkspace} className="nav-workspace">
          Open Kora <ArrowUpRight className="size-4" />
        </WorkspaceLink>
      </header>

      <main id="landing-main" tabIndex={-1}>
        <section id="top" className="site-hero">
          <div className="hero-grid">
            <div className="hero-copy">
              <p className="hero-kicker"><span /> Built for support teams in motion</p>
              <h1>
                Complaints arrive messy.
                <span>Decisions should not.</span>
              </h1>
              <p className="hero-lede">
                Kora turns WhatsApp and email complaints into explainable, review-ready support actions, without hiding the human behind the automation.
              </p>
              <div className="hero-actions">
                <WorkspaceLink onOpenWorkspace={onOpenWorkspace} className="button-lift button-lift-accent">
                  Enter the workspace <ArrowRight className="size-4" />
                </WorkspaceLink>
                <a href="#product" className="button-lift button-lift-quiet">
                  See the operating surface <ArrowDown className="size-4" />
                </a>
              </div>
            </div>

            <div className="hero-index" aria-label="Kora capabilities">
              <div><span>01</span><p>One queue for WhatsApp and email</p></div>
              <div><span>02</span><p>Visible confidence, evidence, and routing</p></div>
              <div><span>03</span><p>Human control before consequential action</p></div>
            </div>
          </div>

          <div className="hero-proof" id="proof">
            <div><strong>100</strong><span>policy cases across English and Pidgin</span></div>
            <div><strong>126</strong><span>automated safety and workflow checks</span></div>
            <div><strong>11/11</strong><span>live Groq smoke cases passed</span></div>
            <div className="hero-proof-note"><FileCheck2 className="size-4" /><span>Every override is written to the audit record</span></div>
          </div>
        </section>

        <section id="product" className="product-story">
          <div className="story-intro">
            <p>One operating surface</p>
            <h2>The message, the machine’s judgment, and the human decision stay together.</h2>
            <span>Less tab switching. No mystery hand-offs. No repeated questions.</span>
          </div>
          <ProductStage />
        </section>

        <section id="system" className="system-section">
          <div className="system-heading">
            <p>Not a chatbot</p>
            <h2>A decision system with clear boundaries.</h2>
          </div>
          <div className="system-list">
            {systemRows.map(({ icon: Icon, title, body, output }, index) => (
              <article key={title}>
                <span className="system-number">0{index + 1}</span>
                <Icon className="system-icon" />
                <div><h3>{title}</h3><p>{body}</p></div>
                <span className="system-output"><Check className="size-3.5" />{output}</span>
              </article>
            ))}
          </div>
        </section>

        <section className="memory-band">
          <div className="memory-mark"><Database className="size-5" /><span>Persistent context</span></div>
          <blockquote>
            “The customer already supplied the transaction ID in their last message.”
          </blockquote>
          <p>Kora’s memory layer keeps useful context attached to the customer, so the next reply moves forward instead of starting again.</p>
        </section>

        <section className="closing-section">
          <p>See the working system</p>
          <h2>Open a case. Inspect the reason. Make the call.</h2>
          <WorkspaceLink onOpenWorkspace={onOpenWorkspace} className="closing-link">
            Enter Kora <ArrowUpRight className="size-5" />
          </WorkspaceLink>
        </section>
      </main>

      <footer className="site-footer">
        <Wordmark />
        <p>AI-assisted support triage, built around visible human control.</p>
        <a href="#top">Back to top <ArrowUpRight className="size-3.5" /></a>
      </footer>
    </div>
  );
}
