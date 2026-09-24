import { useState } from "react";
import { BookOpenCheck, CircleAlert, Mail, MessageCircle, Save, Wrench, Zap } from "lucide-react";
import { policyState } from "../lib/tickets";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Switch } from "../components/ui/switch";

const EMPTY_POLICY = { title: "", version: "1.0", source_url: "", content: "" };

export default function SettingsView({ automation, onChange, onSave, saving, tickets, integrations, policies, onCreatePolicy, onTogglePolicy, policySaving, canManage }) {
  const [policyDraft, setPolicyDraft] = useState(EMPTY_POLICY);
  const [confirmSave, setConfirmSave] = useState(false);
  const hasActivePolicies = policies.some((policy) => policy.active);
  const hasDelivery = integrations?.mode === "live" && (integrations?.email?.configured || integrations?.whatsapp?.configured);
  const governanceReady = hasActivePolicies && hasDelivery;
  const open = tickets.filter((ticket) => ticket.lifecycle?.state !== "resolved");
  const autoCount = open.filter((ticket) => policyState(ticket) === "auto").length;
  const reviewCount = open.filter((ticket) => policyState(ticket) === "mandatory").length;
  const assignedCount = open.filter((ticket) => ticket.lifecycle?.assigned_to || ticket.assignee).length;
  const deadJobs = integrations?.jobs?.dead || 0;
  const cancelledJobs = integrations?.jobs?.cancelled || 0;
  return (
    <div className="view-padding max-w-5xl">
      <div className="page-heading"><p>Confidence is only one requirement. Policy, verification, guardrails, information completeness and delivery must also pass.</p></div>
      {!canManage && <div className="system-notice"><CircleAlert /><div><strong>Read-only</strong><p>Only support managers can change automation settings and policies.</p></div></div>}
      <div className="grid gap-5 lg:grid-cols-[1.2fr_.8fr]">
        <Card className="p-6">
          <div className="flex items-start justify-between gap-5 border-b border-line pb-5"><div><div className="flex items-center gap-2"><Zap className="size-4" /><h3 className="text-[17px] font-semibold">Auto-approve eligible drafts</h3></div><p className="mt-2 max-w-lg text-sm leading-6 text-ink-muted">Eligible cases need an approved policy match, no guardrail, required verification, complete information, connected delivery and sufficient confidence.</p></div><Switch aria-label="Enable auto-approval" checked={automation.enabled} disabled={!canManage || (!governanceReady && !automation.enabled)} onCheckedChange={(enabled) => onChange({ ...automation, enabled })} /></div>
          {!governanceReady && <div className="mt-4 rounded-[14px] bg-muted-surface p-4 text-[13px]"><strong>Auto-approval is unavailable</strong><p className="mt-1 text-ink-muted">{!hasActivePolicies ? "Add and activate an approved policy. " : ""}{!hasDelivery ? "Connect email or WhatsApp for live delivery." : ""}</p></div>}
          <label className="automation-range mt-6 block"><span className="flex items-center justify-between gap-4"><span>Auto-approve threshold</span><strong>{automation.auto_approve_threshold}%</strong></span><input type="range" min="80" max="99" disabled={!canManage} value={automation.auto_approve_threshold} onChange={(event) => onChange({ ...automation, auto_approve_threshold: Number(event.target.value) })} /><span className="range-bounds"><span>80%</span><span>99%</span></span></label>
          <label className="automation-range mt-7 block border-t border-line pt-6"><span className="flex items-center justify-between gap-4"><span>Mandatory review below</span><strong>{automation.mandatory_review_threshold}%</strong></span><input type="range" min="50" max="90" disabled={!canManage} value={automation.mandatory_review_threshold} onChange={(event) => onChange({ ...automation, mandatory_review_threshold: Number(event.target.value) })} /><span className="range-bounds"><span>50%</span><span>90%</span></span></label>
          {automation.mandatory_review_threshold >= automation.auto_approve_threshold && <p className="mt-4 flex items-center gap-2 text-xs font-bold"><CircleAlert className="size-4" />The lower threshold must remain below auto-approve.</p>}
          {confirmSave
            ? <div className="mt-5 border-y border-line py-4 text-[13px]"><strong>Recorded queue impact</strong><p className="mt-1 text-ink-muted">{autoCount} open conversations are recorded as eligible and {reviewCount} require review. New settings apply when a case is next triaged.</p><div className="mt-3 flex gap-2"><Button onClick={() => { onSave(); setConfirmSave(false); }} disabled={saving}><Save className="size-4" />Confirm and save</Button><Button variant="ghost" onClick={() => setConfirmSave(false)}>Cancel</Button></div></div>
            : <Button onClick={() => setConfirmSave(true)} disabled={!canManage || saving || automation.mandatory_review_threshold >= automation.auto_approve_threshold || (automation.enabled && !governanceReady)} className="mt-7"><Save className="size-4" />Review changes</Button>}
        </Card>
        <div className="automation-impact p-6"><h3 className="text-[17px] font-semibold">Current queue impact</h3><div className="mt-5 divide-y divide-line">{[["Eligible for auto-approval", autoCount, "All safety conditions pass"], ["Assigned conversations", assignedCount, `Primary owner recorded out of ${open.length} open`], ["Human review required", reviewCount, "A governance or risk condition blocks automation"]].map(([label, count, meta]) => <div key={label} className="flex items-center justify-between py-4"><span><strong className="block text-sm">{label}</strong><small className="mt-1 block text-[13px] text-ink-faint">{meta}</small></span><strong className="text-[22px] font-semibold">{count}</strong></div>)}</div></div>
      </div>
      <div className="automation-surface mt-5 border border-line-strong bg-paper">
        <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line p-6"><div><h3 className="text-[17px] font-semibold tracking-[-0.02em]">Customer channels</h3><p className="mt-2 max-w-2xl text-sm leading-6 text-ink-muted">Only connected live channels can deliver an approved response.</p></div><Badge variant={hasDelivery ? "accent" : "neutral"}>{hasDelivery ? "Delivery available" : "Delivery unavailable"}</Badge></div>
        <div className="grid lg:grid-cols-[1fr_1fr_.8fr]">
          {[["Email", Mail, integrations?.email], ["WhatsApp", MessageCircle, integrations?.whatsapp]].map(([label, Icon, channel]) => <div key={label} className="border-b border-line p-6 lg:border-b-0 lg:border-r"><div className="flex items-center justify-between"><span className="flex items-center gap-2"><Icon className="size-4" /><strong className="text-[13px]">{label}</strong></span><Badge variant={channel?.configured ? "accent" : "neutral"}>{channel?.configured ? "Connected" : "Not connected"}</Badge></div></div>)}
          <div className="p-6"><div className="flex items-center gap-2"><Wrench className="size-4" /><strong className="text-[13px]">System health</strong></div><p className="mt-3 text-[13px] text-ink-muted">{deadJobs ? `${deadJobs} job${deadJobs === 1 ? "" : "s"} failed and need attention` : "No failed jobs"}{cancelledJobs ? ` · ${cancelledJobs} send${cancelledJobs === 1 ? "" : "s"} cancelled for re-review` : ""}</p></div>
        </div>
      </div>
      <div className="automation-surface mt-5 border border-line-strong bg-paper">
        <div className="border-b border-line p-6"><h3 className="text-[17px] font-semibold tracking-[-0.02em]">Approved response policies</h3><p className="mt-2 max-w-2xl text-sm leading-6 text-ink-muted">Kora retrieves matching policy text before drafting and records every cited version in the case audit.</p></div>
        <div className="grid lg:grid-cols-[1fr_1fr]">
          <div className="border-b border-line p-6 lg:border-b-0 lg:border-r">
            <div className="grid gap-4 sm:grid-cols-[1fr_140px]"><label className="automation-field">Policy title<Input value={policyDraft.title} maxLength={160} disabled={!canManage} onChange={(event) => setPolicyDraft({ ...policyDraft, title: event.target.value })} placeholder="Transfer reversal timeline" /></label><label className="automation-field">Version<Input value={policyDraft.version} maxLength={40} disabled={!canManage} onChange={(event) => setPolicyDraft({ ...policyDraft, version: event.target.value })} /></label></div>
            <label className="automation-field mt-4">Source URL (optional)<Input type="url" value={policyDraft.source_url} maxLength={1000} disabled={!canManage} onChange={(event) => setPolicyDraft({ ...policyDraft, source_url: event.target.value })} placeholder="https://company.example/policy" /></label>
            <label className="automation-field mt-4">Approved content<textarea value={policyDraft.content} maxLength={30000} disabled={!canManage} onChange={(event) => setPolicyDraft({ ...policyDraft, content: event.target.value })} rows={7} placeholder="Paste the exact approved policy, required information, timeline and escalation path." /></label>
            <Button className="mt-3" disabled={!canManage || policySaving || policyDraft.title.trim().length < 3 || policyDraft.content.trim().length < 20} onClick={async () => { const saved = await onCreatePolicy({ ...policyDraft, source_url: policyDraft.source_url || null }); if (saved) setPolicyDraft(EMPTY_POLICY); }}><BookOpenCheck className="size-4" />{policySaving ? "Saving policy" : "Approve policy"}</Button>
          </div>
          <div className="divide-y divide-line">{policies.length ? policies.map((policy) => <div key={policy.id} className="flex items-start justify-between gap-5 p-5"><div className="min-w-0"><div className="flex items-center gap-2"><strong className="truncate text-sm">{policy.title}</strong><Badge variant={policy.active ? "accent" : "neutral"} shape="pill">v{policy.version}</Badge></div><p className="mt-2 line-clamp-2 text-[13px] leading-5 text-ink-muted">{policy.content}</p></div><Switch aria-label={`${policy.active ? "Deactivate" : "Activate"} ${policy.title}`} checked={Boolean(policy.active)} disabled={!canManage} onCheckedChange={(active) => onTogglePolicy(policy.id, active)} /></div>) : <div className="p-6"><BookOpenCheck className="size-5 text-ink-faint" /><strong className="mt-3 block text-sm">No approved policies</strong><p className="mt-1 max-w-md text-[13px] leading-5 text-ink-muted">Drafts remain human-reviewed until the first company policy is added.</p></div>}</div>
        </div>
      </div>
    </div>
  );
}
