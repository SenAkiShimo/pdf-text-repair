# PDF Text Repair

PDF Text Repair 是一个面向 macOS 的本地 PDF 文字层修复工具，可重建可搜索文字层，并生成更适合 Readest 连续朗读的紧凑文字层。

它可以处理：

- 整页为图片、无法选中文字的扫描 PDF；
- 页面显示正常，但复制或朗读出现异常字符的 PDF；
- 同时包含正常文字页和扫描页的混合 PDF；
- 已有但质量较差的 OCR 隐藏层；
- 文字本身正常、只需要重建 Readest 朗读层的 PDF。

所有文档处理都在本机完成，程序不会覆盖原始 PDF。

## 当前状态

v0.2.2 为 macOS 10.15 及以上系统的公开测试版，推荐 Apple Silicon Mac。当前构建尚未进行 Apple 公证和代码签名。

## 主要功能

- Tauri 桌面图形界面；
- 自动抽样分析 PDF，并推荐处理模式；
- 使用 PP-OCRv6 处理扫描图片书；
- 提供 OCRmyPDF 与 Tesseract 兼容模式；
- 小说／对话、散文／论述、忠实保留三种预设；
- 识别并处理前置内容、目录、章节扉页、空白页、页码、脚注、署名、题记出处和图示碎片；
- 合并跨行断词、连续页未完句和同一段台词中的视觉换行；
- 生成 Readest 连续朗读文字层；
- 导出 TXT、OCR JSON 报告和低置信度复核清单；
- 在 GUI 中启动本地组件安装器；
- 支持进度显示、取消、日志和输出文件快捷操作。

## 环境要求

源码构建需要：

- macOS 10.15 或更高版本；
- Node.js 22 或更高版本；
- Rust stable；
- Xcode Command Line Tools。

OCR 处理需要：

- Homebrew；
- OCRmyPDF 与 Tesseract 语言包；
- 独立的 Python 3.13 虚拟环境；
- PyMuPDF；
- PaddleOCR 3.7；
- PaddlePaddle CPU 或 ONNX Runtime；
- PP-OCRv6 模型。

应用可以直接启动仓库内的安装器来补齐缺失组件。

## 启动开发版

```bash
npm install
npm run tauri dev
```

也可以双击：

```text
scripts/dev-macos.command
```

该脚本使用项目自己的 `.npm-cache`，不会依赖用户目录中可能损坏或权限异常的 npm 缓存。

## 构建 `.app`

```bash
npm install
npm run tauri build
```

也可以双击：

```text
scripts/build-macos.command
```

构建结果位于：

```text
src-tauri/target/release/bundle/macos/PDF Text Repair.app
```

## 测试

详见 [TESTING.md](TESTING.md)。公开仓库不包含受版权保护的书籍 PDF，请使用自己拥有或获准处理的文件进行测试。

## 默认输出

```text
原文件名-readest.pdf
原文件名-readest-text.txt
原文件名-readest-ocr-report.json
原文件名-readest-review.txt
```

JSON 和 review 文件只在相应模式开启识别报告时生成。

## 隐私

PDF 渲染、OCR、模型推理、文本整理和文字层生成均在本机进行。程序不会上传文档，也不会覆盖原始 PDF。

## 已知限制

- OCR 结果仍可能出现错字，重要文档需要人工复核；
- 特殊双栏、竖排、图文混排或极低清晰度页面可能需要手动设置；
- 当前版本主要面向 macOS；
- 发布预编译二进制前，需要另外检查第三方许可证、代码签名和 Apple 公证要求。

## 上传到 GitHub

操作步骤见 [GITHUB_UPLOAD.zh-CN.md](GITHUB_UPLOAD.zh-CN.md)。

## 许可证

项目原创代码使用 MIT License。第三方组件和模型文件保留各自许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
