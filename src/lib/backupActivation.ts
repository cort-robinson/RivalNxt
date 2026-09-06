import { listDownloads } from "./api";
import { previewActivation, type ActivationMetadata } from "./activationApi";
import type { ModBackup } from "./backupUtils";

/** Legacy JSON restores affect only mods recorded in that backup. */
export async function previewBackupActivation(backup: ModBackup, installedMods: any[]) {
  const downloads = await listDownloads();
  const entries = Object.fromEntries(downloads.map((download) => [String(download.id), download.active_paks ?? []]));
  const missing: string[] = [];
  const metadata: ActivationMetadata[] = [];
  for (const saved of backup.mods) {
    const mod = installedMods.find((candidate) => {
      if (saved.backendModId != null && candidate.backendModId != null) return saved.backendModId === candidate.backendModId;
      if (saved.sourceDownloadIds?.length && Array.isArray(candidate.sourceDownloadIds)) return saved.sourceDownloadIds.some((id) => candidate.sourceDownloadIds.includes(id));
      return String(saved.modId) === String(candidate.id);
    });
    if (!mod) { missing.push(saved.name); continue; }
    // Resolve IDs against the installed library, never a database-specific saved author ID.
    const effectiveModId = mod.backendModId ?? (mod.sourceDownloadIds?.length ? -Number(mod.sourceDownloadIds[0]) : null);
    const details = {
      ...(typeof saved.description === "string" ? { description: saved.description } : {}),
      ...(saved.customTags?.length ? { custom_tags: saved.customTags } : {}),
      ...(saved.customImages?.length ? { custom_images: saved.customImages } : {}),
      ...(saved.customAuthorName ? { author: {
        name: saved.customAuthorName,
        author_type: saved.customAuthorType || "custom",
        ...(saved.customAuthorAvatar !== undefined ? { avatar: saved.customAuthorAvatar } : {}),
      } } : {}),
    };
    if (Object.keys(details).length) {
      if (effectiveModId == null || !Number.isSafeInteger(effectiveModId) || effectiveModId === 0) {
        missing.push(`${saved.name}: metadata target is missing`);
      } else {
        metadata.push({ mod_id: effectiveModId, ...(mod.modKey ? { mod_key: mod.modKey } : {}), ...details });
      }
    }
    const savedIds = new Set(saved.sourceDownloadIds.map(String));
    const savedPaks = saved.activePaks ?? [];
    const remaining = new Set(savedPaks);
    for (const id of mod.sourceDownloadIds ?? []) {
      const download = downloads.find((item) => Number(item.id) === Number(id));
      if (!download) { missing.push(saved.name); continue; }
      if (!saved.isActive || !savedIds.has(String(id))) { entries[String(id)] = []; continue; }
      const contents = download.contents ?? [];
      if (!savedPaks.length) {
        // Old backups do not identify variants. Only an unambiguous single pak is safe.
        const paks = contents.filter((p) => p.toLowerCase().endsWith(".pak"));
        if (paks.length !== 1) missing.push(`${saved.name}: choose and save a variant first`);
        entries[String(id)] = paks.length === 1 ? paks : [];
      } else {
        const selected = savedPaks.filter((pak) => contents.some((p) => p.replace(/\\/g, "/").toLowerCase() === pak.replace(/\\/g, "/").toLowerCase()));
        // Preserve legacy basename selections for the backend's ambiguity check.
        for (const pak of savedPaks) {
          if (selected.includes(pak) || pak.includes("/") || pak.includes("\\")) continue;
          if (contents.some((p) => p.split(/[\\/]/).pop()?.toLowerCase() === pak.toLowerCase())) selected.push(pak);
        }
        selected.forEach((pak) => remaining.delete(pak));
        entries[String(id)] = selected;
      }
    }
    if (saved.isActive && remaining.size) missing.push(`${saved.name}: saved files are missing`);
    if (saved.isActive && ![...(mod.sourceDownloadIds ?? [])].some((id) => savedIds.has(String(id)))) missing.push(`${saved.name}: saved download is missing`);
  }
  const plan = await previewActivation(entries, undefined, metadata.length ? metadata : undefined);
  if (missing.length) {
    plan.can_apply = false;
    plan.missing.push(...missing.map((name, index) => ({ download_id: -(index + 1), name, reason: "Restore the saved download or create a new backup" })));
  }
  return plan;
}
