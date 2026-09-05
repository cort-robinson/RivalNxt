import { useEffect, useState } from "react";
import { getJson } from "../lib/api";
import { recoverActivation } from "../lib/activationApi";
import { Button } from "./ui/button";

export function RecoveryNotice({ onRecovered, onDiagnostics }: {
  onRecovered: () => void;
  onDiagnostics: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [journalFolder, setJournalFolder] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function check() {
      try {
        const status = await getJson<{ recovery_required: boolean; journal_folder?: string }>("/api/activation/status");
        if (alive) { setPending(status.recovery_required); setJournalFolder(status.journal_folder || ""); }
      } catch { /* Backend startup/disconnect is handled by the startup overlay. */ }
      if (alive) timer = setTimeout(() => void check(), 10000);
    }
    void check();
    return () => { alive = false; clearTimeout(timer); };
  }, []);
  if (!pending) return null;
  async function recover() {
    setBusy(true); setError("");
    try { await recoverActivation(); setPending(false); onRecovered(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Recovery could not complete. Keep the saved journal and review diagnostics."); }
    finally { setBusy(false); }
  }
  return <section role="alert" className="border-b border-border bg-card p-4 space-y-2">
    <h2 className="font-semibold">An interrupted switch needs recovery</h2>
    <p className="text-sm text-muted-foreground">Mod changes are paused. Recovery checks saved files before restoring the previous selection. If files changed afterward, it stops for manual review.</p>
    {journalFolder ? <p className="text-sm text-muted-foreground break-all">Saved recovery files: {journalFolder}</p> : null}
    {error ? <p className="text-sm text-destructive break-words">{error}</p> : null}
    <div className="flex gap-2"><Button size="sm" disabled={busy} onClick={() => void recover()}>{busy ? "Checking recovery…" : "Recover previous selection"}</Button>
      <Button size="sm" variant="outline" disabled={busy} onClick={onDiagnostics}>View diagnostics</Button></div>
  </section>;
}
