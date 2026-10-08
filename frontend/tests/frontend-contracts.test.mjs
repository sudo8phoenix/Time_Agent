import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");

assert.match(source, /VITE_FIXTURE_MODE === "true"/);
assert.match(source, /api<void>\("\/auth\/logout", \{ method: "POST" \}\)/);
assert.match(source, /job\.proposalIds\[reviewIndex\]/);
assert.match(source, /resolve_warnings/);
assert.match(source, /\/jobs\/" \+ job\.id \+ "\/retry/);
assert.match(source, /body\.append\("upload", file\)/);
assert.match(source, /\/select-project/);
assert.match(source, /task_overrides: taskOverrides/);
assert.match(source, /Stage canonical CSV/);
assert.match(source, /Create your first project/);
assert.match(source, /Schedule version \$\{result\.version\} is \$\{result\.state\}/);
assert.match(source, /Activate CSV version \{csvVersion\}/);

console.log("frontend contract wiring assertions passed");
