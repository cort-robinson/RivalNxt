import { postJson } from "./api";

export interface ActivationPlan {
  token: string;
  entries: Record<string, string[]>;
  changes: { download_id: number; name: string; before: string[]; after: string[] }[];
  missing: { download_id: number; name: string; reason: string; files?: string[] }[];
  can_apply: boolean;
  recovery_required?: boolean;
  download_paths?: Record<string, string>;
}

export const previewActivation = (entries: Record<string, string[]>, downloadPaths?: Record<string, string>) =>
  postJson<{ entries: Record<string, string[]>; download_paths?: Record<string, string> }, ActivationPlan>("/api/activation/preview", { entries, download_paths: downloadPaths });

export const applyActivation = (plan: ActivationPlan) =>
  postJson<{ entries: Record<string, string[]>; token: string; download_paths?: Record<string, string> }, { updated: number; missing: number }>(
    "/api/activation/apply", { entries: plan.entries, token: plan.token, download_paths: plan.download_paths },
  );

export const previewKeepVariant = (downloadId: number, pak: string) =>
  postJson<{ download_id: number; pak: string }, ActivationPlan>(
    "/api/activation/keep-preview", { download_id: downloadId, pak },
  );

export const recoverActivation = () =>
  postJson<object, { recovered: number }>("/api/activation/recover", {});
