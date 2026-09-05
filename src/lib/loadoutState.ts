/** Lightweight preset state used at startup; file mutations load on demand. */
import { AUTO_LOADOUT_ID, getLoadout, loadLoadouts, removeLoadout, type Loadout, type LoadoutSourceDownload } from "./backupUtils";

/** The loadout remembered by the last Disable All, if any. */
export function getRememberedLoadout(): Loadout | null {
  const loadout = getLoadout(AUTO_LOADOUT_ID);
  return loadout && loadout.activeDownloads > 0 ? loadout : null;
}

/** Every saved preset, newest first. Excludes the automatic Disable All slot. */
export function listPresets(): Loadout[] {
  return loadLoadouts().filter((l) => l.id.startsWith("preset:"));
}

export function deletePreset(id: string): void {
  removeLoadout(id);
}

/**
 * Which saved preset, if any, matches what is enabled right now.
 *
 * Presets were listed with no indication of which one was in effect, so there
 * was no way to tell what you were running. A preset counts as active only on
 * an exact match: the same downloads AND the same pak selection within each,
 * because "close enough" would claim a preset that is not actually loaded.
 */
export function findActivePreset(
  downloads: LoadoutSourceDownload[],
  presets: Loadout[],
): Loadout | null {
  const live = new Map<string, Set<string>>();
  for (const dl of downloads) {
    const paks = Array.isArray(dl.active_paks) ? dl.active_paks.filter(Boolean) : [];
    if (paks.length > 0) live.set(String(dl.id), new Set(paks));
  }

  for (const preset of presets) {
    const keys = Object.keys(preset.entries);
    if (keys.length !== live.size) continue;

    const same = keys.every((key) => {
      const want = preset.entries[key] ?? [];
      const have = live.get(key);
      return (
        have !== undefined &&
        have.size === want.length &&
        want.every((p) => have.has(p))
      );
    });
    if (same) return preset;
  }
  return null;
}

