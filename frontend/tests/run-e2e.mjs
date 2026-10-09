import { mkdtempSync, mkdirSync, readFileSync, readdirSync, writeFileSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cli = join(root, "node_modules/playwright/cli.js");
const args = process.argv.slice(2);
let temporary;
try {
  let command = [cli, "test", ...args];
  const environment = { ...process.env };
  // Playwright 1.52's ESM loader hangs under Node 26. Keep the source tests
  // intact and run temporary CommonJS copies only on affected runtimes.
  if (Number(process.versions.node.split(".")[0]) >= 26) {
    temporary = mkdtempSync(join(root, ".playwright-compat-"));
    const tests = join(temporary, "tests");
    mkdirSync(tests);
    const compile = (source, fileName) => ts.transpileModule(source, { fileName, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021, inlineSourceMap: true, inlineSources: true } }).outputText;
    for (const name of readdirSync(join(root, "tests/e2e"))) {
      if (!name.endsWith(".ts")) continue;
      const source = join(root, "tests/e2e", name);
      writeFileSync(join(tests, name.replace(/\.ts$/, ".cjs")), compile(readFileSync(source, "utf8"), source));
    }
    const configSource = readFileSync(join(root, "playwright.config.ts"), "utf8")
      .replace('testDir: "./tests/e2e",', `testDir: ${JSON.stringify(tests)}, outputDir: ${JSON.stringify(join(root, "test-results"))},`)
      .replaceAll(".spec.ts", ".spec.cjs")
      .replaceAll("command:", `cwd: ${JSON.stringify(root)}, command:`);
    const config = join(temporary, "config.cjs");
    writeFileSync(config, compile(configSource, join(root, "playwright.config.ts")));
    command = [cli, "test", "--config", config, ...args];
    environment.PW_DISABLE_TS_ESM = "1";
  }
  const result = spawnSync(process.execPath, command, { cwd: root, env: environment, stdio: "inherit" });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
} finally {
  if (temporary) rmSync(temporary, { recursive: true, force: true });
}
