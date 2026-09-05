import { getJson, postJson } from "./api";

export type Operation = {
  id: string;
  at: string;
  updated_at: string;
  kind: string;
  summary: string;
  status: "running" | "succeeded" | "failed" | "interrupted" | "cancelled";
  detail: string | null;
};

export async function listOperations(): Promise<Operation[]> {
  return (await getJson<{ operations: Operation[] }>("/api/activity/operations")).operations;
}

export const clearOperations = () => postJson<object, { ok: boolean }>("/api/activity/operations/clear", {});
