# Third-party notices

PDF Text Repair does not bundle OCR engines or model weights in the source archive. The installer creates a private local Python environment and installs third-party packages on the user's machine. Each component remains subject to its own license.

- **PaddleOCR** — Apache-2.0 — https://github.com/PaddlePaddle/PaddleOCR
- **PaddlePaddle** — Apache-2.0 — https://github.com/PaddlePaddle/Paddle
- **ONNX Runtime** — MIT — https://github.com/microsoft/onnxruntime
- **OCRmyPDF** — MPL-2.0 — https://github.com/ocrmypdf/OCRmyPDF
- **Tesseract OCR and language data** — Apache-2.0 — https://github.com/tesseract-ocr/tesseract
- **Tauri** — Apache-2.0 OR MIT — https://github.com/tauri-apps/tauri
- **PyMuPDF / MuPDF** — GNU AGPL v3 or commercial license — https://pymupdf.readthedocs.io/en/latest/about.html

The helper scripts import PyMuPDF from a user-installed private virtual environment. Anyone distributing a combined binary, preinstalled runtime, hosted service, or commercial product must evaluate and comply with the applicable PyMuPDF/MuPDF licensing terms. The MIT license in this repository covers only the original PDF Text Repair code and does not replace third-party licenses.

OCRmyPDF may invoke Ghostscript, qpdf, unpaper, pngquant, jbig2enc, and other package-manager dependencies. Their licenses remain applicable. PaddleOCR model weights may have model-specific notices in addition to the framework license. Review all dependency and model licenses before publishing bundled binaries.
