import { useEffect, useRef, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import type { Update } from "@tauri-apps/plugin-updater";
import { Button } from "./ui/button";

/** User-initiated updates. The caller must create a safety backup before installation. */
export function UpdatePanel({ beforeInstall, onBusyChange }: { beforeInstall: () => Promise<void>; onBusyChange?: (busy: boolean) => void }) {
  const update = useRef<Update | null>(null);
  const mounted = useRef(true);
  const busyRef = useRef(false);
  const [available, setAvailable] = useState<{ version: string; body?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (!busyRef.current) void update.current?.close();
    };
  }, []);

  async function checkUpdates() {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); onBusyChange?.(true); setError(""); setStatus("Checking for updates…");
    try {
      await update.current?.close(); update.current = null; setAvailable(null);
      const { check } = await import("@tauri-apps/plugin-updater");
      const next = await check({ timeout: 30000 });
      if (!mounted.current) { await next?.close(); return; }
      update.current = next;
      setAvailable(next ? { version: next.version, body: next.body } : null);
      setStatus(next ? `Version ${next.version} is ready to download.` : "You’re running the latest version.");
    } catch (reason) {
      setStatus(""); setError(`Could not check for updates. Check your connection and try again. ${String(reason)}`);
    } finally { busyRef.current = false; onBusyChange?.(false); if (mounted.current) setBusy(false); }
  }

  async function install() {
    const next = update.current;
    if (!next || busyRef.current) return;
    busyRef.current = true; setBusy(true); onBusyChange?.(true); setError("");
    try {
      setStatus("Creating a safety backup…");
      await beforeInstall();
      setStatus("Downloading and verifying the signed update…");
      let received = 0;
      let total = 0;
      await next.downloadAndInstall(event => {
        if (!mounted.current) return;
        if (event.event === "Started") total = event.data.contentLength ?? 0;
        if (event.event === "Progress") {
          received += event.data.chunkLength;
          setStatus(total ? `Downloading update: ${Math.min(100, Math.round(received / total * 100))}%` : "Downloading update…");
        }
        if (event.event === "Finished") setStatus("Verifying the update and starting the installer…");
      });
      setStatus("The installer is starting. RivalNxt will close to finish the update.");
    } catch (reason) {
      setStatus(""); setError(`The update could not be installed. You can retry when ready. ${String(reason)}`);
    } finally {
      busyRef.current = false;
      onBusyChange?.(false);
      if (mounted.current) setBusy(false);
      else await next.close();
    }
  }

  return <section aria-labelledby="app-updates-title" className="space-y-3">
    <h3 id="app-updates-title" className="font-semibold">App updates</h3>
    <p className="text-sm text-muted-foreground">Get releases from cort-robinson/RivalNxt. Installing creates a safety backup and closes the app.</p>
    {!isTauri() ? <p className="text-sm">Open the desktop app to check for updates.</p> : <>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={busy} onClick={() => void checkUpdates()}>Check for updates</Button>
        {available ? <Button disabled={busy} onClick={() => void install()}>Install version {available.version}</Button> : null}
      </div>
      <p role="status" className="text-sm">{status}</p>
      {error ? <p role="alert" className="text-sm text-destructive break-words">{error}</p> : null}
      {available ? <details open className="text-sm"><summary className="cursor-pointer font-medium">Release notes</summary>
        <div className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words">{available.body || "No release notes were provided for this update."}</div>
      </details> : null}
    </>}
  </section>;
}
