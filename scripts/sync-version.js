const fs = require("fs");
const path = require("path");

// Read version from package.json
const packageJson = require("../package.json");
const version = packageJson.version;

console.log(`📦 Syncing version ${version} to all files...`);

// 1. Update Tauri config
const tauriConfigPath = path.join(__dirname, "../src-tauri/tauri.conf.json");
const tauriConfig = fs.readFileSync(tauriConfigPath, "utf8").replace(
  /("version"\s*:\s*)"[^"]+"/, `$1"${version}"`
);
fs.writeFileSync(tauriConfigPath, tauriConfig);
console.log(`  ✅ tauri.conf.json`);

// Python imports this constant for every Nexus request.
const pythonVersionPath = path.join(__dirname, "../core/version.py");
const pythonVersion = fs.readFileSync(pythonVersionPath, "utf8").replace(
  /APP_VERSION = ["'][^"']+["']/,
  `APP_VERSION = "${version}"`
);
fs.writeFileSync(pythonVersionPath, pythonVersion);
console.log(`Version ${version} synced to Tauri and Python.`);

// Windows executable metadata comes from the Rust package version.
const cargoPath = path.join(__dirname, "../src-tauri/Cargo.toml");
const cargo = fs.readFileSync(cargoPath, "utf8").replace(
  /^(version\s*=\s*)"[^"]+"/m,
  `$1"${version}"`
);
fs.writeFileSync(cargoPath, cargo);
const lockPath = path.join(__dirname, "../src-tauri/Cargo.lock");
const lock = fs.readFileSync(lockPath, "utf8").replace(
  /(name = "rivalnxt"\r?\nversion = )"[^"]+"/,
  `$1"${version}"`
);
fs.writeFileSync(lockPath, lock);
