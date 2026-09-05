import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ActivityDialog } from "../../components/ActivityDialog";
import { HealthReviewDialog } from "../../components/HealthReviewDialog";
import { clearActivity, listActivity, listNxmHandoffs, cancelNxmHandoff, getGameVersionCheck, scanCompatibility } from "../api";
import { clearOperations, listOperations } from "../activityApi";
import { openInBrowser } from "../tauri-utils";

vi.mock("../api", () => ({ clearActivity: vi.fn(), listActivity: vi.fn(), listNxmHandoffs: vi.fn(), cancelNxmHandoff: vi.fn(), getGameVersionCheck: vi.fn(), scanCompatibility: vi.fn() }));
vi.mock("../activityApi", () => ({ clearOperations: vi.fn(), listOperations: vi.fn() }));
vi.mock("../tauri-utils", () => ({ openInBrowser: vi.fn() }));
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listActivity).mockResolvedValue([]);
  vi.mocked(listNxmHandoffs).mockResolvedValue([]);
  vi.mocked(listOperations).mockResolvedValue([]);
});

it("retains failed operations and exposes only supported download cancellation", async () => {
  vi.mocked(listOperations).mockResolvedValue([{ id: "job", at: "2026-09-01", updated_at: "2026-09-01", kind: "backup", summary: "Create backup", status: "interrupted", detail: null }]);
  vi.mocked(listNxmHandoffs).mockResolvedValue([{ id: "live", progress: { stage: "downloading", percent: 20 } }, { id: "extract", progress: { stage: "extracting" } }]);
  render(<ActivityDialog open onOpenChange={vi.fn()} />);
  await screen.findByText("Create backup");
  expect(screen.getByText(/app closed before a result/)).toBeVisible();
  expect(screen.getAllByRole("button", { name: "Cancel download" })).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Cancel download" }));
  await waitFor(() => expect(cancelNxmHandoff).toHaveBeenCalledWith("live"));
});

it("shows unavailable data as an error rather than silently clearing history", async () => {
  vi.mocked(listOperations).mockRejectedValue(new Error("offline"));
  render(<ActivityDialog open onOpenChange={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Some activity could not refresh");
});

it("clears finished history through both persistent stores", async () => {
  vi.mocked(listActivity).mockResolvedValue([{ id: 1, at: "2026-09-01", kind: "backup", summary: "Backup created", detail: null }]);
  render(<ActivityDialog open onOpenChange={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Clear finished history" }));
  await waitFor(() => expect(clearActivity).toHaveBeenCalledOnce());
  expect(clearOperations).toHaveBeenCalledOnce();
});

it("opens a fresh Nexus Files page for failed downloads instead of replaying expired handoff secrets", async () => {
  vi.mocked(listNxmHandoffs).mockResolvedValue([{ id: "failed", request: { mod_id: 42, raw: "nxm://secret" }, progress: { stage: "failed" } }]);
  render(<ActivityDialog open onOpenChange={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Open Nexus to retry" }));
  await waitFor(() => expect(openInBrowser).toHaveBeenCalledWith("https://www.nexusmods.com/marvelrivals/mods/42?tab=files"));
  expect(screen.queryByRole("button", { name: "Cancel download" })).not.toBeInTheDocument();
});

it("identifies missing companions without claiming game compatibility or applying repairs", async () => {
  vi.mocked(getGameVersionCheck).mockResolvedValue({ ok: true, file_count: 12, latest_modified: "2026-09-01", latest_file: "Game.pak" });
  vi.mocked(scanCompatibility).mockResolvedValue({ results: [{ path: "Hero.pak", archive: "blocked", game_compatibility: "unknown", error: "An IoStore companion is missing" }], backups: [] });
  const settings = vi.fn();
  const packages = vi.fn();
  const backups = vi.fn();
  render(<HealthReviewDialog open onOpenChange={vi.fn()} onOpenSettings={settings} onOpenPackages={packages} onOpenBackups={backups} />);
  await screen.findByText(/1 have missing companion files/);
  expect(screen.getByText("In-game compatibility: unknown")).toBeVisible();
  expect(screen.getByText(/Index repair cannot replace/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Game path settings" }));
  expect(settings).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Open package repair" }));
  expect(packages).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Open backup manager" }));
  expect(backups).toHaveBeenCalledOnce();
});

it("keeps independent game results when package scan fails", async () => {
  vi.mocked(getGameVersionCheck).mockResolvedValue({ ok: true, file_count: 12, latest_modified: null, latest_file: null });
  vi.mocked(scanCompatibility).mockRejectedValue(new Error("worker missing"));
  render(<HealthReviewDialog open onOpenChange={vi.fn()} onOpenSettings={vi.fn()} onOpenPackages={vi.fn()} onOpenBackups={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Installed packages could not be checked");
  expect(screen.getByText(/12 files found/)).toBeVisible();
  expect(screen.getByText("In-game compatibility: unknown")).toBeVisible();
});
