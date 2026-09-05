import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PresetPreviewDialog } from "../PresetPreviewDialog";
import type { ActivationPlan } from "../../lib/activationApi";

const api = vi.hoisted(() => ({
  applyActivation: vi.fn(), previewActivation: vi.fn(), recoverActivation: vi.fn(),
}));
vi.mock("../../lib/activationApi", () => api);

const plan: ActivationPlan = {
  token: "original-preview", entries: { "2": ["new.pak"] }, missing: [], can_apply: true,
  changes: [{ download_id: 1, name: "Old variant", before: ["old.pak"], after: [] },
    { download_id: 2, name: "New variant", before: [], after: ["new.pak"] }],
};

beforeEach(() => { vi.clearAllMocks(); });

describe("selection preview", () => {
  it("shows exact disables and enables before sending the reviewed token", async () => {
    api.applyActivation.mockResolvedValue({ updated: 2, missing: 0 });
    const onApplied = vi.fn();
    render(<PresetPreviewDialog open onOpenChange={vi.fn()} initialPlan={plan} onApplied={onApplied} />);
    expect(screen.getByText("old.pak")).toBeInTheDocument();
    expect(screen.getByText("new.pak")).toBeInTheDocument();
    expect(api.applyActivation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Apply selection" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledOnce());
    expect(api.applyActivation).toHaveBeenCalledWith(plan);
  });

  it("requires a fresh review after a stale-token failure", async () => {
    api.applyActivation.mockRejectedValue(new Error("Library changed; review a fresh preview"));
    api.previewActivation.mockResolvedValue({ ...plan, token: "fresh" });
    render(<PresetPreviewDialog open onOpenChange={vi.fn()} initialPlan={plan} />);
    fireEvent.click(screen.getByRole("button", { name: "Apply selection" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Apply selection" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Refresh preview" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Apply selection" })).toBeEnabled());
  });

  it("blocks missing downloads and offers explicit interrupted recovery", async () => {
    api.recoverActivation.mockResolvedValue({ recovered: 1 });
    api.previewActivation.mockResolvedValue(plan);
    render(<PresetPreviewDialog open onOpenChange={vi.fn()} initialPlan={{ ...plan, can_apply: false,
      recovery_required: true, missing: [{ download_id: 9, name: "Gone mod", reason: "Source download is missing" }] }} />);
    expect(screen.getByText("Gone mod")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply selection" })).toBeDisabled();
    expect(api.recoverActivation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Recover previous selection" }));
    await waitFor(() => expect(api.recoverActivation).toHaveBeenCalledOnce());
  });
});
