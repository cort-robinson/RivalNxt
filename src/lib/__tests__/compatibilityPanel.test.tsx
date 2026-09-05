import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CompatibilityPanel } from "../../components/CompatibilityPanel";
import {
  scanCompatibility, repairCompatibility, restoreCompatibility,
  type CompatibilityResult,
} from "../api";

vi.mock("../api", () => ({
  scanCompatibility: vi.fn(), repairCompatibility: vi.fn(), restoreCompatibility: vi.fn(),
}));
beforeEach(() => vi.resetAllMocks());

const row = (path: string, archive: CompatibilityResult["archive"] = "checked"): CompatibilityResult => ({
  path, archive, game_compatibility: "unknown", content_notes: ["IoStore assets not checked"],
});
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));

it("starts with one action and puts the technical explanation on demand", () => {
  render(<CompatibilityPanel />);
  expect(screen.getByRole("button", { name: "Check mods" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: /Repair/ })).not.toBeInTheDocument();
  expect(screen.queryByText(/UTOC/)).not.toBeInTheDocument();
  click("About this check");
  expect(screen.getByText(/A mod can contain several packages/)).toBeVisible();
  expect(screen.getByText(/UTOC and UCAS/)).toBeVisible();
});

it("keeps 235 clean packages out of the default view without claiming game compatibility", async () => {
  vi.mocked(scanCompatibility).mockResolvedValue({ results: Array.from({ length: 235 }, (_, index) => row(`folder/Character ${index}_9999999_P.pak`)), backups: [] });
  render(<CompatibilityPanel />);
  click("Check mods");
  await screen.findByText("No outdated patch files found");
  expect(screen.getByText("235 packages checked.")).toBeVisible();
  expect(screen.getByText("In-game compatibility is untested.")).toBeVisible();
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
  expect(screen.queryByText("IoStore assets not checked")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Repair/ })).not.toBeInTheDocument();
  click("View results");
  expect(screen.getAllByRole("listitem")).toHaveLength(235);
  expect(screen.getByText("Character 0")).toBeVisible();
  expect(screen.getByText("folder/Character 0_9999999_P.pak")).not.toBeVisible();
});

it("shows only packages needing attention and lets the user reveal all results", async () => {
  vi.mocked(scanCompatibility).mockResolvedValue({ results: [row("Clean.pak"), row("Old.pak", "repair_needed"), { ...row("Bad.pak", "blocked"), error: "PAK footer is missing" }], backups: [] });
  render(<CompatibilityPanel />);
  click("Check mods");
  await screen.findByText("1 package needs repair");
  expect(screen.getByRole("button", { name: "Repair 1 package" })).toBeEnabled();
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  expect(screen.queryByText("Clean")).not.toBeInTheDocument();
  click("All packages (3)");
  expect(screen.getAllByRole("listitem")).toHaveLength(3);
  click("About this check");
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});

it("reports repairs, collapses routine results and retains restore access", async () => {
  vi.mocked(scanCompatibility).mockResolvedValue({ results: [row("Audio.pak", "repair_needed")], backups: [] });
  vi.mocked(repairCompatibility).mockResolvedValue({ results: [row("Audio.pak", "repaired")], backups: [{ id: "saved", state: "complete", files: 1 }] });
  vi.mocked(restoreCompatibility).mockResolvedValue({ state: "restored" });
  render(<CompatibilityPanel />);
  click("Check mods");
  await screen.findByText("1 package needs repair");
  click("Repair 1 package");
  await screen.findByText("Repaired 1 package");
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
  expect(screen.getByText("In-game compatibility is untested.")).toBeVisible();
  click("Backups (1)");
  expect(screen.getByText(/Later file changes are protected/)).toBeVisible();
  click("Restore Backup 1");
  await waitFor(() => expect(restoreCompatibility).toHaveBeenCalledWith("saved"));
  await screen.findByText("Backup restored.");
});

it("does not show an all-clear message after a partial repair failure", async () => {
  vi.mocked(scanCompatibility).mockResolvedValue({ results: [row("A.pak", "repair_needed"), row("B.pak", "repair_needed")], backups: [] });
  vi.mocked(repairCompatibility).mockResolvedValue({ results: [row("A.pak", "repaired"), { ...row("B.pak", "failed"), error: "Backup disk is full" }], backups: [] });
  render(<CompatibilityPanel />);
  click("Check mods");
  await screen.findByText("2 packages need repair");
  click("Repair 2 packages");
  await screen.findByText("1 package needs a manual check");
  expect(screen.getByText("Repair failed")).toBeVisible();
  expect(screen.queryByText("No outdated patch files found")).not.toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(1);
});

it("shows an empty scan without repair or result controls", async () => {
  vi.mocked(scanCompatibility).mockResolvedValue({ results: [], backups: [] });
  render(<CompatibilityPanel />);
  click("Check mods");
  await screen.findByText("No installed mod packages found");
  expect(screen.queryByRole("button", { name: "View results" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
});

it("prevents repair from a stale result after a failed recheck", async () => {
  vi.mocked(scanCompatibility).mockResolvedValueOnce({ results: [row("Old.pak", "repair_needed")], backups: [] }).mockRejectedValueOnce(new Error("Cannot read mod folder"));
  render(<CompatibilityPanel />);
  click("Check mods");
  await screen.findByText("1 package needs repair");
  click("Check again");
  expect(await screen.findByRole("alert")).toHaveTextContent("Cannot read mod folder");
  expect(screen.queryByRole("button", { name: /Repair/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
});

it("disables the action while a scan is pending", async () => {
  let finish!: (value: { results: CompatibilityResult[]; backups: [] }) => void;
  vi.mocked(scanCompatibility).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  render(<CompatibilityPanel />);
  click("Check mods");
  expect(screen.getByRole("button", { name: "Please wait…" })).toBeDisabled();
  expect(screen.getByText("Checking installed mods…")).toBeVisible();
  finish({ results: [], backups: [] });
  await screen.findByText("No installed mod packages found");
});

it("keeps a successful restore visible if the following scan fails", async () => {
  vi.mocked(scanCompatibility).mockResolvedValueOnce({ results: [row("A.pak")], backups: [{ id: "saved", state: "prepared", files: 1 }] }).mockRejectedValueOnce(new Error("Scan unavailable"));
  vi.mocked(restoreCompatibility).mockResolvedValue({ state: "restored" });
  render(<CompatibilityPanel />);
  click("Check mods");
  await screen.findByText("No outdated patch files found");
  click("Backups (1)");
  expect(screen.getByText(/Interrupted operation/)).toBeVisible();
  click("Restore Backup 1");
  await screen.findByRole("alert");
  expect(screen.getByText("Backup restored.")).toBeVisible();
  expect(screen.queryByText("No outdated patch files found")).not.toBeInTheDocument();
});
