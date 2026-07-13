import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const dist = path.join(root, "dist");
const include = ["index.html", "styles.css", "assets", "projects", "README.md"];
const forbiddenNames = [/\.zip$/i, /^\.env$/i, /^node_modules$/i, /^\.git$/i, /^dist$/i];
const secretPatterns = [
  /sk-[A-Za-z0-9_-]{16,}/,
  /rk_[A-Za-z0-9_-]{16,}/,
  /AKIA[0-9A-Z]{16}/,
  /-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----/
];

function ensureCleanTarget() {
  fs.rmSync(dist, { recursive: true, force: true });
  fs.mkdirSync(dist, { recursive: true });
}

function shouldSkip(name) {
  return forbiddenNames.some((rule) => rule.test(name));
}

function copyRecursive(source, target) {
  const stat = fs.statSync(source);
  const name = path.basename(source);
  if (shouldSkip(name)) return;

  if (stat.isDirectory()) {
    fs.mkdirSync(target, { recursive: true });
    for (const child of fs.readdirSync(source)) {
      copyRecursive(path.join(source, child), path.join(target, child));
    }
    return;
  }

  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
}

function scanForSensitiveContent(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const filePath = path.join(dir, entry.name);
    if (shouldSkip(entry.name)) continue;
    if (entry.isDirectory()) {
      scanForSensitiveContent(filePath);
      continue;
    }

    if (entry.name.endsWith(".zip")) {
      throw new Error(`Refusing to publish archive: ${path.relative(root, filePath)}`);
    }

    const stat = fs.statSync(filePath);
    if (stat.size > 2_500_000) continue;
    const text = fs.readFileSync(filePath, "utf8");
    for (const pattern of secretPatterns) {
      if (pattern.test(text)) {
        throw new Error(`Potential secret found in ${path.relative(root, filePath)}`);
      }
    }
  }
}

ensureCleanTarget();
scanForSensitiveContent(root);

for (const item of include) {
  const source = path.join(root, item);
  if (!fs.existsSync(source)) {
    throw new Error(`Missing required publish item: ${item}`);
  }
  copyRecursive(source, path.join(dist, item));
}

fs.writeFileSync(path.join(dist, ".nojekyll"), "");

console.log("Built GitHub Pages artifact in dist/");
