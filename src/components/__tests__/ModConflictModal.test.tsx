import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ModConflictModal } from "../ModConflictModal";

const api = vi.hoisted(() => ({ previewKeepVariant: vi.fn(), applyActivation: vi.fn() }));
vi.mock("../../lib/activationApi", () => api);
vi.mock("../LazyModModal", () => ({ LazyModModal: () => null }));

beforeEach(() => { vi.clearAllMocks(); });

it("groups detected tags and reviews a download variant without immediately enabling it", async () => {
  api.previewKeepVariant.mockResolvedValue({
    token: "reviewed", entries: { "7": ["preferred.pak"] }, can_apply: true, missing: [],
    changes: [{ download_id: 8, name: "Overlapping mod", before: ["other.pak"], after: [] }],
  });
  render(<ModConflictModal open onOpenChange={vi.fn()} conflicts={[{
    asset_path: "Characters/Luna/body.uasset", participants: [{ pak_name: "preferred.pak", merged_tag: "Luna Snow / Classic",
      mods: [{ mod_id: 500, mod_name: "Preferred mod", pak_file: "preferred.pak", local_download_id: 7 }] }],
  }]} />);
  expect(screen.getByText("Luna Snow / Classic")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Keep this variant" }));
  await waitFor(() => expect(api.previewKeepVariant).toHaveBeenCalledWith(7, "preferred.pak"));
  await screen.findByText("other.pak");
  expect(api.applyActivation).not.toHaveBeenCalled();
});

it("does not offer destructive resolution without an identified local download", () => {
  render(<ModConflictModal open onOpenChange={vi.fn()} conflicts={[{
    asset_path: "unknown", participants: [{ pak_name: "unknown.pak", mods: [{ mod_id: null, mod_name: "Unknown", pak_file: "unknown.pak" }] }],
  }]} />);
  expect(screen.queryByRole("button", { name: "Keep this variant" })).not.toBeInTheDocument();
  expect(screen.getByText("Open mod to identify its download")).toBeInTheDocument();
});
