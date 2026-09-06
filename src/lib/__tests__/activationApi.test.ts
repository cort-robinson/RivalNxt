import { beforeEach, expect, it, vi } from "vitest";
import { applyActivation, previewActivation } from "../activationApi";

const api = vi.hoisted(() => ({ postJson: vi.fn() }));
vi.mock("../api", () => api);
beforeEach(() => vi.clearAllMocks());

it("applies exactly the metadata returned in the token-bound preview", async () => {
  const metadata = [{ mod_id: -3, custom_tags: ["saved"], description: "" }];
  const plan = { entries: { "3": ["variant.pak"] }, token: "bound", metadata, changes: [], missing: [], can_apply: true };
  api.postJson.mockResolvedValueOnce(plan).mockResolvedValueOnce({ updated: 1, missing: 0 });
  await applyActivation(await previewActivation(plan.entries, undefined, metadata));
  expect(api.postJson).toHaveBeenNthCalledWith(1, "/api/activation/preview", {
    entries: plan.entries, download_paths: undefined, metadata,
  });
  expect(api.postJson).toHaveBeenNthCalledWith(2, "/api/activation/apply", {
    entries: plan.entries, token: "bound", download_paths: undefined, metadata,
  });
});
