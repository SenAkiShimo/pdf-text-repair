# Testing

## Static checks

```bash
python3 -m py_compile src-tauri/resources/*.py
python3 src-tauri/resources/paddle_scan_pipeline.py --self-test
zsh -n scripts/*.command src-tauri/resources/*.command
npm install
npm run build
cargo check --manifest-path src-tauri/Cargo.toml
```

The Python self-test requires PyMuPDF. The final two checks require Node.js and Rust.

## GUI smoke test

1. Run `scripts/dev-macos.command`.
2. Confirm that the environment badge reports installed local components.
3. Select a PDF and confirm that page count, sampled pages, text/image counts, recommendation, and confidence appear.
4. Switch through all processing modes and presets.
5. Confirm that incompatible settings are disabled automatically.
6. Confirm that output names never overwrite the input.
7. Start and cancel a short task, then run it again.
8. Confirm that PDF, TXT, review, and Finder actions work after completion.

## Document coverage

Use documents you own or have permission to process.

### Image-only scanned book

Expected:

- scanned-book mode is recommended;
- PP-OCRv6 is used;
- page numbers and configured marginal content are omitted from speech;
- the visible page image remains unchanged;
- the output PDF is searchable and readable in Readest.

### Broken Unicode mapping

Expected:

- force-rebuild mode is recommended;
- the old text layer is discarded;
- copied text no longer contains unrelated symbols;
- Readest reads the rebuilt layer continuously.

### Novel layout

Use pages containing a contents page, a sparse chapter title, a blank page, dialogue, prose, and footnotes.

Expected:

- contents and blank pages can be omitted from speech;
- chapter titles remain available;
- bottom footnotes are omitted when the option is enabled;
- visual wraps within one speaker turn are joined;
- different speakers remain separate;
- duplicated OCR punctuation is normalized.

### Existing searchable PDF

Expected:

- Readest-layer-only mode is recommended;
- no OCR model is invoked;
- visible content remains unchanged.
