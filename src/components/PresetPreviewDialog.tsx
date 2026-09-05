import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { Button } from "./ui/button";
import type { Loadout } from "../lib/backupUtils";
import { applyActivation, previewActivation, recoverActivation, type ActivationPlan } from "../lib/activationApi";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  loadout?: Loadout | null;
  initialPlan?: ActivationPlan | null;
  title?: string;
  onApplied?: () => void;
  allowUnchanged?: boolean;
  description?: string;
  refreshPreview?: () => Promise<ActivationPlan>;
}

export function PresetPreviewDialog({ open, onOpenChange, loadout, initialPlan, title, onApplied, allowUnchanged, description, refreshPreview }: Props) {
  const [plan, setPlan] = useState<ActivationPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    let active = true;
    setError("");
    setLoading(false);
    setPlan(initialPlan ?? null);
    if (initialPlan || !loadout) return;
    setLoading(true);
    previewActivation(loadout.entries, loadout.downloadPaths).then((value) => {
      if (active) setPlan(value);
    }).catch((failure) => {
      if (active) setError(failure instanceof Error ? failure.message : "Could not preview this preset.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, loadout, initialPlan]);

  async function refresh(recover = false) {
    setBusy(true);
    setError("");
    try {
      if (recover) await recoverActivation();
      const entries = loadout?.entries ?? plan?.entries;
      if (refreshPreview) setPlan(await refreshPreview());
      else if (entries) setPlan(await previewActivation(entries, loadout?.downloadPaths ?? plan?.download_paths));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not refresh the preview.");
    } finally { setBusy(false); }
  }

  async function apply() {
    if (!plan) return;
    setBusy(true);
    setError("");
    try {
      await applyActivation(plan);
      onApplied?.();
      onOpenChange(false);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The switch could not be completed.");
      // A rejected or rolled-back request never remains actionable with an old token.
      setPlan((value) => value ? { ...value, can_apply: false } : value);
    } finally { setBusy(false); }
  }

  return <Dialog open={open} onOpenChange={(next) => { if (!busy) onOpenChange(next); }}>
    <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{title ?? `Switch to ${loadout?.name ?? "this selection"}`}</DialogTitle>
        <DialogDescription>{description ?? "Review the exact file changes. A failed switch attempts to restore the previous files and selection. Interrupted recovery stops if files changed."}</DialogDescription>
      </DialogHeader>
      {loading ? <p role="status">Checking installed downloads and game files…</p> : null}
      {error ? <p role="alert" className="text-sm text-destructive break-words">{error}</p> : null}
      {plan?.recovery_required ? <div role="alert" className="space-y-2">
        <p className="text-sm">An interrupted switch needs recovery before another selection can be applied.</p>
        <Button variant="outline" disabled={busy} onClick={() => void refresh(true)}>Recover previous selection</Button>
      </div> : null}
      {plan?.missing.length ? <div className="space-y-2">
        <h3 className="font-semibold">Restore these downloads before switching</h3>
        <ul className="text-sm space-y-2">{plan.missing.map((item) => <li key={item.download_id}>
          <span className="font-medium">{item.name}</span> — {item.reason}
          {item.files?.length ? <p className="text-muted-foreground break-all">{item.files.join(", ")}</p> : null}
        </li>)}</ul>
      </div> : null}
      {plan ? <div className="divide-y divide-border">
        {plan.changes.length === 0 ? <p className="py-4 text-sm text-muted-foreground">This selection is already active.</p> : plan.changes.map((change) => {
          const disabled = change.before.filter((p) => !change.after.includes(p));
          const enabled = change.after.filter((p) => !change.before.includes(p));
          return <div key={change.download_id} className="py-3 space-y-1">
            <h3 className="font-medium break-words">{change.name}</h3>
            {disabled.length ? <p className="text-sm break-all"><span className="text-muted-foreground">Disable: </span>{disabled.join(", ")}</p> : null}
            {enabled.length ? <p className="text-sm break-all"><span className="text-muted-foreground">Enable: </span>{enabled.join(", ")}</p> : null}
          </div>;
        })}
      </div> : null}
      <div className="flex flex-wrap justify-end gap-2 pt-2">
        <Button variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="outline" disabled={busy || loading} onClick={() => void refresh()}>Refresh preview</Button>
        <Button disabled={busy || loading || !plan?.can_apply || (!allowUnchanged && !plan.changes.length)} onClick={() => void apply()}>
          {busy ? "Working…" : "Apply selection"}
        </Button>
      </div>
    </DialogContent>
  </Dialog>;
}
