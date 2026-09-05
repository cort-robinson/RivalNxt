import { useState } from "react";
import { Button } from "./ui/button";
import "../styles/compatibility.css";
import {
  scanCompatibility, repairCompatibility, restoreCompatibility,
  type CompatibilityReport,
} from "../lib/api";

const labels = {
  repair_needed: "Index repair needed",
  checked: "Index checked",
  repaired: "Index repaired and checked",
  blocked: "Check blocked",
  failed: "Repair failed",
};

export function CompatibilityPanel() {
  const [report, setReport] = useState<CompatibilityReport | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function run(action: "scan" | "repair" | "restore", id?: string) {
    setBusy(action);
    setError("");
    try {
      if (action === "restore" && id) await restoreCompatibility(id);
      setReport(action === "repair" ? await repairCompatibility() : await scanCompatibility());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The file operation failed. Try a new scan.");
    } finally {
      setBusy("");
    }
  }

  return (
    <details className="compatibility-panel mx-4 my-3 rounded-lg border border-border bg-card p-4">
      <summary className="cursor-pointer font-medium focus-visible:outline focus-visible:outline-2">
        Patch compatibility
      </summary>
      <div className="mt-3 space-y-3 text-sm" aria-busy={Boolean(busy)}>
        <p className="compatibility-intro text-muted-foreground">
          Check installed mod indexes and remove old repak entries. New installs receive this check automatically.
          Repairs save verified PAK backups. UTOC and UCAS files stay unchanged.
        </p>
        <p className="compatibility-intro">In-game compatibility is unknown. Audio, VFX, movie, config, camera-shake and IoStore assets need a separate game check. Close the game before a repair or restore.</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={Boolean(busy)} onClick={() => void run("scan")}>Scan installed mods</Button>
          <Button disabled={Boolean(busy) || !report?.results.some(row => row.archive === "repair_needed")}
            onClick={() => void run("repair")}>Repair old indexes</Button>
        </div>
        {busy ? <p role="status">{busy === "scan" ? "Checking files…" : busy === "repair" ? "Saving backups and repairing indexes…" : "Restoring saved files…"}</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        {report ? <div role="status">{report.results.length} packages checked. In-game compatibility: unknown.</div> : null}
        {report && report.results.length === 0 ? <p>No mod packages found in ~mods.</p> : null}
        {report?.results.length ? <ul className="compatibility-results divide-y divide-border" aria-label="Package check results" tabIndex={0}>
          {report.results.map(row => <li key={row.path} className="py-3 space-y-1">
            <p className="break-all font-medium">{row.path}</p>
            <p>{labels[row.archive]}</p>
            {row.content_notes?.length ? <p className="text-muted-foreground">{row.content_notes.join(", ")}</p> : null}
            {row.removed_entries?.length ? <p className="break-all text-muted-foreground">Old entries: {row.removed_entries.join(", ")}</p> : null}
            {row.error ? <p>{row.error}</p> : null}
          </li>)}
        </ul> : null}
        {report?.backups.some(backup => backup.state !== "restored") ? <details>
          <summary className="cursor-pointer">Restore saved files</summary>
          <p className="my-2">Restore returns files to their state before repair or install. It stops if later changes would be lost.</p>
          <ul className="compatibility-backups space-y-2">
            {report.backups.filter(backup => backup.state !== "restored").map(backup => <li key={backup.id} className="flex flex-wrap items-center gap-2">
              <span className="break-all">{backup.created_at ? new Date(backup.created_at).toLocaleString() : backup.id} · {backup.files} files · {backup.state}</span>
              <Button variant="outline" size="sm" disabled={Boolean(busy)} aria-label={`Restore backup ${backup.id}`}
                onClick={() => void run("restore", backup.id)}>Restore</Button>
            </li>)}
          </ul>
        </details> : null}
      </div>
    </details>
  );
}
