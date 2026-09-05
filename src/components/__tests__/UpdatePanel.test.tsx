import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UpdatePanel } from "../UpdatePanel";

const mocks = vi.hoisted(() => ({ check: vi.fn(), isTauri: vi.fn(() => true) }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: mocks.isTauri }));
vi.mock("@tauri-apps/plugin-updater", () => ({ check: mocks.check }));

describe("UpdatePanel", () => {
  beforeEach(() => vi.clearAllMocks());
  it("checks only on request and shows notes before installing", async () => {
    const downloadAndInstall = vi.fn().mockResolvedValue(undefined);
    const beforeInstall = vi.fn().mockResolvedValue(undefined);
    mocks.check.mockResolvedValue({ version: "0.11.0", body: "Safer switching", close: vi.fn(), downloadAndInstall });
    render(<UpdatePanel beforeInstall={beforeInstall} />);
    expect(mocks.check).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Check for updates" }));
    expect(await screen.findByText("Safer switching")).toBeInTheDocument();
    expect(downloadAndInstall).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Install version 0.11.0" }));
    await waitFor(() => expect(downloadAndInstall).toHaveBeenCalledOnce());
    expect(beforeInstall.mock.invocationCallOrder[0]).toBeLessThan(downloadAndInstall.mock.invocationCallOrder[0]);
  });
  it("does not install if the safety backup fails", async () => {
    const downloadAndInstall = vi.fn();
    mocks.check.mockResolvedValue({ version: "0.11.0", close: vi.fn(), downloadAndInstall });
    render(<UpdatePanel beforeInstall={vi.fn().mockRejectedValue(new Error("Backup disk full"))} />);
    fireEvent.click(screen.getByRole("button", { name: "Check for updates" }));
    fireEvent.click(await screen.findByRole("button", { name: "Install version 0.11.0" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Backup disk full");
    expect(downloadAndInstall).not.toHaveBeenCalled();
  });
  it("reports unavailable checks without claiming the app is current", async () => {
    mocks.check.mockRejectedValue(new Error("Network unavailable"));
    render(<UpdatePanel beforeInstall={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Check for updates" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not check for updates");
    expect(screen.queryByText("You’re running the latest version.")).not.toBeInTheDocument();
  });
});
