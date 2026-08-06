# Changelog

## 0.2.2

- Prepared the source tree for a public GitHub repository.
- Removed bundled book excerpts and replaced them with testing guidance.
- Removed internal source comments while preserving executable shebangs.
- Added contributor, security, issue-template, pull-request, and CI files.
- Generalized diagnostic scripts so they do not depend on named books.
- Added public-repository metadata and expanded generated-file exclusions.

## 0.2.1

- Fixed macOS GUI startup failing with `npm EACCES` when `~/.npm` contains root-owned cache files.
- Development and build scripts now use a project-local `.npm-cache` directory and do not require `sudo` or ownership changes to the global npm cache.
- Added automatic fallback from the China npm mirror to the official npm registry.
- Dependency readiness is now checked using the actual Tauri and Vite executables instead of only testing whether `node_modules` exists.
- Updated GUI and package metadata to v0.2.1 beta.

## 0.2.0

- First complete Tauri GUI beta.
- Added PDF analysis and recommended processing modes.
- Integrated PaddleOCR scanning, OCRmyPDF compatibility modes, and Readest speech-layer rebuilding.
- Added novel, prose, and faithful-layout presets.
- Added progress, cancellation, logs, output opening, TXT review, and environment checks.
