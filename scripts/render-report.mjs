import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const root = process.cwd();
const docsDir = path.join(root, "docs");
const sourcePath = path.join(docsDir, "1.md");
const buildDir = path.join(docsDir, "build");
const texPath = path.join(buildDir, "1.tex");
const pdfPath = path.join(docsDir, "1.pdf");

function escapeLatex(text) {
  return text
    .replace(/\\/g, "\\textbackslash{}")
    .replace(/&/g, "\\&")
    .replace(/%/g, "\\%")
    .replace(/#/g, "\\#")
    .replace(/_/g, "\\_")
    .replace(/\{/g, "\\{")
    .replace(/\}/g, "\\}")
    .replace(/\^/g, "\\textasciicircum{}")
    .replace(/~/g, "\\textasciitilde{}");
}

function inlineMarkdown(text) {
  const parts = text.split(/(\$[^$]+\$|`[^`]+`)/g).filter(Boolean);
  return parts
    .map((part) => {
      if (part.startsWith("$") && part.endsWith("$")) return part;
      if (part.startsWith("`") && part.endsWith("`")) {
        return `\\texttt{${escapeLatex(part.slice(1, -1))}}`;
      }
      return escapeLatex(part)
        .replace(/\\textbackslash\{\}/g, "\\textbackslash{}")
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
          return `\\href{${escapeLatex(url)}}{${escapeLatex(label)}}`;
        });
    })
    .join("");
}

function flushParagraph(output, paragraph) {
  if (!paragraph.length) return;
  output.push(`${inlineMarkdown(paragraph.join(" "))}\n`);
  paragraph.length = 0;
}

function convertMarkdown(markdown) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const output = [];
  const paragraph = [];
  let inItemize = false;
  let inDisplayMath = false;
  let inCode = false;
  let codeBuffer = [];

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (line.startsWith("```")) {
      flushParagraph(output, paragraph);
      if (inCode) {
        output.push("\\begin{verbatim}");
        output.push(...codeBuffer);
        output.push("\\end{verbatim}\n");
        codeBuffer = [];
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }

    if (inCode) {
      codeBuffer.push(rawLine);
      continue;
    }

    if (line.trim() === "$$") {
      flushParagraph(output, paragraph);
      if (inItemize) {
        output.push("\\end{itemize}\n");
        inItemize = false;
      }
      output.push(inDisplayMath ? "\\end{equation*}" : "\\begin{equation*}");
      inDisplayMath = !inDisplayMath;
      continue;
    }

    if (inDisplayMath) {
      if (!line.trim()) continue;
      output.push(rawLine);
      continue;
    }

    if (!line.trim()) {
      flushParagraph(output, paragraph);
      if (inItemize) {
        output.push("\\end{itemize}\n");
        inItemize = false;
      }
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      flushParagraph(output, paragraph);
      if (inItemize) {
        output.push("\\end{itemize}\n");
        inItemize = false;
      }
      const command = heading[1].length === 1 ? "section*" : heading[1].length === 2 ? "section" : "subsection";
      output.push(`\\${command}{${inlineMarkdown(heading[2])}}\n`);
      continue;
    }

    const bullet = line.match(/^\s*-\s+(.*)$/);
    if (bullet) {
      flushParagraph(output, paragraph);
      if (!inItemize) {
        output.push("\\begin{itemize}");
        inItemize = true;
      }
      output.push(`\\item ${inlineMarkdown(bullet[1])}`);
      continue;
    }

    paragraph.push(line.trim());
  }

  flushParagraph(output, paragraph);
  if (inItemize) output.push("\\end{itemize}\n");
  return output.join("\n");
}

const markdown = fs.readFileSync(sourcePath, "utf8");
fs.mkdirSync(buildDir, { recursive: true });

const body = convertMarkdown(markdown);
const tex = String.raw`\documentclass[UTF8,zihao=-4]{ctexart}
\usepackage[a4paper,margin=22mm]{geometry}
\usepackage{xcolor}
\usepackage{hyperref}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{enumitem}
\usepackage{fancyhdr}
\definecolor{ink}{HTML}{18221D}
\definecolor{muted}{HTML}{5C6862}
\definecolor{accent}{HTML}{276A55}
\hypersetup{colorlinks=true,linkcolor=accent,urlcolor=accent}
\setlist[itemize]{leftmargin=2em,itemsep=0.25em,topsep=0.3em}
\setlength{\headheight}{15pt}
\pagestyle{fancy}
\fancyhf{}
\lhead{BILLGU\_PROJECT}
\rhead{顾朱政霖 / Bill Gu}
\cfoot{\thepage}
\begin{document}
\color{ink}
${body}
\end{document}
`;

fs.writeFileSync(texPath, tex, "utf8");

for (let i = 0; i < 2; i += 1) {
  const result = spawnSync("xelatex", ["-interaction=nonstopmode", "-halt-on-error", "-output-directory", buildDir, texPath], {
    cwd: root,
    stdio: "inherit"
  });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

fs.copyFileSync(path.join(buildDir, "1.pdf"), pdfPath);
console.log(`Rendered ${path.relative(root, pdfPath)}`);
