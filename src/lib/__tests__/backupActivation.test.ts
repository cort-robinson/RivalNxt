import { beforeEach, expect, it, vi } from "vitest";
import { previewBackupActivation } from "../backupActivation";
import type { ModBackup } from "../backupUtils";

const api = vi.hoisted(() => ({ listDownloads: vi.fn(), previewActivation: vi.fn() }));
vi.mock("../api", () => ({ listDownloads: api.listDownloads }));
vi.mock("../activationApi", () => ({ previewActivation: api.previewActivation }));
beforeEach(() => {
  vi.clearAllMocks();
  api.previewActivation.mockImplementation(async (entries) => ({ entries, token: "reviewed", can_apply: true, missing: [], changes: [] }));
});
const backup = (activePaks?: string[]) => ({ mods: [{ modId: "mod", backendModId: 10, name: "Saved mod", isActive: true, sourceDownloadIds: [1], activePaks }] }) as ModBackup;
const mods = [{ id: "mod", backendModId: 10, sourceDownloadIds: [1], isActive: true }];

it("previews saved variants even when the mod is already enabled and preserves unrecorded mods", async () => {
  api.listDownloads.mockResolvedValue([{ id: 1, active_paks: ["old.pak"], contents: ["old.pak", "new.pak"] }, { id: 2, active_paks: ["unrelated.pak"], contents: ["unrelated.pak"] }]);
  const plan = await previewBackupActivation(backup(["new.pak"]), mods);
  expect(plan.entries).toEqual({ "1": ["new.pak"], "2": ["unrelated.pak"] });
});

it("blocks ambiguous legacy variants and missing saved files", async () => {
  api.listDownloads.mockResolvedValue([{ id: 1, active_paks: [], contents: ["a.pak", "b.pak"] }]);
  expect((await previewBackupActivation(backup(), mods)).can_apply).toBe(false);
  expect((await previewBackupActivation(backup(["gone.pak"]), mods)).can_apply).toBe(false);
});
