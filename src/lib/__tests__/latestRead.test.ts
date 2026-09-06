import { expect, it } from "vitest";
import { readLatest } from "../latestRead";

it("prevents a slow pre-download refresh from replacing completed download state", async () => {
  const latest = { current: null as Promise<string[]> | null };
  let resolveOld!: (value: string[]) => void;
  const old = readLatest(new Promise<string[]>(resolve => { resolveOld = resolve; }), latest);
  const fresh = readLatest(Promise.resolve(["downloaded"]), latest);
  expect(await fresh).toEqual(["downloaded"]);
  resolveOld(["update needed"]);
  expect(await old).toEqual(["downloaded"]);
});

it("does not fall back to stale rows when the newest refresh fails", async () => {
  const latest = { current: null as Promise<string[]> | null };
  let resolveOld!: (value: string[]) => void;
  const old = readLatest(new Promise<string[]>(resolve => { resolveOld = resolve; }), latest);
  const fresh = readLatest(Promise.reject(new Error("offline")), latest);
  await expect(fresh).rejects.toThrow("offline");
  resolveOld(["stale"]);
  await expect(old).rejects.toThrow("offline");
});
