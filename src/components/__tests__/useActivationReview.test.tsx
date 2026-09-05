import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useActivationReview } from "../useActivationReview";
import type { ActivationPlan } from "../../lib/activationApi";

const api = vi.hoisted(() => ({ applyActivation: vi.fn(async () => ({ updated: 0, missing: 0 })) }));
vi.mock("../../lib/activationApi", () => api);

it("waits for reviewed activation before continuing separate metadata restoration", async () => {
  const metadata = vi.fn();
  const plan: ActivationPlan = { token: "reviewed", entries: {}, can_apply: true, missing: [], changes: [] };
  function Restore() {
    const { requestReview, dialog } = useActivationReview();
    return <><button onClick={() => void requestReview(plan, async () => plan).then(metadata)}>Restore backup</button>{dialog}</>;
  }
  render(<Restore />);
  fireEvent.click(screen.getByRole("button", { name: "Restore backup" }));
  await screen.findByText("Review backup file changes");
  expect(metadata).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Apply selection" }));
  await waitFor(() => expect(metadata).toHaveBeenCalledOnce());
  expect(api.applyActivation).toHaveBeenCalledWith(plan);
});
