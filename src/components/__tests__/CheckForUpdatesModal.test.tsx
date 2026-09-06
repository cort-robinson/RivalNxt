import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { CheckForUpdatesModal, type ModStatus } from "../CheckForUpdatesModal";
import type { Mod } from "../ModCard";
import { groupUpdateMods, updateLibraryFingerprint } from "../../lib/updateUtils";

const api = vi.hoisted(() => ({ checkModUpdate: vi.fn() }));
vi.mock("../../lib/api", () => api);
vi.mock("sonner", () => ({ toast: { loading: vi.fn(), dismiss: vi.fn(), error: vi.fn(), info: vi.fn() } }));
const mod = (id: number, extra: Partial<Mod> = {}): Mod => ({
  id: `row-${id}`, backendModId: id, name: `Mod ${id}`, author: "Author", description: "", category: "", tags: [], downloads: 0, rating: 0,
  images: [], version: "1", lastUpdated: "", isInstalled: true, sourceDownloadIds: [id], sourceFileIds: [id], ...extra,
});
function Harness({ mods, revision = 0, update = vi.fn() }: { mods: Mod[]; revision?: number; update?: (id: string, target?: number) => Promise<void> | void }) {
  const [statuses, setStatuses] = useState<Record<string, ModStatus>>({});
  const [checked, setChecked] = useState(false);
  const [checking, setChecking] = useState(false);
  return <CheckForUpdatesModal open onOpenChange={vi.fn()} mods={mods} libraryRevision={revision} onUpdateMod={update} statuses={statuses} onStatusesChange={setStatuses}
    checked={checked} onCheckedChange={setChecked} isCheckingAll={checking} onIsCheckingAllChange={setChecking} />;
}
beforeEach(() => vi.clearAllMocks());

it("checks unique mod listings concurrently with at most three active requests", async () => {
  const pending: Array<() => void> = [];
  api.checkModUpdate.mockImplementation(() => new Promise(resolve => pending.push(() => resolve({ ok: true, needs_update: false, pending: [] }))));
  render(<Harness mods={[mod(1), mod(1, { id: "duplicate" }), mod(2), mod(3), mod(4)]} />);
  fireEvent.click(screen.getByRole("button", { name: "Check All" }));
  expect(api.checkModUpdate.mock.calls.map(call => call[0])).toEqual([1, 2, 3]);
  await act(async () => pending.shift()!());
  expect(api.checkModUpdate.mock.calls.map(call => call[0])).toEqual([1, 2, 3, 4]);
  await act(async () => pending.splice(0).forEach(resolve => resolve()));
  expect(await screen.findByText("All mods are up to date!")).toBeInTheDocument();
});

it("shows one listing and requests each target file only once without claiming completion", async () => {
  const update = vi.fn().mockResolvedValue(undefined);
  render(<Harness update={update} mods={[
    mod(1, { hasUpdate: true, latestFileId: 20, updateVariantName: "Red", installedVersion: "1", latestVersion: "2" }),
    mod(1, { id: "row-other", hasUpdate: true, latestFileId: 20, updateVariantName: "Red companion" }),
    mod(1, { id: "row-blue", hasUpdate: true, latestFileId: 21, updateVariantName: "Blue" }),
  ]} />);
  expect(screen.getAllByText("Mod 1")).toHaveLength(1);
  expect(screen.getByText("Red")).toBeInTheDocument();
  expect(screen.getByText("Blue")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Update All/ }));
  await waitFor(() => expect(update.mock.calls).toEqual([["row-1", 20], ["row-1", 21]]));
  expect(screen.getByText("Mod 1")).toBeInTheDocument();
  expect(screen.queryByText("All mods are up to date!")).not.toBeInTheDocument();
});

it("does not turn failed checks into an all-up-to-date success", async () => {
  api.checkModUpdate.mockRejectedValue(new Error("Nexus rate limit. Try again later."));
  render(<Harness mods={[mod(1)]} />);
  fireEvent.click(screen.getByRole("button", { name: "Check All" }));
  expect(await screen.findByText("Nexus rate limit. Try again later.")).toBeInTheDocument();
  expect(screen.getByText(/1 mod check failed/)).toBeInTheDocument();
  expect(screen.queryByText("All mods are up to date!")).not.toBeInTheDocument();
});

it("discards checks started before a download changed the library", async () => {
  let finish!: (value: unknown) => void;
  api.checkModUpdate.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = render(<Harness mods={[mod(1)]} />);
  fireEvent.click(screen.getByRole("button", { name: "Check All" }));
  view.rerender(<Harness mods={[mod(1, { sourceDownloadIds: [1, 2], sourceFileIds: [1, 20], hasUpdate: false })]} />);
  await act(async () => finish({ ok: true, needs_update: true, pending: [{ reference_file_id: 20 }] }));
  expect(screen.queryByText("Update available")).not.toBeInTheDocument();
  expect(screen.getByText(/Your library changed/)).toBeInTheDocument();
});

it("invalidates finished results when imported files change while keeping fingerprints independent of grouping order", async () => {
  api.checkModUpdate.mockResolvedValue({ ok: true, needs_update: true, pending: [{ reference_file_id: 20, local_file_name: "Red", local_version: "1", reference_version: "2" }] });
  const view = render(<Harness mods={[mod(1)]} />);
  fireEvent.click(screen.getByRole("button", { name: "Check All" }));
  await screen.findByText("Red");
  view.rerender(<Harness mods={[mod(1, { sourceDownloadIds: [1, 2], sourceFileIds: [1, 20], hasUpdate: false })]} />);
  expect(screen.queryByText("Red")).not.toBeInTheDocument();
  const a = mod(1), b = mod(1, { id: "b", sourceDownloadIds: [2] });
  expect(updateLibraryFingerprint(groupUpdateMods([a, b])[0])).toBe(updateLibraryFingerprint(groupUpdateMods([b, a])[0]));
});


it("rejects an in-flight result after same-ID ingestion increments the library revision", async () => {
  let finish!: (value: unknown) => void;
  api.checkModUpdate.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = render(<Harness mods={[mod(1)]} />);
  fireEvent.click(screen.getByRole("button", { name: "Check All" }));
  view.rerender(<Harness mods={[mod(1)]} revision={1} />);
  await act(async () => finish({ ok: true, needs_update: true, pending: [{ reference_file_id: 20 }] }));
  expect(screen.queryByText("Update available")).not.toBeInTheDocument();
});

it("stops queued Nexus checks after a rate-limit error and reports unchecked listings", async () => {
  api.checkModUpdate.mockRejectedValue(new Error("Nexus request limit reached. Try again in 60 seconds."));
  render(<Harness mods={[mod(1), mod(2), mod(3), mod(4), mod(5)]} />);
  fireEvent.click(screen.getByRole("button", { name: "Check All" }));
  await screen.findByText(/5 mod checks failed/);
  expect(api.checkModUpdate).toHaveBeenCalledTimes(3);
  expect(screen.getAllByText(/Not checked: Nexus request limit reached/)).toHaveLength(2);
});


it("keeps every cached variant target under one listing before running Check All", async () => {
  const update = vi.fn().mockResolvedValue(undefined);
  render(<Harness update={update} mods={[mod(1, { hasUpdate: true, latestFileId: 999,
    pendingUpdates: [
      { local: "1", latest: "2", referenceFileId: 20, variantName: "Red" },
      { local: "3", latest: "4", referenceFileId: 21, variantName: "Blue" },
    ],
  })]} />);
  expect(screen.getAllByText("Mod 1")).toHaveLength(1);
  expect(screen.getByText("Red")).toBeInTheDocument();
  expect(screen.getByText("Blue")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Update All/ }));
  await waitFor(() => expect(update.mock.calls).toEqual([["row-1", 20], ["row-1", 21]]));
  expect(api.checkModUpdate).not.toHaveBeenCalled();
});

it("retains confirmed results when only remote reference file IDs change", async () => {
  api.checkModUpdate.mockResolvedValue({ ok: true, needs_update: false, pending: [] });
  const view = render(<Harness mods={[mod(1)]} />);
  fireEvent.click(screen.getByRole("button", { name: "Check All" }));
  await screen.findByText("All mods are up to date!");
  view.rerender(<Harness mods={[mod(1, { sourceFileIds: [20], latestFileId: 20 })]} />);
  expect(screen.getByText("All mods are up to date!")).toBeInTheDocument();
  expect(updateLibraryFingerprint(mod(1))).toBe(updateLibraryFingerprint(mod(1, { sourceFileIds: [20] })));
});
