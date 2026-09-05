import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DiagnosticsDialog } from "../../components/DiagnosticsDialog";

const mocks = vi.hoisted(() => ({ getJson: vi.fn(), invoke: vi.fn() }));
vi.mock("../api", () => ({ getJson: mocks.getJson }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));

beforeEach(() => {
  mocks.getJson.mockReset(); mocks.invoke.mockReset();
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true });
});

it("saves only the exact preview after the user requests export", async () => {
  const text = '{"version":"0.10.0","message":"[redacted]"}';
  mocks.getJson.mockResolvedValue({ text, filename: "report.json" });
  mocks.invoke.mockResolvedValueOnce("C:/Example/report.json").mockResolvedValueOnce(undefined);
  render(<DiagnosticsDialog open onOpenChange={() => {}} />);
  await screen.findByDisplayValue(text);
  expect(mocks.invoke).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Save report" }));
  await waitFor(() => expect(mocks.invoke).toHaveBeenCalledWith("save_text_file", {
    path: "C:/Example/report.json", content: text,
  }));
  expect(mocks.getJson).toHaveBeenCalledTimes(1);
});

it("does not write or report an error when file selection is cancelled", async () => {
  mocks.getJson.mockResolvedValue({ text: "{}", filename: "report.json" });
  mocks.invoke.mockRejectedValue("Selection cancelled");
  render(<DiagnosticsDialog open onOpenChange={() => {}} />);
  await screen.findByDisplayValue("{}");
  fireEvent.click(screen.getByRole("button", { name: "Save report" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save report" })).not.toBeDisabled());
  expect(mocks.invoke).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("reports unavailable data and allows a retry without exporting an empty report", async () => {
  mocks.getJson.mockRejectedValueOnce(new Error("unavailable")).mockResolvedValueOnce({ text: "{}", filename: "report.json" });
  render(<DiagnosticsDialog open onOpenChange={() => {}} />);
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "Save report" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByDisplayValue("{}");
  expect(mocks.invoke).not.toHaveBeenCalled();
});
