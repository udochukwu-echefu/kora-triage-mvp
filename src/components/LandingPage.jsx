import { useState } from "react";
import { ArrowDown, ArrowRight, ArrowUpRight, Check, CheckCheck, ChevronDown, GitFork, Mail, Menu, MessageCircle, UserRoundCheck, X } from "lucide-react";
import "./landing-page.css";

const examples = [
  { label: "A pending transfer", name: "Amaka", initials: "AO", channel: "WhatsApp", message: "Hi, I sent ₦25,000 this morning. I've been debited but the person never receive am. Please help.", intent: "Transfer pending", urgency: "High priority", team: "Transfers team", context: "Transfer amount and customer intent identified. Check the transaction status before confirming an outcome.", reply: "Hi Amaka, I’m sorry your transfer hasn’t arrived. We’ll check the ₦25,000 transaction and confirm its status with you.", step: "Review transaction status" },
  { label: "A late delivery", name: "Tunde", initials: "TA", channel: "Email", message: "My order was meant to arrive yesterday. It’s a birthday gift and I still haven't received an update.", intent: "Delivery delayed", urgency: "High priority", team: "Logistics team", context: "A missed delivery date and time-sensitive gift. Check the order history and latest tracking information.", reply: "Hi Tunde, I’m sorry your gift hasn’t arrived on time. We’ll check the latest delivery update and let you know what’s happening.", step: "Check delivery tracking" },
  { label: "A suspicious debit", name: "Zainab", initials: "ZA", channel: "WhatsApp", message: "I just got a debit alert for a payment I didn't make. Please, someone needs to look at this now.", intent: "Fraud report", urgency: "Critical priority", team: "Fraud team", context: "An unrecognised transaction requires specialist attention. Human review is mandatory for this case.", reply: "Hi Zainab, I’m sorry about this unexpected debit. I’m flagging it for our fraud team to review urgently and guide you on the next steps.", step: "Escalate for human review" }
];

function Wordmark() {
  return <span className="kl-wordmark"><span className="kl-mark" aria-hidden="true">k<span>.</span></span>kora<span className="kl-wordmark-dot">.</span></span>;
}

function PrimaryLink({ children = "Open workspace", className = "" }) {
  return <a className={`kl-button kl-button-primary ${className}`} href="/app">{children}<ArrowUpRight size={18} aria-hidden="true" /></a>;
}

function HeroConversation() {
  return <figure className="kl-hero-art" aria-label="Example of a customer message and Kora’s assessment">
    <div className="kl-message-note"><span className="kl-avatar">AO</span><div><strong>Amaka O.</strong><span><MessageCircle size={13} aria-hidden="true" /> WhatsApp</span></div></div>
    <blockquote className="kl-incoming">“I’ve been debited, but the person never receive am.”</blockquote>
    <div className="kl-triage-preview">
      <div className="kl-preview-heading"><strong>Kora’s assessment</strong><span>Needs review</span></div>
      <dl className="kl-assessment"><div><dt>Issue</dt><dd>Transfer pending</dd></div><div><dt>Assigned team</dt><dd>Transfers</dd></div></dl>
      <div className="kl-draft"><span>Suggested reply</span><p>Hi Amaka, I’m sorry your transfer hasn’t arrived. We’ll check the transaction status and update you.</p></div>
      <div className="kl-preview-footer"><UserRoundCheck size={16} aria-hidden="true" /><span>Ready for your team to review</span></div>
    </div>
    <figcaption className="kl-art-caption">Example conversation</figcaption>
  </figure>;
}

function WorkflowDemo() {
  const [selected, setSelected] = useState(0);
  const example = examples[selected];
  return <section className="kl-workflow kl-section" id="how-it-works" aria-labelledby="kl-workflow-title">
    <div className="kl-section-heading"><h2 id="kl-workflow-title">See how Kora<br />handles a message.</h2><p>Choose a case to see the assessment, the suggested team, and the reply your agent can review.</p></div>
    <div className="kl-demo-tabs" role="group" aria-label="Choose an example conversation">{examples.map((item, index) => <button key={item.label} type="button" aria-pressed={selected === index} onClick={() => setSelected(index)}>{index === 1 ? <Mail size={16} /> : <MessageCircle size={16} />}{item.label}</button>)}</div>
    <div className="kl-demo" aria-live="polite" aria-atomic="true">
      <div className="kl-demo-message"><div className="kl-step-heading"><span>01</span><strong>Customer message</strong></div><div className="kl-demo-person"><span className="kl-avatar">{example.initials}</span><div><strong>{example.name}</strong><small>{example.channel}</small></div></div><blockquote>{example.message}</blockquote></div>
      <div className="kl-demo-understand"><div className="kl-step-heading"><span>02</span><strong>Assessment & routing</strong></div><div className="kl-demo-tags"><span>{example.intent}</span><span>{example.urgency}</span></div><p>{example.context}</p><div className="kl-demo-route"><GitFork size={19} /><span>Routed to<strong>{example.team}</strong></span><ArrowRight size={18} /></div></div>
      <div className="kl-demo-response"><div className="kl-step-heading"><span>03</span><strong>Agent review</strong></div><span className="kl-draft-label">Suggested reply</span><p>{example.reply}</p><div className="kl-demo-next"><UserRoundCheck size={17} />{example.step}</div></div>
    </div>
    <p className="kl-demo-footnote">Sample messages and suggested replies. No live customer data.</p>
  </section>;
}

const questions = [
  ["What does Kora help my team do?", "Kora brings support messages into a shared queue, identifies intent and urgency, recalls customer context, suggests a route, and drafts a reply. Your team can inspect and correct the assessment before taking action."],
  ["Does Kora understand Nigerian Pidgin?", "Kora is designed to work with natural English and Nigerian Pidgin in support conversations. Agents can review the interpretation and edit the suggested response, so the customer’s meaning stays at the centre."],
  ["Will AI send replies without our approval?", "Automation is controlled by your team’s policy and confidence settings. Cases that are uncertain, sensitive, or outside those rules require human review. Agents can inspect the reasoning, edit replies, and escalate cases."],
  ["Which channels can I use?", "Kora supports WhatsApp and email workflows. Channel availability depends on the integrations configured for your workspace. You can review the connection status in the app."],
];

export default function LandingPage() {
  const [menuOpen, setMenuOpen] = useState(false);
  return <div className="kora-landing">
    <a className="kl-skip" href="#kl-main">Skip to content</a>
    <header className="kl-nav">
      <a href="/" aria-label="Kora home"><Wordmark /></a>
      <nav className={menuOpen ? "kl-nav-links is-open" : "kl-nav-links"} id="kl-navigation" aria-label="Landing page navigation" onClick={() => setMenuOpen(false)}><a href="#how-it-works">How it works</a><a href="#why-kora">Why Kora</a><a href="#questions">FAQs</a></nav>
      <div className="kl-nav-actions"><PrimaryLink /><button className="kl-menu-toggle" type="button" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen} aria-controls="kl-navigation" aria-label={menuOpen ? "Close menu" : "Open menu"}>{menuOpen ? <X /> : <Menu />}</button></div>
    </header>
    <main id="kl-main">
      <section className="kl-hero" aria-labelledby="kl-title">
        <div className="kl-hero-copy"><span className="kl-eyebrow">For Nigerian support teams</span><h1 id="kl-title">Support with<br />the full story.</h1><p>Kora sorts WhatsApp and email requests, recalls customer history, and drafts replies your team can review.</p><div className="kl-hero-actions"><PrimaryLink /><a className="kl-text-link" href="#how-it-works">Try an example<ArrowDown size={17} aria-hidden="true" /></a></div><p className="kl-hero-note">Built for conversations in English and Pidgin.</p></div>
        <HeroConversation />
      </section>
      <WorkflowDemo />
      <section className="kl-benefits kl-section" id="why-kora" aria-label="Customer context and team routing">
        <div className="kl-benefit-layout">
          <article className="kl-context-feature"><div className="kl-feature-copy"><h3>Pick up where they left off.</h3><p>Read earlier conversations alongside the current message, so customers don’t have to explain the same issue twice.</p></div><div className="kl-memory-visual" aria-label="Illustrative customer history"><div className="kl-memory-person"><span className="kl-avatar">AO</span><div><strong>Amaka Okafor</strong><span>Conversation history</span></div><MessageCircle size={22} /></div><ol><li><span className="kl-timeline-dot" /><div><small>Previous conversation</small><strong>Asked about a pending transfer</strong></div><Check size={16} /></li><li><span className="kl-timeline-dot" /><div><small>Today’s message</small><strong>Following up on the same issue</strong></div><MessageCircle size={16} /></li></ol><div className="kl-memory-found"><CheckCheck size={17} /> Previous conversation linked to this case</div></div></article>
          <article className="kl-route-feature"><h3>Route to the team that can help.</h3><p>Send transfer questions to payments, delivery issues to logistics, and suspicious activity to specialists.</p><div className="kl-route-visual"><div><strong>Suggested routing</strong><span>Team</span></div><dl><div><dt>Pending transfer</dt><dd>Transfers</dd></div><div><dt>Late delivery</dt><dd>Logistics</dd></div><div><dt>Unrecognised debit</dt><dd>Fraud & risk</dd></div></dl><p>Agents can change the assignment before proceeding.</p></div></article>
        </div>
        <article className="kl-human-feature"><h3>Review the reasoning<br />before you act.</h3><div><p>Inspect each suggestion, edit the reply, or escalate the case. Kora records the decision and who made it in the audit trail.</p><a className="kl-text-link" href="/app">Explore the workspace<ArrowRight size={18} aria-hidden="true" /></a></div></article>
      </section>
      <section className="kl-faq kl-section" id="questions" aria-labelledby="kl-faq-title"><h2 id="kl-faq-title">Before you get started.</h2><div className="kl-questions">{questions.map(([question, answer]) => <details key={question}><summary>{question}<ChevronDown size={19} /></summary><p>{answer}</p></details>)}</div></section>
      <section className="kl-closing"><h2>Take a look<br />at your workspace.</h2><PrimaryLink /></section>
    </main>
    <footer className="kl-footer"><a href="/" aria-label="Kora home"><Wordmark /></a><span>Support operations for Nigerian teams.</span><a href="/app">Open workspace<ArrowUpRight size={16} /></a><small>© {new Date().getFullYear()} Kora</small></footer>
  </div>;
}
