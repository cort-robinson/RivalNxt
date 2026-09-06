import { readFileSync } from "node:fs";

// Fail before the expensive native build if npm and Cargo resolve different
// Tauri minor releases. This is the same compatibility boundary as Tauri CLI.
const lock = readFileSync(new URL("../src-tauri/Cargo.lock", import.meta.url), "utf8");
for (const [crate, npm] of [["tauri", "@tauri-apps/api"], ["tauri-plugin-updater", "@tauri-apps/plugin-updater"]]) {
  const pattern = new RegExp(`name = "${crate}"\\r?\\nversion = "([^"]+)"`);
  const rust = lock.match(pattern)?.[1];
  const javascript = JSON.parse(readFileSync(new URL(`../node_modules/${npm}/package.json`, import.meta.url), "utf8")).version;
  if (!rust || rust.split(".").slice(0, 2).join(".") !== javascript.split(".").slice(0, 2).join(".")) {
    throw new Error(`Tauri version mismatch: ${crate} ${rust} / ${npm} ${javascript}`);
  }
  console.log(`${crate} ${rust} matches ${npm} ${javascript}`);
}
