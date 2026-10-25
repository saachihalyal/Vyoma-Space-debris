import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve("src");
const cssFiles = [];
async function collect(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) await collect(target);
    else if (entry.isFile() && entry.name.endsWith(".css")) cssFiles.push(target);
  }
}
await collect(root);
const violations = [];
for (const file of cssFiles) {
  const source = await readFile(file, "utf8");
  for (const match of source.matchAll(/font-size\s*:\s*([\d.]+)(px|rem|em)\b/gi)) {
    const value = Number(match[1]);
    const pixels = match[2].toLowerCase() === "px" ? value : value * 16;
    if (pixels < 12) violations.push(`${path.relative(process.cwd(), file)}:${source.slice(0, match.index).split("\n").length}: ${match[0]}`);
  }
}
if (violations.length) {
  console.error(`UI font-size rule failed (${violations.length} declarations below 12px):\n${violations.join("\n")}`);
  process.exitCode = 1;
} else {
  console.log(`UI font-size rule passed: scanned ${cssFiles.length} CSS files; all declared font sizes are at least 12px.`);
}
