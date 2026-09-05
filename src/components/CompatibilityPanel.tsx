import { useId, useState } from "react";
import { ChevronDown, Wrench } from "lucide-react";
import { Button } from "./ui/button";
import "../styles/compatibility.css";
import {
  scanCompatibility, repairCompatibility, restoreCompatibility,
  type CompatibilityReport, type CompatibilityResult,
} from "../lib/api";

type Panel = "results" | "backups" | "about";
type Action = "scan" | "repair" | "restore";
const needsAttention = (row: CompatibilityResult) =>
  row.archive === "repair_needed" || row.archive === "blocked" || row.archive === "failed";
const packageCount = (count: number) => `${count} package${count === 1 ? "" : "s"}`;
const labels = {
  repair_needed: "Needs repair", checked: "No repair needed", repaired: "Repaired",
  blocked: "Could not check", failed: "Repair failed",
};

function PackageResult({ row }: { row: CompatibilityResult }) {
  const filename = row.path.split(/[\\/]/).pop() || row.path;
  const name = filename.replace(/\.(pak|utoc|ucas)$/i, "").replace(/_\d+_P$/i, "");
  return <li>
    <details className="compatibility-package">
      <summary>
        <span className="compatibility-package-name">{name}</span>
        <span className="compatibility-package-status">{labels[row.archive]}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </summary>
      <div className="compatibility-package-details">
        {row.error ? <p>{row.error}</p> : null}
        <dl>
          <dt>File</dt><dd>{row.path}</dd>
          {row.removed_entries?.length ? <>
            <dt>{row.archive === "repaired" ? "Entries removed" : "Outdated entries"}</dt>
            <dd>{row.removed_entries.join(", ")}</dd>
          </> : null}
          {row.content_notes?.length ? <>
            <dt>Technical notes</dt><dd>{row.content_notes.join(", ")}</dd>
          </> : null}
        </dl>
      </div>
    </details>
  </li>;
}

export function CompatibilityPanel() {
  const id = useId();
  const [report, setReport] = useState<CompatibilityReport | null>(null);
  const [busy, setBusy] = useState<Action | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [panel, setPanel] = useState<Panel | null>(null);
  const [showAll, setShowAll] = useState(false);

  const rows = report?.results || [];
  const attention = rows.filter(needsAttention);
  const repairCount = rows.filter(row => row.archive === "repair_needed").length;
  const reviewCount = attention.length - repairCount;
  const repairedCount = rows.filter(row => row.archive === "repaired").length;
  const backups = report?.backups.filter(backup => backup.state !== "restored") || [];
  const canRepair = repairCount > 0 && !error;

  let summary = "Check installed mods for outdated patch files.";
  if (report) {
    if (repairCount) summary = `${packageCount(repairCount)} ${repairCount === 1 ? "needs" : "need"} repair`;
    else if (reviewCount) summary = `${packageCount(reviewCount)} ${reviewCount === 1 ? "needs" : "need"} a manual check`;
    else if (repairedCount) summary = `Repaired ${packageCount(repairedCount)}`;
    else summary = rows.length ? "No outdated patch files found" : "No installed mod packages found";
  }
  if (error) summary = "Check again to get current results.";
  if (busy) summary = {
    scan: "Checking installed mods…", repair: "Saving backups and repairing files…", restore: "Restoring saved files…",
  }[busy];

  async function run(action: Action, backupId?: string) {
    setBusy(action);
    setError("");
    setNotice("");
    try {
      if (action === "restore" && backupId) {
        await restoreCompatibility(backupId);
        setNotice("Backup restored.");
        // A failed follow-up scan must not leave the pre-restore report current.
        setReport(null);
      }
      const next = action === "repair" ? await repairCompatibility() : await scanCompatibility();
      setReport(next);
      setShowAll(false);
      setPanel(next.results.some(row => row.archive === "blocked" || row.archive === "failed") ? "results" : null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The operation could not finish. Try checking again.");
    } finally {
      setBusy(null);
    }
  }

  function togglePanel(next: Panel) {
    setPanel(current => current === next ? null : next);
  }

  return (
    <section className="compatibility-panel" aria-labelledby={`${id}-title`}>
      <div className="compatibility-overview">
        <div className="compatibility-copy">
          <h3 id={`${id}-title`}><Wrench size={16} aria-hidden="true" />Patch compatibility</h3>
          <p className="compatibility-summary" role="status">{summary}</p>
          {report && !busy && !error && rows.length ? <p className="compatibility-meta">
            {packageCount(rows.length)} checked.
            {repairCount && reviewCount ? ` ${reviewCount} ${reviewCount === 1 ? "needs" : "need"} a manual check.` : ""}
            {repairedCount ? " Backups saved." : ""}
          </p> : null}
        </div>
        <div className="compatibility-actions">
          {canRepair ? <Button variant="outline" size="sm" disabled={Boolean(busy)}
            onClick={() => void run("scan")}>Check again</Button> : null}
          <Button size="sm" disabled={Boolean(busy)} onClick={() => void run(canRepair ? "repair" : "scan")}>
            {busy ? "Please wait…" : canRepair ? `Repair ${packageCount(repairCount)}` : report || error ? "Check again" : "Check mods"}
          </Button>
        </div>
      </div>
      {canRepair && !busy ? <p className="compatibility-hint">Close the game before repairing. A backup is saved first.</p> : null}
      {notice ? <p className="compatibility-hint" role="status">{notice}</p> : null}
      {error ? <p className="compatibility-error" role="alert">{error}</p> : null}
      <div className="compatibility-footer">
        <p>In-game compatibility is untested.</p>
        <div className="compatibility-links">
          {report && rows.length ? <button type="button" aria-expanded={panel === "results"} aria-controls={`${id}-results`}
            onClick={() => togglePanel("results")}>
            {attention.length ? `Review ${packageCount(attention.length)}` : "View results"}
          </button> : null}
          {backups.length ? <button type="button" aria-expanded={panel === "backups"} aria-controls={`${id}-backups`}
            onClick={() => togglePanel("backups")}>Backups ({backups.length})</button> : null}
          <button type="button" aria-expanded={panel === "about"} aria-controls={`${id}-about`}
            onClick={() => togglePanel("about")}>About this check</button>
        </div>
      </div>

      {panel === "results" && report ? <div className="compatibility-expanded" id={`${id}-results`}>
        {error ? <p className="compatibility-meta">Previous results. Check again before taking action.</p> : null}
        <div className="compatibility-result-controls">
          {attention.length ? <div className="compatibility-filters" role="group" aria-label="Filter package results">
            <button type="button" aria-pressed={!showAll} onClick={() => setShowAll(false)}>Needs attention ({attention.length})</button>
            <button type="button" aria-pressed={showAll} onClick={() => setShowAll(true)}>All packages ({rows.length})</button>
          </div> : <span>{packageCount(rows.length)}</span>}
          <span className="compatibility-meta">Select a package for details</span>
        </div>
        <ul className="compatibility-results" aria-label="Package results" tabIndex={0}>
          {(attention.length && !showAll ? attention : rows).map(row => <PackageResult key={row.path} row={row} />)}
        </ul>
      </div> : null}

      {panel === "backups" ? <div className="compatibility-expanded" id={`${id}-backups`}>
        <p className="compatibility-explanation">Restore files to their state before a repair or install. Close the game first. Later file changes are protected.</p>
        <ul className="compatibility-backups" aria-label="Saved backups">
          {backups.map((backup, index) => {
            const date = backup.created_at ? new Date(backup.created_at) : null;
            const label = date && !Number.isNaN(date.getTime()) ? date.toLocaleString() : `Backup ${index + 1}`;
            return <li key={backup.id}>
              <div><p>{label}</p><p className="compatibility-meta">{backup.files} file{backup.files === 1 ? "" : "s"}{backup.state === "prepared" ? " · Interrupted operation" : ""}</p></div>
              <Button variant="outline" size="sm" disabled={Boolean(busy)} aria-label={`Restore ${label}`}
                onClick={() => void run("restore", backup.id)}>Restore</Button>
            </li>;
          })}
        </ul>
      </div> : null}

      {panel === "about" ? <div className="compatibility-expanded compatibility-explanation" id={`${id}-about`}>
        <p>This checks for outdated entries in mod package indexes. A mod can contain several packages, so this count can differ from your mod count. New installs receive this check automatically.</p>
        <p>Repairs save verified backups and preserve the other package content. Companion UTOC and UCAS files stay unchanged.</p>
        <p>A clean file check does not confirm that a mod works in the game. Audio, visual effects, movies, configuration, camera-shake and IoStore assets still need an in-game check.</p>
      </div> : null}
    </section>
  );
}
