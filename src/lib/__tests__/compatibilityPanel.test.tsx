import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CompatibilityPanel } from "../../components/CompatibilityPanel";
import { scanCompatibility, repairCompatibility, restoreCompatibility } from "../api";

vi.mock("../api", () => ({
  scanCompatibility: vi.fn(), repairCompatibility: vi.fn(), restoreCompatibility: vi.fn(),
}));

beforeEach(() => vi.resetAllMocks());

it("keeps game status unknown after successful index repair and offers restore", async () => {
  vi.mocked(scanCompatibility).mockResolvedValue({ results: [{ path: "audio.pak", archive: "repair_needed", game_compatibility: "unknown", content_notes: ["audio"] }], backups: [] });
  vi.mocked(repairCompatibility).mockResolvedValue({ results: [{ path: "audio.pak", archive: "repaired", game_compatibility: "unknown" }], backups: [{ id: "saved", state: "complete", files: 1 }] });
  vi.mocked(restoreCompatibility).mockResolvedValue({ state: "restored" });
  render(<CompatibilityPanel />);
  fireEvent.click(screen.getByText("Patch compatibility"));
  expect(screen.getByRole("button", { name: "Repair old indexes" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Scan installed mods" }));
  await screen.findByText("Index repair needed");
  fireEvent.click(screen.getByRole("button", { name: "Repair old indexes" }));
  await screen.findByText("Index repaired and checked");
  expect(screen.getByText(/packages checked. In-game compatibility: unknown/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("Restore saved files"));
  fireEvent.click(screen.getByRole("button", { name: "Restore backup saved" }));
  await waitFor(() => expect(restoreCompatibility).toHaveBeenCalledWith("saved"));
});

it("shows scan failures and permits retry", async () => {
  vi.mocked(scanCompatibility).mockRejectedValue(new Error("Cannot read mod folder"));
  render(<CompatibilityPanel />);
  fireEvent.click(screen.getByText("Patch compatibility"));
  fireEvent.click(screen.getByRole("button", { name: "Scan installed mods" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Cannot read mod folder");
  expect(screen.getByRole("button", { name: "Scan installed mods" })).toBeEnabled();
});
