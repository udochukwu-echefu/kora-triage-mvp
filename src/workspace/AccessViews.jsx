import { useState } from "react";
import { KeyRound, LoaderCircle } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";

function AccessCard({ label, title, children, labelledBy }) {
  return (
    <main className="grid min-h-screen place-items-center bg-canvas px-6 text-ink">
      <section className="w-full max-w-sm border border-line-strong bg-paper p-7 shadow-precision" aria-labelledby={labelledBy}>
        <div className="grid size-10 place-items-center bg-ink text-sm font-extrabold text-paper">KR</div>
        <p className="section-label mt-8">{label}</p>
        <h1 id={labelledBy} className="mt-2 text-[24px] font-extrabold tracking-[-0.05em]">{title}</h1>
        {children}
      </section>
    </main>
  );
}

// Token deployments: an administrator issues tokens with `python -m app.manage create-token`.
export function SignInView({ onSignIn, error }) {
  const [token, setTokenValue] = useState("");
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    if (!token.trim()) return;
    setBusy(true);
    try {
      await onSignIn(token.trim(), remember);
    } finally {
      setBusy(false);
    }
  };
  return (
    <AccessCard label="Secure workspace" title="Sign in to Kora" labelledBy="sign-in-title">
      <form className="mt-5 grid gap-4" onSubmit={submit}>
        <p className="text-[13px] leading-5 text-ink-muted">Paste the access token your administrator issued. It is sent only to this Kora server.</p>
        <label className="grid gap-2 text-[13px] font-semibold">Access token
          <Input type="password" autoComplete="current-password" value={token} onChange={(event) => setTokenValue(event.target.value)} placeholder="kora_…" aria-invalid={Boolean(error)} aria-describedby={error ? "sign-in-error" : undefined} />
        </label>
        <label className="flex items-center gap-2 text-[13px] text-ink-muted"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />Keep me signed in on this device</label>
        {error && <p id="sign-in-error" role="alert" className="text-[13px] font-semibold text-accent-strong">{error}</p>}
        <Button type="submit" disabled={busy || !token.trim()} className="w-full">{busy ? <LoaderCircle className="size-4 animate-spin" /> : <KeyRound className="size-4" />}Sign in</Button>
      </form>
    </AccessCard>
  );
}

export function DemoSignedOutView({ onReturn }) {
  return (
    <AccessCard label="Demo workspace" title="You have left the demo" labelledBy="signed-out-title">
      <p className="mt-3 text-[13px] leading-5 text-ink-muted">This public demo has no personal accounts, so there is nothing to sign out of. Production deployments use access tokens issued per teammate.</p>
      <Button onClick={onReturn} className="mt-7 w-full">Return to the demo</Button>
    </AccessCard>
  );
}
