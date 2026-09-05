import { useRef, useState } from "react";
import type { ActivationPlan } from "../lib/activationApi";
import { PresetPreviewDialog } from "./PresetPreviewDialog";

/** Pause a legacy backup restore before its atomic file switch and metadata stage. */
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
    title="Review backup file changes"
    description="Review the file selection first. Saved tags, descriptions and images are restored separately after this step."
    onOpenChange={(open) => {
      if (!open) {
        pending.current?.reject(new Error("Backup restore cancelled before metadata changes."));
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
