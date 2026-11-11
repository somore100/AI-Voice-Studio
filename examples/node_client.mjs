// Audiovane Local API from Node 18+ / a browser-style fetch. No packages needed.
//   AVS_API_KEY=your-key node examples/node_client.mjs
import { writeFile, readFile } from "node:fs/promises";

const BASE = process.env.AVS_API_URL ?? "http://127.0.0.1:8765/v1";
const headers = process.env.AVS_API_KEY ? { Authorization: `Bearer ${process.env.AVS_API_KEY}` } : {};

async function call(path, init = {}) {
  const res = await fetch(BASE + path, { ...init, headers: { ...headers, ...init.headers } });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error?.message ?? `HTTP ${res.status}`);   // the API answers {error:{message}}
  }
  return res;
}

const models = await (await call("/models")).json();
console.log(models.data.map((m) => `${m.id} (${m.capabilities})`).join(", "));

const wav = Buffer.from(await (await call("/audio/speech", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ model: "kokoro", voice: "kokoro:af_heart", input: "Hello from Node.",
                         speed: 0.95, pitch: 0, depth: 1, response_format: "wav" }),
})).arrayBuffer());
await writeFile("node.wav", wav);

const form = new FormData();                       // speech -> text with word times
form.set("file", new Blob([await readFile("node.wav")], { type: "audio/wav" }), "node.wav");
form.set("model", "whisper-1");
form.set("response_format", "verbose_json");
form.append("timestamp_granularities[]", "word");
const t = await (await call("/audio/transcriptions", { method: "POST", body: form })).json();
console.log(t.text);
for (const w of t.words) console.log(`${w.start.toFixed(2)}-${w.end.toFixed(2)}  ${w.word}`);
