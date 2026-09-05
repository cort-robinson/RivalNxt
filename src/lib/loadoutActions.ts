/**
 * Turn every mod off, then put the exact same set back on.
 *
 * Lives outside any component because two places drive it: the global header
 * (the everyday path) and the Backup modal. Two copies of "disable everything"
 * that drifted apart is precisely the kind of bug this feature exists to avoid.
 *
 * A loadout records only which pak files were active per download — no images,
 * no tags, no descriptions — so it stays a few kilobytes and can be captured on
 * every Disable All without the user opting in. Mod artwork is unaffected:
 * images live in the database keyed by mod, while activating only moves .pak
 * files in and out of the game's ~mods folder.
 */
import {
  listDownloads,
  scanActive,
} from "./api";
import { getRememberedLoadout } from "./loadoutState";
import { applyActivation, previewActivation } from "./activationApi";
import {
  AUTO_LOADOUT_ID,
  addLoadout,
  buildLoadout,
  generateBackupName,
  type Loadout,
} from "./backupUtils";

/**
 * Snapshot what is active right now, without persisting it.
 *
 * Persisting is the caller's decision: a capture that found nothing active must
 * never overwrite a good saved loadout, and only the caller knows whether an
 * empty result means "already disabled" or "genuinely nothing installed".
 *
 * Built from the backend download list rather than the UI mod list because
 * active_paks there is reconciled against the real ~mods folder, so it reflects
 * what the game will actually load.
 */
async function captureLoadout(): Promise<Loadout> {
  await scanActive();
  const downloads = await listDownloads();
  return buildLoadout(
    downloads,
    `Before Disable All · ${generateBackupName()}`,
    AUTO_LOADOUT_ID,
  );
}

export interface DisableAllResult {
  loadout: Loadout;
  /** Downloads that were switched off. Zero means nothing was active. */
  disabled: number;
}

/**
 * Record the current loadout, then switch everything off.
 *
 * The capture is persisted only when it is non-empty, so clicking this twice
 * cannot replace a real loadout with an empty one and turn Restore into a
 * silent no-op.
 */
export async function disableAllRemembering(): Promise<DisableAllResult> {
  const loadout = await captureLoadout();
  if (loadout.activeDownloads === 0) {
    return { loadout, disabled: 0 };
  }

  addLoadout(loadout);

  const plan = await previewActivation({});
  await applyActivation(plan);

  return { loadout, disabled: loadout.activeDownloads };
}

export interface RestoreLoadoutResult {
  /** Downloads whose active selection was changed. */
  updated: number;
  /** Downloads in the loadout that are no longer installed. */
  missing: number;
}

/**
 * Re-apply a remembered loadout exactly, including which pak variant was on.
 *
 * Deliberately not "enable everything": a mod can ship several mutually
 * exclusive .pak variants, and turning all of them on is not the state the user
 * had.
 */
export async function restoreLoadout(
  loadout?: Loadout | null,
): Promise<RestoreLoadoutResult> {
  const target = loadout ?? getRememberedLoadout();
  if (!target) throw new Error("No remembered loadout to restore");

  const plan = await previewActivation(target.entries, target.downloadPaths);
  return applyActivation(plan);
}

/**
 * Save the current active selection under a user-chosen name.
 *
 * Uses the same storage as the automatic Disable All slot but with its own id,
 * so a preset is never clobbered by the auto-capture and vice versa. Returns
 * null when nothing is active — an empty preset would silently disable
 * everything on apply, which is never what "save my current setup" means.
 */
export async function savePreset(name: string): Promise<Loadout | null> {
  const trimmed = name.trim();
  if (!trimmed) throw new Error("Preset name cannot be empty");

  await scanActive();
  const downloads = await listDownloads();
  const loadout = buildLoadout(downloads, trimmed, `preset:${trimmed.toLowerCase()}`);
  if (loadout.activeDownloads === 0) return null;

  addLoadout(loadout);
  return loadout;
}


export { getRememberedLoadout, listPresets, deletePreset, findActivePreset } from "./loadoutState";
