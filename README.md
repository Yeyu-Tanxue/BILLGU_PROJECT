# BILLGU_PROJECT

顾朱政霖 / Bill Gu / Erik Gu 的公开项目合集。This repository is a cleaned, public-facing archive for selected hardware, AIoT, FPGA, and web product projects.

The GitHub Pages site is built from the files in this repository. It is intentionally source-backed: the homepage links to four project detail pages, and each detail page links to curated code, reports, constraints, photos, and documentation.

## Online Preview

- Repository: <https://github.com/Yeyu-Tanxue/BILLGU_PROJECT>
- Pages URL after deployment: <https://yeyu-tanxue.github.io/BILLGU_PROJECT/>

## Projects

| Project | 中文简介 | English Summary | Folder |
|---|---|---|---|
| BLDC Motor Control | 无刷直流电机闭环控制，包含 PCB、原理图、实验报告和 STM32/Keil 固件。 | STM32-based closed-loop BLDC control archive with PCB, schematic, report, and firmware modules. | `projects/bldc-motor-control/` |
| AIoT Hearing Terminal | 听障双向沟通终端，包含 ESP32-S3-CAM 固件、Python 工具、云端 API 和作品照片。 | AIoT accessibility terminal using ESP32-S3-CAM, MediaPipe, LSTM/CNN, ASR, TTS, and LCD output. | `projects/aiot-hearing-terminal/` |
| FPGA Stopwatch | FPGA 多功能数字秒表，包含 Verilog 源码和 EGo1 约束。 | Vivado / Verilog stopwatch with clock division, debounced keys, countdown, lap review, LEDs, and seven-segment display scanning. | `projects/fpga-stopwatch/` |
| GOODALPHABET / Gu的辞書 | 日语与词汇学习网站项目。原项目属于 `Yeyu-Tanxue/GOODALPHABET`，`erikpsw` 是 fork。 | Web learning product with Next.js, shadcn/ui, FastAPI, Auth0, Stripe, and Vercel deployment structure. | `projects/goodalphabet/` |

## Repository Structure

```text
.
├── index.html                  # GitHub Pages homepage
├── styles.css                  # Static portfolio styling
├── assets/images/              # Public display images
├── projects/                   # Curated real project files and detail pages
├── scripts/build.mjs           # Zero-dependency static build and safety check
├── .github/workflows/pages.yml # GitHub Pages deployment workflow
└── README.md
```

## Build

This project does not require installing frontend dependencies for the portfolio page.

```bash
npm run build
```

The build script creates `dist/` and refuses to publish obvious archives or common secret patterns.

## Public Archive Policy

原始压缩包没有直接提交。本仓库只保留适合公开审阅的精选内容，并排除了：

- `.env` and runtime secrets
- Original `.zip` archives
- Vivado and IDE generated caches
- Large unrelated build outputs
- Temporary logs and local machine state

Some project folders still contain real source files and documentation from the original work, so they should be treated as project archives rather than polished standalone packages.
