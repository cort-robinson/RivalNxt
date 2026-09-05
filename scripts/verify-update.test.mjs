import { test } from "node:test";
import assert from "node:assert/strict";
import { verifyUpdate } from "./verify-update.mjs";

// Synthetic data signed by the Tauri CLI; no private key is included.
const data = Buffer.from("53796e746865746963207570646174657220696e7465677269747920746573740d0a", "hex");
const signature = "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZSBmcm9tIHRhdXJpIHNlY3JldCBrZXkKUlVUdlE5ZUU1ZklMT09ueU5NM1l3ZEdGdG1EeFpnT2xIKzNoVlNQaG1ZSkwwZ1hVaUVpWlQ3dHdIbC9vZkVFRzNEblMxRXhEMlY1T01BY1FUcVN0dGJ1RFhMVDlxUDNzZ1FjPQp0cnVzdGVkIGNvbW1lbnQ6IHRpbWVzdGFtcDoxNzg4NjUxNzgxCWZpbGU6dXBkYXRlci1zaWduYXR1cmUtZml4dHVyZS50eHQKS3oxbDRpVURIVXZQakV3QkxSalNLRVhrbXF3SmZpY1FxM2VGaVErd2Ric2Jhcyt5VThEY0czaGFKNDB3dHFuLzVEUzhuUFZtRHVjK1ZmbEdXbG4wQXc9PQo=";
const publicKey = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IDM4MEJGMkU1ODRENzQzRUYKUldUdlE5ZUU1ZklMT0k5cGhkZ1Z2TmRXR1lETzh0d3Y1WTZySHB0QStSTTV0MmJZaHZpMWlvSkgK";
test("accepts a native Tauri signature", () => verifyUpdate(data, signature, publicKey));
test("rejects altered installer bytes", () => {
  assert.throws(() => verifyUpdate(Buffer.concat([data, Buffer.from("tampered")]), signature, publicKey), /verification failed/);
});
test("rejects changed trusted comments", () => {
  const altered = Buffer.from(Buffer.from(signature, "base64").toString().replace("timestamp:", "timestamp:1")).toString("base64");
  assert.throws(() => verifyUpdate(data, altered, publicKey), /verification failed/);
});
test("rejects missing signatures", () => assert.throws(() => verifyUpdate(data, "", publicKey), /format/));
