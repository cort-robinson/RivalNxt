
/**
 * Normalizes a version string for robust comparison (e.g. "v1.2" vs "1.2")
 */
export function normalizeVersionForCheck(v: string | null | undefined): string {
  if (!v) return "";
  let cleaned = v.replace(/\.\d{9,11}$/, "").toLowerCase();
  if (!cleaned.startsWith("v")) cleaned = "v" + cleaned;
  cleaned = cleaned.replace(/^vs/, "v");
  cleaned = cleaned.replace(/-w\d*$/, "");
  return cleaned;
}



import type { Mod } from "../components/ModCard";

export interface PendingModUpdate {
  local: string;
  latest: string;
  referenceFileId?: number | null;
  pakName?: string;
  variantName?: string;
}

export const updateModKey = (mod: Mod) => `mod:${mod.backendModId}`;

export function updateLibraryFingerprint(mod: Mod): string {
  return JSON.stringify([
    [...new Set(mod.sourceDownloadIds || [])].sort((a, b) => a - b),
    [...new Set(mod.sourcePaths || [])].sort(),
  ]);
}

export function distinctPendingUpdates(pending: PendingModUpdate[]): PendingModUpdate[] {
  const seen = new Set<string>();
  return pending.filter((p) => {
    const key = p.referenceFileId && p.referenceFileId > 0
      ? `file:${p.referenceFileId}`
      : JSON.stringify([p.variantName || p.pakName, p.local, p.latest]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export type UpdateModGroup = Mod & { pendingUpdates: PendingModUpdate[] };

export function groupUpdateMods(mods: Mod[]): UpdateModGroup[] {
  const groups = new Map<number, UpdateModGroup>();
  for (const mod of mods) {
    if (!mod.isInstalled || !mod.backendModId || mod.backendModId <= 0) continue;
    let group = groups.get(mod.backendModId);
    if (!group) {
      group = { ...mod, sourceDownloadIds: [], sourceFileIds: [], sourcePaths: [], pendingUpdates: [] };
      groups.set(mod.backendModId, group);
    }
    group.sourceDownloadIds!.push(...(mod.sourceDownloadIds || []));
    group.sourceFileIds!.push(...(mod.sourceFileIds || []));
    group.sourcePaths!.push(...(mod.sourcePaths || []));
    group.hasUpdate ||= mod.hasUpdate;
    if (mod.pendingUpdates) {
      group.pendingUpdates.push(...mod.pendingUpdates);
    } else if (mod.hasUpdate) group.pendingUpdates.push({
      local: mod.updateVariantLocalVersion || mod.installedVersion || "",
      latest: mod.updateVariantLatestVersion || mod.latestVersion || "",
      referenceFileId: mod.latestFileId,
      variantName: mod.updateVariantName || mod.latestFileName || "",
    });
  }
  return [...groups.values()].map(group => ({ ...group, pendingUpdates: distinctPendingUpdates(group.pendingUpdates) }));
}
