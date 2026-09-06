import { postJson } from "./api";

export interface ActivationMetadata {
  mod_id: number;
  mod_key?: string;
  description?: string;
  custom_tags?: string[];
  custom_images?: { data: string; filename?: string; mimeType?: string }[];
  author?: { name: string; author_type?: string; avatar?: string | null };
}

export interface ActivationPlan {
  token: string;
  metadata?: ActivationMetadata[];
  entries: Record<string, string[]>;
  changes: { download_id: number; name: string; before: string[]; after: string[] }[];
  missing: { download_id: number; name: string; reason: string; files?: string[] }[];
  can_apply: boolean;
  recovery_required?: boolean;
  download_paths?: Record<string, string>;
}

export const previewActivation = (entries: Record<string, string[]>, downloadPaths?: Record<string, string>, metadata?: ActivationMetadata[]) =>
  postJson<{ entries: Record<string, string[]>; download_paths?: Record<string, string>; metadata?: ActivationMetadata[] }, ActivationPlan>("/api/activation/preview", { entries, download_paths: downloadPaths, metadata });

export const applyActivation = (plan: ActivationPlan) =>
  postJson<{ entries: Record<string, string[]>; token: string; download_paths?: Record<string, string>; metadata?: ActivationMetadata[] }, { updated: number; missing: number }>(
    "/api/activation/apply", { entries: plan.entries, token: plan.token, download_paths: plan.download_paths, metadata: plan.metadata },
  );

export const previewKeepVariant = (downloadId: number, pak: string) =>
  postJson<{ download_id: number; pak: string }, ActivationPlan>(
    "/api/activation/keep-preview", { download_id: downloadId, pak },
  );

export const recoverActivation = () =>
  postJson<object, { recovered: number }>("/api/activation/recover", {});
