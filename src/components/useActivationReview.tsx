import { useRef, useState } from "react";
import type { ActivationPlan } from "../lib/activationApi";
import { PresetPreviewDialog } from "./PresetPreviewDialog";

/** Pause a legacy backup restore before restoring files and metadata together. */
export function useActivationReview() {
  const [plan, setPlan] = useState<ActivationPlan | null>(null);
  const pending = useRef<{ resolve: () => void; reject: (error: Error) => void } | null>(null);
  const refresh = useRef<(() => Promise<ActivationPlan>) | undefined>(undefined);
  const requestReview = (value: ActivationPlan, refreshPreview: () => Promise<ActivationPlan>) => new Promise<void>((resolve, reject) => {
    refresh.current = refreshPreview;
    pending.current = { resolve, reject };
    setPlan(value);
  });
  const dialog = <PresetPreviewDialog open={plan !== null} initialPlan={plan} allowUnchanged
    refreshPreview={refresh.current}
    title="Review backup restore"
    description="Mod files and saved tags, descriptions, images and authors restore together. If recovery cannot verify an interrupted change, it pauses for review."
    onOpenChange={(open) => {
      if (!open) {
        pending.current?.reject(new Error("Backup restore cancelled before changes."));
        pending.current = null;
        setPlan(null);
      }
    }}
    onApplied={() => {
      pending.current?.resolve();
      pending.current = null;
      setPlan(null);
    }} />;
  return { requestReview, dialog };
}
