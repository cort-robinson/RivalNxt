import { useCallback, useMemo, useRef, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import {
  RefreshCw,
  CheckCircle,
  AlertTriangle,
  ArrowUpCircle,
  Loader2,
} from "lucide-react";
import type { Mod } from "./ModCard";
import {
  checkModUpdate,
} from "../lib/api";
import { distinctPendingUpdates, groupUpdateMods, updateLibraryFingerprint, updateModKey, type PendingModUpdate, type UpdateModGroup } from "../lib/updateUtils";
import { toast } from "sonner";

interface CheckForUpdatesModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mods: Mod[];
  libraryRevision?: number;
  onUpdateMod?: (modId: string, targetFileId?: number) => Promise<void> | void;
  onRefreshMods?: () => void;
  // Controlled state lifted to parent so results survive modal close/reopen
  statuses: Record<string, ModStatus>;
  onStatusesChange: (s: Record<string, ModStatus>) => void;
  checked: boolean;
  onCheckedChange: (c: boolean) => void;
  isCheckingAll: boolean;
  onIsCheckingAllChange: (v: boolean) => void;
}

export type ModUpdateStatus =
  | "idle"
  | "checking"
  | "up-to-date"
  | "has-update"
  | "error";

export interface ModStatus {
  status: ModUpdateStatus;
  error?: string;
  libraryFingerprint?: string;
  libraryRevision?: number;
  pendingVersions?: PendingModUpdate[];
}

const FALLBACK_IMG =
  "/icons/mod-placeholder.svg";

const formatVersionDisplay = (ver: string | undefined | null): string => {
  if (!ver) return "";
  const cleaned = ver.replace(/\.\d{9,11}$/, "");
  return cleaned.toLowerCase().startsWith("v") ? cleaned : `v${cleaned}`;
};



export function CheckForUpdatesModal({
  open,
  onOpenChange,
  mods,
  libraryRevision = 0,
  onUpdateMod,
  onRefreshMods,
  statuses,
  onStatusesChange,
  checked,
  onCheckedChange,
  isCheckingAll,
  onIsCheckingAllChange,
}: CheckForUpdatesModalProps) {
  const installedMods = useMemo(() => groupUpdateMods(mods), [mods]);
  const installedRef = useRef(installedMods);
  installedRef.current = installedMods;
  const revisionRef = useRef(libraryRevision);
  revisionRef.current = libraryRevision;
  const statusesRef = useRef(statuses);
  statusesRef.current = statuses;
  const checkingRef = useRef(false);
  const [isStartingUpdates, setIsStartingUpdates] = useState(false);
  const startingRef = useRef(false);

  const setModStatus = useCallback((mod: Mod, value: Omit<ModStatus, "libraryFingerprint">) => {
    const fingerprint = updateLibraryFingerprint(mod);
    const current = installedRef.current.find(m => updateModKey(m) === updateModKey(mod));
    if (!current || revisionRef.current !== libraryRevision || updateLibraryFingerprint(current) !== fingerprint) return;
    const next = { ...statusesRef.current, [updateModKey(mod)]: { ...value, libraryFingerprint: fingerprint, libraryRevision } };
    statusesRef.current = next;
    onStatusesChange(next);
  }, [onStatusesChange, libraryRevision]);

  const checkSingleMod = useCallback(async (mod: Mod) => {
    setModStatus(mod, { status: "checking" });
    try {
      const result = await checkModUpdate(mod.backendModId!);
      if (!result.ok || result.metadata_warning) throw new Error(result.metadata_warning || "Update check failed. Try again.");
      const pending = result.pending as Array<typeof result.pending[number] & { reference_file_id?: number; local_file_name?: string }>;
      setModStatus(mod, {
        status: result.needs_update ? "has-update" : "up-to-date",
        pendingVersions: distinctPendingUpdates((pending || []).map(p => ({
          local: p.local_version || "", latest: p.reference_version || "",
          referenceFileId: p.reference_file_id, pakName: p.pak_name || "",
          variantName: p.local_file_name || p.pak_name || "",
        }))),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Check failed. Try again.";
      setModStatus(mod, { status: "error", error: message });
      if (/429|rate.?limit|request.?limit|quota|too many requests/i.test(message)) return message;
    }
  }, [setModStatus]);

  const handleCheckAll = useCallback(async () => {
    if (checkingRef.current || isCheckingAll || installedMods.length === 0) return;
    checkingRef.current = true;
    onIsCheckingAllChange(true);
    onCheckedChange(false);
    statusesRef.current = {};
    onStatusesChange({});
    const toastId = "check-updates-modal";
    let next = 0;
    let done = 0;
    let rateLimitError: string | undefined;
    toast.loading(`Checking 0/${installedMods.length} mods…`, { id: toastId });
    try {
      await Promise.all(Array.from({ length: Math.min(3, installedMods.length) }, async () => {
        while (next < installedMods.length) {
          const mod = installedMods[next++];
          if (rateLimitError) {
            setModStatus(mod, { status: "error", error: `Not checked: ${rateLimitError}` });
          } else {
            const limited = await checkSingleMod(mod);
            if (limited) rateLimitError = limited;
          }
          toast.loading(`Checking ${++done}/${installedMods.length} mods…`, { id: toastId });
        }
      }));
      onCheckedChange(true);
      onRefreshMods?.();
    } finally {
      toast.dismiss(toastId);
      checkingRef.current = false;
      onIsCheckingAllChange(false);
    }
  }, [isCheckingAll, installedMods, checkSingleMod, setModStatus, onRefreshMods, onIsCheckingAllChange, onCheckedChange, onStatusesChange]);

  const getModStatus = useCallback((mod: Mod) => {
    const status = statuses[updateModKey(mod)];
    return status?.libraryFingerprint === updateLibraryFingerprint(mod) && (status.libraryRevision ?? 0) === libraryRevision ? status : undefined;
  }, [statuses, libraryRevision]);
  const getDerivedStatus = useCallback((mod: Mod): ModUpdateStatus =>
    getModStatus(mod)?.status || (mod.hasUpdate ? "has-update" : "idle"), [getModStatus]);
  const getPending = (mod: UpdateModGroup) => distinctPendingUpdates(getModStatus(mod)?.pendingVersions ?? mod.pendingUpdates);
  const modsWithUpdates = installedMods.filter(m => getDerivedStatus(m) === "has-update");
  const errorCount = installedMods.filter(m => getDerivedStatus(m) === "error").length;
  const incompleteCount = installedMods.filter(m => ["error", "idle"].includes(getDerivedStatus(m))).length;
  const allUpToDate = checked && incompleteCount === 0 && modsWithUpdates.length === 0 && !isCheckingAll;
  const visibleMods = installedMods.filter(m => ["has-update", "checking", "error"].includes(getDerivedStatus(m)));

  const handleUpdateAll = async () => {
    if (!onUpdateMod || startingRef.current) return;
    startingRef.current = true;
    setIsStartingUpdates(true);
    const requested = new Set<string>();
    try {
      for (const mod of modsWithUpdates) {
        const pending = getPending(mod);
        const targets = pending.length ? pending.map(p => p.referenceFileId ?? undefined) : [mod.latestFileId ?? undefined];
        for (const target of targets) {
          const key = `${updateModKey(mod)}:${target ?? "files"}`;
          if (requested.has(key)) continue;
          requested.add(key);
          await onUpdateMod(mod.id, target);
        }
      }
      toast.info("Download requests opened. Updates clear after the new files finish importing.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not start all downloads. Try the remaining files again.");
    } finally {
      startingRef.current = false;
      setIsStartingUpdates(false);
    }
  };

  // Stats for header
  const totalChecked = installedMods.filter((m) =>
    ["up-to-date", "has-update", "error"].includes(getDerivedStatus(m)),
  ).length;

  const accentGradient = isCheckingAll
    ? "linear-gradient(90deg, #8b5cf6, #6366f1)"
    : checked && modsWithUpdates.length > 0
    ? "linear-gradient(90deg, #ef4444, #f97316)"
    : allUpToDate
    ? "linear-gradient(90deg, #22c55e, #10b981)"
    : "linear-gradient(90deg, #3b82f6, #06b6d4)";

  const iconBg = isCheckingAll
    ? "linear-gradient(135deg, rgba(139,92,246,0.15), rgba(99,102,241,0.15))"
    : checked && modsWithUpdates.length > 0
    ? "linear-gradient(135deg, rgba(239,68,68,0.15), rgba(249,115,22,0.15))"
    : allUpToDate
    ? "linear-gradient(135deg, rgba(34,197,94,0.15), rgba(16,185,129,0.15))"
    : "linear-gradient(135deg, rgba(59,130,246,0.15), rgba(6,182,212,0.15))";

  const getStatusBadge = (mod: Mod) => {
    const status = getDerivedStatus(mod);
    if (status === "checking") return <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><Loader2 className="w-3.5 h-3.5 animate-spin" />Checking…</span>;
    if (status === "error") return <span className="flex items-center gap-1.5 text-xs text-red-700 dark:text-red-400"><AlertTriangle className="w-3.5 h-3.5" />Check failed</span>;
    return <span className="text-xs text-muted-foreground">Update available</span>;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="w-full bg-card p-0 flex flex-col shadow-2xl"
        style={{
          maxWidth: "min(900px, 95vw)",
          minWidth: "min(600px, 95vw)",
          width: "min(900px, 95vw)",
          height: "85vh",
          maxHeight: "85vh",
          border: "1px solid hsl(var(--border))",
          borderRadius: "16px",
          overflow: "hidden",
        }}
      >
        {/* Gradient accent bar */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: "4px",
            background: accentGradient,
            transition: "background 0.4s ease",
            zIndex: 50,
          }}
        />

        {/* Header */}
        <DialogHeader className="flex-shrink-0 pt-6">
          <div className="flex items-center justify-between w-full px-6 pt-2 pb-4 border-b border-border/60">
            <div className="flex items-center gap-3">
              {/* Icon Container */}
              <div
                style={{
                  width: "44px",
                  height: "44px",
                  borderRadius: "12px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: iconBg,
                  flexShrink: 0,
                  transition: "background 0.4s ease",
                }}
              >
                {isCheckingAll ? (
                  <Loader2 className="w-5 h-5 text-violet-400 animate-spin" />
                ) : checked && modsWithUpdates.length > 0 ? (
                  <ArrowUpCircle className="w-5 h-5 text-red-400 animate-pulse" />
                ) : allUpToDate ? (
                  <CheckCircle className="w-5 h-5 text-emerald-400" />
                ) : (
                  <RefreshCw className="w-5 h-5 text-blue-400" />
                )}
              </div>

              <div>
                <DialogTitle className="text-lg font-semibold tracking-tight">
                  Check for Updates
                </DialogTitle>
                <DialogDescription className="text-xs text-muted-foreground mt-0.5">
                  {installedMods.length} mod
                  {installedMods.length !== 1 ? "s" : ""} with Nexus IDs
                  {(checked || modsWithUpdates.length > 0)
                    ? ` · ${modsWithUpdates.length} update${modsWithUpdates.length !== 1 ? "s" : ""} available`
                    : ""}
                </DialogDescription>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {/* Update All — only disabled when checking is running or no updates are present */}
              <Button
                variant="default"
                size="sm"
                disabled={isCheckingAll || isStartingUpdates || !onUpdateMod || modsWithUpdates.length === 0}
                onClick={handleUpdateAll}
                className="gap-2 transition-all duration-300 hover:shadow-lg hover:shadow-red-500/20 active:scale-[0.98]"
                style={{
                  background: isCheckingAll || modsWithUpdates.length === 0
                    ? undefined
                    : "linear-gradient(135deg, #ef4444, #f97316)",
                  border: "none",
                  fontWeight: 600,
                }}
              >
                <ArrowUpCircle className="w-4 h-4" />
                {isStartingUpdates ? "Opening downloads…" : "Update All"}
                {modsWithUpdates.length > 0 && (
                  <Badge
                    variant="secondary"
                    className="ml-1 text-xs px-1.5 py-0 bg-white/20 text-white border-none"
                  >
                    {modsWithUpdates.length}
                  </Badge>
                )}
              </Button>

              <Button
                variant="outline"
                size="sm"
                disabled={isCheckingAll || isStartingUpdates || installedMods.length === 0}
                onClick={handleCheckAll}
                className="gap-2 transition-all duration-300 hover:bg-accent/50 active:scale-[0.98]"
                style={{
                  borderColor: isCheckingAll ? "rgba(139,92,246,0.2)" : "rgba(59,130,246,0.3)",
                  color: isCheckingAll ? "#a78bfa" : "#3b82f6",
                  fontWeight: 600,
                }}
              >
                <RefreshCw
                  className={`w-4 h-4 ${isCheckingAll ? "animate-spin" : ""}`}
                />
                {isCheckingAll
                  ? `Checking… (${totalChecked}/${installedMods.length})`
                  : checked
                    ? "Re-check All"
                    : "Check All"}
              </Button>
            </div>
          </div>
        </DialogHeader>

        {/* Scrollable mod list */}
        <style>{`
          .updates-modal-scroll::-webkit-scrollbar {
            width: 8px;
          }
          .updates-modal-scroll::-webkit-scrollbar-track {
            background: transparent;
          }
          .updates-modal-scroll::-webkit-scrollbar-thumb {
            background: rgba(100, 100, 100, 0.45);
            border-radius: 4px;
          }
          .updates-modal-scroll::-webkit-scrollbar-thumb:hover {
            background: rgba(100, 100, 100, 0.7);
          }
          .updates-modal-scroll {
            scrollbar-color: rgba(100, 100, 100, 0.45) transparent;
            scrollbar-width: thin;
          }
        `}</style>

        <div className="flex-1 min-h-0 overflow-y-auto updates-modal-scroll px-6 py-4">
          {installedMods.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
              <RefreshCw className="w-10 h-10 opacity-30" />
              <p className="text-sm font-medium">
                No installed mods are linked to Nexus IDs.
              </p>
            </div>
          ) : !checked && !isCheckingAll && visibleMods.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground text-center">
              <RefreshCw className="w-10 h-10 opacity-30 animate-pulse" />
              <div>
                <p className="text-sm font-medium text-foreground">
                  Ready to check for updates
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  Click the <strong>Check All</strong> button above to scan your {installedMods.length} mods.
                </p>
              </div>
            </div>
          ) : allUpToDate ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-green-500 text-center">
              <CheckCircle className="w-12 h-12 opacity-80 mx-auto animate-pulse" />
              <div>
                <p className="text-sm font-medium text-foreground">
                  All mods are up to date!
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  No updates were found for your installed mods.
                </p>
              </div>
            </div>
          ) : (
            <div className="grid gap-2">
              {checked && incompleteCount > 0 && !isCheckingAll && (
                <p role="status" className="text-sm text-muted-foreground mb-2">
                  {errorCount > 0 ? `${errorCount} mod check${errorCount === 1 ? "" : "s"} failed.` : "Your library changed during the check."} Re-check All to refresh the remaining results.
                </p>
              )}
              {visibleMods.map(mod => {
                const hasUpdate = getDerivedStatus(mod) === "has-update";
                const pending = getPending(mod);
                return (
                  <div key={updateModKey(mod)} className={`p-3.5 rounded-xl border ${hasUpdate ? "border-red-500/25 bg-red-500/5" : "border-border/60 bg-card"}`}>
                    <div className="flex items-center gap-4">
                      <img src={mod.images?.[0] || FALLBACK_IMG} alt="" className="w-14 h-10 rounded-lg object-cover flex-shrink-0" loading="lazy" onError={event => { event.currentTarget.onerror = null; event.currentTarget.src = FALLBACK_IMG; }} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold break-words">{mod.name}</p>
                        <p className="text-xs text-muted-foreground break-words">{mod.author ? `by ${mod.author}` : ""}</p>
                      </div>
                      {getStatusBadge(mod)}
                      {hasUpdate && onUpdateMod && <Button size="sm" variant="outline" disabled={isCheckingAll || isStartingUpdates} onClick={() => {
                        onOpenChange(false);
                        window.dispatchEvent(new CustomEvent("open-mod-modal", { detail: { modId: mod.id, tab: "files" } }));
                      }}>View files</Button>}
                    </div>
                    {hasUpdate && pending.length > 0 && <ul className="mt-3 space-y-2 border-t border-border/40 pt-3" aria-label={`${mod.name} file updates`}>
                      {pending.map((item, index) => <li key={item.referenceFileId ?? index} className="flex flex-wrap justify-between gap-x-4 gap-y-1 text-xs">
                        <span className="min-w-0 break-words text-foreground">{item.variantName || item.pakName || "Mod file"}</span>
                        <span className="text-muted-foreground">{formatVersionDisplay(item.local) || "Installed"} → {formatVersionDisplay(item.latest) || "New file"}</span>
                      </li>)}
                    </ul>}
                    {getDerivedStatus(mod) === "error" && <p className="mt-2 text-xs text-red-700 dark:text-red-400 break-words">{getModStatus(mod)?.error}</p>}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer hint */}
        {!checked && !isCheckingAll && installedMods.length > 0 ? (
          <div className="flex-shrink-0 py-1 border-t border-border/40">
            <p className="text-xs text-muted-foreground text-center">
              Click <strong>Check All</strong> to contact the Nexus API and
              refresh update status for all mods.
            </p>
          </div>
        ) : (
          <div className="h-6 flex-shrink-0" />
        )}
      </DialogContent>
    </Dialog>
  );
}

