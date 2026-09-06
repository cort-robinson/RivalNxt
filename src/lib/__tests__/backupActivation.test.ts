import { beforeEach, expect, it, vi } from "vitest";
import { previewBackupActivation } from "../backupActivation";
import type { ModBackup } from "../backupUtils";

const api = vi.hoisted(() => ({ listDownloads: vi.fn(), previewActivation: vi.fn() }));
vi.mock("../api", () => ({ listDownloads: api.listDownloads }));
vi.mock("../activationApi", () => ({ previewActivation: api.previewActivation }));
beforeEach(() => {
  vi.clearAllMocks();
  api.previewActivation.mockImplementation(async (entries, _paths, metadata) => ({ entries, metadata, token: "reviewed", can_apply: true, missing: [], changes: [] }));
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

it("includes all saved metadata in the reviewed transaction, including an empty description", async () => {
  api.listDownloads.mockResolvedValue([{ id: 1, active_paks: ["new.pak"], contents: ["new.pak"] }]);
  const saved = backup(["new.pak"]);
  Object.assign(saved.mods[0], {
    description: "", customTags: ["favorite"],
    customImages: [{ data: "aW1hZ2U=", filename: "cover.png", mimeType: "image/png" }],
    customAuthorId: 999, customAuthorName: "Saved author", customAuthorType: "custom", customAuthorAvatar: null,
  });
  const plan = await previewBackupActivation(saved, mods);
  expect(plan.metadata).toEqual([{
    mod_id: 10, description: "", custom_tags: ["favorite"],
    custom_images: saved.mods[0].customImages,
    author: { name: "Saved author", author_type: "custom", avatar: null },
  }]);
  expect(plan.changes).toEqual([]);
  expect(plan.can_apply).toBe(true);
});

it("uses the installed local download ID for metadata and leaves absent fields untouched", async () => {
  api.listDownloads.mockResolvedValue([{ id: 1, active_paks: [], contents: ["new.pak"] }]);
  const saved = backup(["new.pak"]);
  saved.mods[0].backendModId = null;
  saved.mods[0].customTags = ["favorite"];
  const plan = await previewBackupActivation(saved, [{ id: "local", modKey: "local:1", sourceDownloadIds: [1] }]);
  expect(plan.metadata).toEqual([{ mod_id: -1, mod_key: "local:1", custom_tags: ["favorite"] }]);
  delete saved.mods[0].customTags;
  expect((await previewBackupActivation(saved, mods)).metadata).toBeUndefined();
});

it("blocks metadata restoration when a matched mod has no safe backend target", async () => {
  api.listDownloads.mockResolvedValue([]);
  const saved = backup();
  Object.assign(saved.mods[0], { backendModId: null, sourceDownloadIds: [], isActive: false, description: "saved" });
  const plan = await previewBackupActivation(saved, [{ id: "mod" }]);
  expect(plan.can_apply).toBe(false);
  expect(plan.metadata).toBeUndefined();
  expect(plan.missing[0].name).toContain("metadata target is missing");
});
