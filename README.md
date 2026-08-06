# PDF Text Repair

PDF Text Repair is a local macOS utility for rebuilding PDF text layers and generating a compact reading layer for smoother narration in Readest.

It supports:

- image-only scanned PDFs with PP-OCRv6;
- PDFs whose visible glyphs do not match their embedded Unicode text;
- mixed PDFs containing both searchable and scanned pages;
- replacement of low-quality OCR layers;
- rebuilding a Readest-oriented reading layer without rerunning OCR.

All document processing runs locally. Source PDFs are never overwritten.

## Status

Version 0.2.2 is a public beta for macOS 10.15 or later. Apple Silicon is recommended. The application is not notarized or code-signed.

## Features

- Tauri desktop interface;
- automatic PDF sampling and processing-mode recommendation;
- PP-OCRv6 scanned-book pipeline;
- OCRmyPDF and Tesseract compatibility modes;
- novel/dialogue, prose, and faithful-layout presets;
- front-matter, table-of-contents, title-page, blank-page, page-number, footnote, credit-line, citation-line, and diagram-label handling;
- continuous text-layer rebuilding for Readest;
- TXT, JSON, and low-confidence review output;
- local dependency installer;
- cancellation, progress, logs, and output-file actions.

## Requirements

For source builds:

- macOS 10.15 or later;
- Node.js 22 or later;
- Rust stable;
- Xcode Command Line Tools.

For OCR processing:

- Homebrew;
- OCRmyPDF and Tesseract language data;
- Python 3.13 virtual environment;
- PyMuPDF;
- PaddleOCR 3.7;
- PaddlePaddle CPU or ONNX Runtime;
- PP-OCRv6 model files.

The application can launch the included installer for missing OCR components.

## Development

```bash
npm install
npm run tauri dev
```

The macOS helper script uses a project-local npm cache:

```text
scripts/dev-macos.command
```

## Build

```bash
npm install
npm run tauri build
```

Or run:

```text
scripts/build-macos.command
```

The app bundle is written to:

```text
src-tauri/target/release/bundle/macos/PDF Text Repair.app
```

## Testing

See [TESTING.md](TESTING.md). This repository does not include copyrighted book PDFs. Use documents you own or have permission to process.

## Privacy

PDF rendering, OCR, model inference, text cleanup, and text-layer generation are performed locally. The program does not upload documents or overwrite source files.

## Limitations

- OCR output can contain errors and should be reviewed for important documents.
- Layout detection is heuristic and may require manual settings for unusual books.
- The current release is macOS-focused.
- Binary redistribution requires separate review of third-party licensing and signing requirements.

## License

Original project code is licensed under the MIT License. Third-party components and model files retain their own licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)

GitHub upload guide: [GITHUB_UPLOAD.zh-CN.md](GITHUB_UPLOAD.zh-CN.md)
