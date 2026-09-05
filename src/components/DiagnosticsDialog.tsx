import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Download, Loader2, RefreshCw } from "lucide-react";
import { getJson } from "../lib/api";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";

type Preview = { filename: string; text: string };

export function DiagnosticsDialog({ open, onOpenChange }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [revision, setRevision] = useState(0);
  const savingRef = useRef(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setPreview(null);
    setError("");
    setSaved(false);
    getJson<Preview>("/api/diagnostics").then((data) => {
      if (!cancelled) setPreview(data);
    }).catch(() => {
      if (!cancelled) setError("Could not prepare diagnostics. Check that the backend is running, then try again.");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [open, revision]);

  async function save() {
    if (!preview || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError("");
    try {
      if ("__TAURI_INTERNALS__" in window) {
        const path = await invoke<string>("save_file_dialog", {
          defaultName: preview.filename, filterExtensions: ["json"],
        });
        if (!path) return;
        await invoke("save_text_file", { path, content: preview.text });
      } else {
        const url = URL.createObjectURL(new Blob([preview.text], { type: "application/json" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = preview.filename;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      setSaved(true);
    } catch (cause) {
      if (!String(cause).toLowerCase().includes("cancel")) {
        setError("The report could not be saved. Choose a writable folder and try again.");
      }
    } finally { savingRef.current = false; setSaving(false); }
  }

  return <Dialog open={open} onOpenChange={(next) => { if (!savingRef.current) onOpenChange(next); }}>
    <DialogContent className="max-w-3xl max-h-[90vh] flex flex-col overflow-hidden" style={{ width: "min(760px, calc(100vw - 32px))", maxWidth: "none" }}>
      <DialogHeader>
        <DialogTitle>Diagnostics</DialogTitle>
        <DialogDescription>
          Review the exact report before saving. It includes versions, recent activity and available logs.
          Credentials and local paths are redacted. Nothing is sent automatically.
        </DialogDescription>
      </DialogHeader>
      {loading ? <p role="status" className="flex items-center gap-2 py-8"><Loader2 className="h-4 w-4 animate-spin" />Preparing report…</p> : null}
      {preview ? <textarea aria-label="Diagnostics report preview" readOnly value={preview.text}
        className="min-h-64 h-[45vh] w-full resize-none rounded-md border bg-background p-3 font-mono text-xs text-foreground focus-visible:outline focus-visible:outline-2" /> : null}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      {saved ? <p role="status" className="text-sm">Report saved. You can attach it to a support request.</p> : null}
      <div className="flex justify-end gap-2">
        <Button variant="outline" disabled={loading || saving} onClick={() => { if (!savingRef.current) setRevision((value) => value + 1); }}><RefreshCw className="h-4 w-4" />Refresh</Button>
        <Button disabled={!preview || loading || saving} onClick={() => void save()}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}Save report
        </Button>
      </div>
    </DialogContent>
  </Dialog>;
}
