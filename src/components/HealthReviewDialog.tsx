import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { Button } from "./ui/button";
import { getGameVersionCheck, scanCompatibility, type GameVersionCheckResponse, type CompatibilityReport } from "../lib/api";

type Props = { open: boolean; onOpenChange: (open: boolean) => void; onOpenSettings: () => void; onOpenPackages: () => void; onOpenBackups: () => void };

/** Read-only review; repair and restore retain their existing recovery UI. */
export function HealthReviewDialog({ open, onOpenChange, onOpenSettings, onOpenPackages, onOpenBackups }: Props) {
  const [game, setGame] = useState<GameVersionCheckResponse | null>(null);
  const [packages, setPackages] = useState<CompatibilityReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!open) return;
    let stopped = false;
    setBusy(true); setError(""); setGame(null); setPackages(null);
    void Promise.allSettled([getGameVersionCheck(), scanCompatibility()]).then(([gameResult, packageResult]) => {
      if (stopped) return;
      if (gameResult.status === "fulfilled") setGame(gameResult.value);
      if (packageResult.status === "fulfilled") setPackages(packageResult.value);
      setError([gameResult.status === "rejected" ? "Game files could not be checked." : "", packageResult.status === "rejected" ? "Installed packages could not be checked." : ""].filter(Boolean).join(" "));
      setBusy(false);
    });
    return () => { stopped = true; };
  }, [open, refresh]);
  const attention = packages?.results.filter(item => ["repair_needed", "blocked", "failed"].includes(item.archive)) || [];
  const missing = attention.filter(item => /companion.*missing|missing.*companion/i.test(item.error || ""));
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="max-w-2xl" style={{ width: "min(680px, calc(100vw - 32px))", maxWidth: "none", maxHeight: "85vh", overflowY: "auto" }}>
      <DialogHeader><DialogTitle>Post-patch health review</DialogTitle><DialogDescription>Review game files, installed package integrity, and recovery options before your next session.</DialogDescription></DialogHeader>
      {busy && <p role="status" className="text-sm">Checking game files and installed packages…</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error} Try again, or check your game path in Settings.</p>}
      <section aria-label="Game files"><h3 className="font-semibold">Game files</h3>
        <p className="text-sm text-muted-foreground">{game ? game.ok ? `${game.file_count} files found. Latest change: ${game.latest_modified ? new Date(game.latest_modified).toLocaleString() : "unknown"}.` : game.error || "Game files unavailable." : "Game file status unavailable until the check completes."}</p>
        {game?.latest_file && <p className="text-xs text-muted-foreground break-words">Last changed: {game.latest_file}</p>}
        <p className="text-sm text-muted-foreground mt-2">File timestamps detect local changes; they do not confirm that the game is on its latest published patch.</p>
      </section>
      <section aria-label="Package integrity"><h3 className="font-semibold">Package integrity</h3>
        <p className="text-sm text-muted-foreground">{packages ? `${packages.results.length} installed packages checked. ${attention.length} need attention. ${missing.length} have missing companion files.` : "Package status unavailable until the check completes."}</p>
        {packages?.results.length === 0 && <p className="text-sm text-muted-foreground">No installed mod packages found.</p>}
        {attention.length > 0 && <ul className="divide-y divide-border mt-2">{attention.map(item => <li key={item.path} className="py-2"><p className="text-sm font-medium break-words">{item.path.split(/[\\/]/).pop()}</p><p className="text-sm text-muted-foreground">{item.error || (item.archive === "repair_needed" ? "Outdated package entries can be repaired from Active Mods." : "This package needs a manual review.")}</p></li>)}</ul>}
        {missing.length > 0 && <p className="text-sm mt-2">Re-download the complete affected mod or disable it. Index repair cannot replace missing companion files.</p>}
      </section>
      <section aria-label="In-game compatibility"><h3 className="font-semibold">In-game compatibility: unknown</h3><p className="text-sm text-muted-foreground">A clean package check does not prove that a mod works with the current game patch. Review the mod author's update notes and test in game.</p></section>
      <section aria-label="Recovery"><h3 className="font-semibold">Recovery</h3><p className="text-sm text-muted-foreground">Active Mods contains package repair and saved package backups. Close the game before repairing or restoring. Restore mod-manager backups from the backup manager.</p><p className="text-sm text-muted-foreground">{packages ? `${packages.backups.filter(item => item.state !== "restored").length} package backups available.` : "Backup availability has not been checked."}</p></section>
      <div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => setRefresh(value => value + 1)}>{busy ? "Checking…" : "Check again"}</Button><Button variant="outline" onClick={() => { onOpenChange(false); onOpenPackages(); }}>Open package repair</Button><Button variant="outline" onClick={() => { onOpenChange(false); onOpenBackups(); }}>Open backup manager</Button><Button variant="ghost" onClick={() => { onOpenChange(false); onOpenSettings(); }}>Game path settings</Button></div>
    </DialogContent>
  </Dialog>;
}
