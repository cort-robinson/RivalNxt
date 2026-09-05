import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { Button } from "./ui/button";
import { clearActivity, listActivity, listNxmHandoffs, cancelNxmHandoff, type ActivityEntry, type ApiNxmHandoffSummary } from "../lib/api";
import { clearOperations, listOperations, type Operation } from "../lib/activityApi";
import { openInBrowser } from "../lib/tauri-utils";

type Props = { open: boolean; onOpenChange: (open: boolean) => void; onOpenDownloads?: () => void; onOpenDiagnostics?: () => void; onOpenHealth?: () => void };
const label = (value?: string) => (value || "queued").replace(/_/g, " ");

export function ActivityDialog({ open, onOpenChange, onOpenDownloads, onOpenDiagnostics, onOpenHealth }: Props) {
  const [entries, setEntries] = useState<ActivityEntry[]>([]);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [handoffs, setHandoffs] = useState<ApiNxmHandoffSummary[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [cancelling, setCancelling] = useState<string[]>([]);
  useEffect(() => {
    if (!open) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      const results = await Promise.allSettled([listActivity(200), listOperations(), listNxmHandoffs()]);
      if (stopped) return;
      if (results[0].status === "fulfilled") setEntries(results[0].value);
      if (results[1].status === "fulfilled") setOperations(results[1].value);
      if (results[2].status === "fulfilled") setHandoffs(results[2].value);
      setError(results.some(result => result.status === "rejected") ? "Some activity could not refresh. Showing the last available results." : "");
      setLoading(false);
      timer = setTimeout(() => void load(), 3000);
    }
    void load();
    return () => { stopped = true; clearTimeout(timer); };
  }, [open, refresh]);
  async function cancel(id: string) {
    setCancelling(current => [...current, id]);
    try { await cancelNxmHandoff(id); setRefresh(value => value + 1); }
    catch { setError("Cancellation could not be requested. Refresh activity and try again."); }
    finally { setCancelling(current => current.filter(value => value !== id)); }
  }
  async function retryOnNexus(modId: number) {
    try { await openInBrowser(`https://www.nexusmods.com/marvelrivals/mods/${modId}?tab=files`); }
    catch { setError("Could not open Nexus Mods. Open the mod's Files page in your browser and choose Mod manager download."); }
  }
  async function clearHistory() {
    try { await clearOperations(); await clearActivity(); setRefresh(value => value + 1); }
    catch { setError("History could not be fully cleared. Refresh activity and try again."); }
  }
  const visible = operations.filter(item => !attentionOnly || ["failed", "interrupted"].includes(item.status));
  const active = handoffs.filter(item => !["complete", "completed", "cancelled"].includes(item.progress?.stage || "") && (!attentionOnly || item.progress?.stage === "failed"));
  const navigate = (action: () => void) => { onOpenChange(false); action(); };
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="max-w-2xl" style={{ width: "min(680px, calc(100vw - 32px))", maxWidth: "none", maxHeight: "85vh", overflowY: "auto" }}>
      <DialogHeader><DialogTitle>Activity</DialogTitle><DialogDescription>Downloads, file changes, backups, and failures. Recent operations remain available after restarting.</DialogDescription></DialogHeader>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={!attentionOnly ? "secondary" : "ghost"} aria-pressed={!attentionOnly} onClick={() => setAttentionOnly(false)}>All activity</Button>
        <Button size="sm" variant={attentionOnly ? "secondary" : "ghost"} aria-pressed={attentionOnly} onClick={() => setAttentionOnly(true)}>Needs attention</Button>
        <Button size="sm" variant="ghost" onClick={() => setRefresh(value => value + 1)}>Refresh activity</Button>
      </div>
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
      {loading ? <p role="status" className="text-sm">Loading activity…</p> : <>
        {active.length > 0 && <section aria-label="Downloads"><h3 className="font-semibold mb-2">Downloads</h3>
          <ul className="divide-y divide-border">{active.map(item => <li key={item.id} className="py-3 flex items-start gap-3">
            <div className="min-w-0 flex-1"><p className="text-sm font-medium break-words">{String(item.metadata?.mod_info?.name || `Nexus mod ${item.request?.mod_id || "download"}`)}</p>
              <p className="text-sm text-muted-foreground">{label(item.progress?.stage)}{typeof item.progress?.percent === "number" ? ` · ${Math.round(item.progress.percent)}%` : ""}</p>
              {item.progress?.error && <p className="text-sm text-destructive break-words">{item.progress.error}</p>}</div>
            {["downloading", "resolving", "queued", "pending", "preparing", "retrying"].includes(item.progress?.stage || "queued") && <Button size="sm" variant="outline" disabled={cancelling.includes(item.id)} onClick={() => void cancel(item.id)}>{cancelling.includes(item.id) ? "Requesting…" : "Cancel download"}</Button>}
            {item.progress?.stage === "failed" && Number.isSafeInteger(item.request?.mod_id) && (item.request?.mod_id || 0) > 0 && <Button size="sm" variant="outline" onClick={() => void retryOnNexus(item.request!.mod_id!)}>Open Nexus to retry</Button>}
          </li>)}</ul>
          {active.some(item => item.progress?.stage === "failed") && <p className="text-sm text-muted-foreground">For failed downloads, open the mod's Files page and choose Mod manager download for a fresh link.</p>}
          {onOpenDownloads && <Button size="sm" variant="outline" onClick={() => navigate(onOpenDownloads)}>Open downloads</Button>}
        </section>}
        <section aria-label="Operations"><h3 className="font-semibold mb-2">Operations</h3>
          {visible.length === 0 ? <p className="text-sm text-muted-foreground py-3">{attentionOnly ? "No failed or interrupted operations recorded." : "Your next import, activation, or backup will appear here."}</p> : <ul className="divide-y divide-border">{visible.map(item => <li key={item.id} className="py-3">
            <div className="flex flex-wrap justify-between gap-2"><p className="text-sm font-medium">{item.summary}</p><span className={`text-sm ${["failed", "interrupted"].includes(item.status) ? "text-destructive" : "text-muted-foreground"}`}>{label(item.status)}</span></div>
            {item.detail && <p className="text-sm text-muted-foreground">{item.detail}</p>}
            {item.status === "interrupted" && <p className="text-sm text-muted-foreground">The app closed before a result was recorded. Review your mods before repeating this action.</p>}
            <time dateTime={item.at} className="text-xs text-muted-foreground">{new Date(item.at).toLocaleString()}</time>
          </li>)}</ul>}
        </section>
        {!attentionOnly && entries.length > 0 && <details><summary className="text-sm cursor-pointer font-medium">Detailed change history ({entries.length})</summary><ul className="divide-y divide-border">{entries.map(item => <li key={item.id} className="py-2"><p className="text-sm break-words">{item.summary}</p>{item.detail && <p className="text-xs text-muted-foreground break-words">{item.detail}</p>}<time className="text-xs text-muted-foreground" dateTime={item.at}>{new Date(item.at).toLocaleString()}</time></li>)}</ul></details>}
      </>}
      <div className="flex flex-wrap gap-2">{onOpenHealth && <Button size="sm" variant="outline" onClick={() => navigate(onOpenHealth)}>Review mod health</Button>}{onOpenDiagnostics && <Button size="sm" variant="outline" onClick={() => navigate(onOpenDiagnostics)}>Export diagnostics</Button>}{(entries.length > 0 || operations.some(item => item.status !== "running")) && <Button size="sm" variant="ghost" onClick={() => void clearHistory()}>Clear finished history</Button>}</div>
    </DialogContent>
  </Dialog>;
}
