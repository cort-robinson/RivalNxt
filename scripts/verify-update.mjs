// Verify Tauri's base64-encoded minisign format using Node's Ed25519 primitive.
// Format reference: minisign-verify (also used by tauri-plugin-updater).
import { readFileSync } from "node:fs";
import { createHash, createPublicKey, verify } from "node:crypto";
import { pathToFileURL } from "node:url";

export function verifyUpdate(bytes, encodedSignature, encodedPublicKey) {
  const publicLines = Buffer.from(encodedPublicKey.trim(), "base64").toString("utf8").trim().split(/\r?\n/);
  const signatureLines = Buffer.from(encodedSignature.trim(), "base64").toString("utf8").trim().split(/\r?\n/);
  const key = Buffer.from(publicLines[1] ?? "", "base64");
  const signature = Buffer.from(signatureLines[1] ?? "", "base64");
  const globalSignature = Buffer.from(signatureLines[3] ?? "", "base64");
  if (key.length !== 42 || signature.length !== 74 || globalSignature.length !== 64 ||
      key.subarray(0, 2).toString() !== "Ed" || signature.subarray(0, 2).toString() !== "ED" ||
      !signatureLines[2]?.startsWith("trusted comment: ") ||
      !key.subarray(2, 10).equals(signature.subarray(2, 10))) {
    throw new Error("Invalid updater signature format or signing key mismatch");
  }
  const publicKey = createPublicKey({
    key: Buffer.concat([Buffer.from("302a300506032b6570032100", "hex"), key.subarray(10)]),
    format: "der", type: "spki",
  });
  const detached = signature.subarray(10);
  const digest = createHash("blake2b512").update(bytes).digest();
  const trusted = Buffer.concat([detached, Buffer.from(signatureLines[2].slice(17))]);
  if (!verify(null, digest, publicKey, detached) || !verify(null, trusted, publicKey, globalSignature)) {
    throw new Error("Updater signature verification failed");
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const installer = process.argv[2];
  if (!installer) throw new Error("Usage: node scripts/verify-update.mjs <installer>");
  const config = JSON.parse(readFileSync(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"));
  verifyUpdate(readFileSync(installer), readFileSync(`${installer}.sig`, "utf8"), config.plugins.updater.pubkey);
  console.log("Installer updater signature verified against the application's public key.");
}
