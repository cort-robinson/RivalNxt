const fs = require("fs");
const path = require("path");

// Read version from package.json
const packageJson = require("../package.json");
const version = packageJson.version;

console.log(`📦 Syncing version ${version} to all files...`);

// 1. Update Tauri config
const tauriConfigPath = path.join(__dirname, "../src-tauri/tauri.conf.json");
const tauriConfig = JSON.parse(fs.readFileSync(tauriConfigPath, "utf8"));
tauriConfig.version = version;
fs.writeFileSync(tauriConfigPath, JSON.stringify(tauriConfig, null, 2) + "\n");
console.log(`  ✅ tauri.conf.json`);

// Python imports this constant for every Nexus request.
const pythonVersionPath = path.join(__dirname, "../core/version.py");
const pythonVersion = fs.readFileSync(pythonVersionPath, "utf8").replace(
  /APP_VERSION = ["'][^"']+["']/,
  `APP_VERSION = "${version}"`
);
fs.writeFileSync(pythonVersionPath, pythonVersion);
console.log(`Version ${version} synced to Tauri and Python.`);
