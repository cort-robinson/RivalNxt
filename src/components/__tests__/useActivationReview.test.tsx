import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useActivationReview } from "../useActivationReview";
import type { ActivationPlan } from "../../lib/activationApi";

const api = vi.hoisted(() => ({ applyActivation: vi.fn(async () => ({ updated: 0, missing: 0 })) }));
vi.mock("../../lib/activationApi", () => api);

it("waits for the complete file and metadata restore before reporting success", async () => {
  const completed = vi.fn();
  const plan: ActivationPlan = { token: "reviewed", entries: {}, metadata: [{ mod_id: 10, description: "Saved description" }], can_apply: true, missing: [], changes: [] };
  function Restore() {
    const { requestReview, dialog } = useActivationReview();
    return <><button onClick={() => void requestReview(plan, async () => plan).then(completed)}>Restore backup</button>{dialog}</>;
  }
  render(<Restore />);
  fireEvent.click(screen.getByRole("button", { name: "Restore backup" }));
  await screen.findByText("Review backup restore");
  expect(completed).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Apply selection" }));
  await waitFor(() => expect(completed).toHaveBeenCalledOnce());
  expect(api.applyActivation).toHaveBeenCalledWith(plan);
});

it("does not report success when the atomic restore fails", async () => {
  api.applyActivation.mockRejectedValueOnce(new Error("Saved image is invalid; previous state restored."));
  const completed = vi.fn();
  const plan: ActivationPlan = { token: "reviewed", entries: {}, metadata: [{ mod_id: 10, description: "saved" }], can_apply: true, missing: [], changes: [] };
  function Restore() {
    const { requestReview, dialog } = useActivationReview();
    return <><button onClick={() => void requestReview(plan, async () => plan).then(completed).catch(() => {})}>Restore backup</button>{dialog}</>;
  }
  render(<Restore />);
  fireEvent.click(screen.getByRole("button", { name: "Restore backup" }));
  await screen.findByText("Review backup restore");
  fireEvent.click(screen.getByRole("button", { name: "Apply selection" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("previous state restored");
  expect(completed).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Apply selection" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByText("Review backup restore")).not.toBeInTheDocument());
  expect(completed).not.toHaveBeenCalled();
});
