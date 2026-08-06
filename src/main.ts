import "./styles.css";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { open, save } from "@tauri-apps/plugin-dialog";

type EnvironmentStatus = {
  ready: boolean;
  paddleReady: boolean;
  paddlePython: string | null;
  paddleocrVersion: string | null;
  paddleMessage: string;
  ocrmypdfPath: string | null;
  ocrmypdfVersion: string | null;
  tesseractPath: string | null;
  tesseractLanguages: string[];
  readingOptimizerReady: boolean;
  readingOptimizerPython: string | null;
  readingOptimizerMessage: string;
  message: string;
};

type AnalysisSample = {
  page: number;
  textChars: number;
  cjkChars: number;
  suspiciousRatio: number;
  imageCoverage: number;
};

type DocumentAnalysis = {
  pageCount: number;
  sampledPages: number[];
  sampleCount: number;
  pagesWithText: number;
  pagesWithoutText: number;
  suspiciousTextPages: number;
  imageDominantPages: number;
  recommendedMode: ActualMode;
  confidence: number;
  summary: string;
  samples: AnalysisSample[];
};

type ProgressPayload = { current: number; total: number; percent: number; stage: string };
type FinishPayload = { success: boolean; cancelled: boolean; outputPath: string; textPath: string | null; message: string };
type LogPayload = { message: string };
type UiMode = "auto" | ActualMode;
type ActualMode = "scan" | "force" | "skip" | "redo" | "reading";
type OcrEngine = "paddle" | "tesseract";
type ModelTier = "tiny" | "small" | "medium";
type ReadingProfile = "auto" | "prose" | "novel";
type ContentStartMode = "all" | "auto" | "page";

type OcrRequest = {
  inputPath: string;
  outputPath: string;
  mode: ActualMode;
  ocrEngine: OcrEngine;
  modelTier: ModelTier;
  scoreThreshold: number;
  languages: string[];
  rotatePages: boolean;
  deskew: boolean;
  clean: boolean;
  removeBackground: boolean;
  oversample: number;
  filterMargins: boolean;
  dropDiagramLabels: boolean;
  dropFootnotes: boolean;
  skipToc: boolean;
  dropRunningHeaders: boolean;
  dropCitationLines: boolean;
  dropCreditLines: boolean;
  mergeContinuousPages: boolean;
  readingProfile: ReadingProfile;
  contentStartMode: ContentStartMode;
  contentStartPage: number | null;
  keepTitlePage: boolean;
  optimize: number;
  jobs: number | null;
  readingOptimized: boolean;
  exportText: boolean;
  debugReport: boolean;
};

const $ = <T extends HTMLElement>(selector: string): T => {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing element: ${selector}`);
  return element;
};

const elements = {
  engineBadge: $("#engineBadge"),
  engineBadgeText: $("#engineBadgeText"),
  engineHelp: $("#engineHelp"),
  installButton: $("#installButton") as HTMLButtonElement,
  recheckButton: $("#recheckButton") as HTMLButtonElement,
  inputPath: $("#inputPath") as HTMLInputElement,
  outputPath: $("#outputPath") as HTMLInputElement,
  dropZone: $("#dropZone"),
  dropTitle: $("#dropTitle"),
  dropSubtitle: $("#dropSubtitle"),
  browseButton: $("#browseButton") as HTMLButtonElement,
  saveAsButton: $("#saveAsButton") as HTMLButtonElement,
  analyzeButton: $("#analyzeButton") as HTMLButtonElement,
  analysisEmpty: $("#analysisEmpty"),
  analysisLoading: $("#analysisLoading"),
  analysisResult: $("#analysisResult"),
  analysisError: $("#analysisError"),
  recommendedMode: $("#recommendedMode"),
  analysisSummary: $("#analysisSummary"),
  analysisConfidence: $("#analysisConfidence"),
  metricPages: $("#metricPages"),
  metricSamples: $("#metricSamples"),
  metricText: $("#metricText"),
  metricImage: $("#metricImage"),
  activeModeHint: $("#activeModeHint"),
  presetSelect: $("#presetSelect") as HTMLSelectElement,
  readingProfile: $("#readingProfile") as HTMLSelectElement,
  contentStartMode: $("#contentStartMode") as HTMLSelectElement,
  contentStartPage: $("#contentStartPage") as HTMLInputElement,
  startPageRow: $("#startPageRow"),
  modelTier: $("#modelTier") as HTMLSelectElement,
  oversample: $("#oversample") as HTMLSelectElement,
  scoreThreshold: $("#scoreThreshold") as HTMLInputElement,
  filterMargins: $("#filterMargins") as HTMLInputElement,
  dropFootnotes: $("#dropFootnotes") as HTMLInputElement,
  skipToc: $("#skipToc") as HTMLInputElement,
  dropCitationLines: $("#dropCitationLines") as HTMLInputElement,
  dropCreditLines: $("#dropCreditLines") as HTMLInputElement,
  dropDiagramLabels: $("#dropDiagramLabels") as HTMLInputElement,
  mergeContinuousPages: $("#mergeContinuousPages") as HTMLInputElement,
  keepTitlePage: $("#keepTitlePage") as HTMLInputElement,
  rotatePages: $("#rotatePages") as HTMLInputElement,
  readingOptimized: $("#readingOptimized") as HTMLInputElement,
  exportText: $("#exportText") as HTMLInputElement,
  debugReport: $("#debugReport") as HTMLInputElement,
  deskew: $("#deskew") as HTMLInputElement,
  clean: $("#clean") as HTMLInputElement,
  removeBackground: $("#removeBackground") as HTMLInputElement,
  optimize: $("#optimize") as HTMLSelectElement,
  jobs: $("#jobs") as HTMLInputElement,
  languageWarning: $("#languageWarning"),
  engineWarning: $("#engineWarning"),
  optimizerWarning: $("#optimizerWarning"),
  statusTitle: $("#statusTitle"),
  statusMessage: $("#statusMessage"),
  pageCounter: $("#pageCounter"),
  progressBar: $("#progressBar"),
  runModeSummary: $("#runModeSummary"),
  runOutputSummary: $("#runOutputSummary"),
  startButton: $("#startButton") as HTMLButtonElement,
  cancelButton: $("#cancelButton") as HTMLButtonElement,
  resultActions: $("#resultActions"),
  openResultButton: $("#openResultButton") as HTMLButtonElement,
  openTextButton: $("#openTextButton") as HTMLButtonElement,
  revealButton: $("#revealButton") as HTMLButtonElement,
  clearLogButton: $("#clearLogButton") as HTMLButtonElement,
  logOutput: $("#logOutput")
};

const MODE_LABELS: Record<ActualMode, string> = {
  scan: "扫描图片书 · PP-OCRv6",
  force: "彻底修复乱码文字层",
  skip: "混合型 PDF · 保留正常文字",
  redo: "替换旧 OCR 层",
  reading: "仅整理 Readest 朗读层"
};

let environment: EnvironmentStatus | null = null;
let analysis: DocumentAnalysis | null = null;
let analysisRunning = false;
let running = false;
let lastOutputPath = "";
let lastTextPath = "";
let unlisteners: UnlistenFn[] = [];

function appendLog(message: string): void {
  const text = message.trim();
  if (!text) return;
  const current = elements.logOutput.textContent ?? "";
  elements.logOutput.textContent = `${current}${current.endsWith("\n") ? "" : "\n"}${text}`
    .split("\n").slice(-500).join("\n");
  elements.logOutput.scrollTop = elements.logOutput.scrollHeight;
}

function selectedUiMode(): UiMode {
  return (document.querySelector<HTMLInputElement>('input[name="mode"]:checked')?.value ?? "auto") as UiMode;
}

function actualMode(): ActualMode | null {
  const selected = selectedUiMode();
  if (selected !== "auto") return selected;
  return analysis?.recommendedMode ?? null;
}

function selectedLanguages(): string[] {
  return Array.from(document.querySelectorAll<HTMLInputElement>(".language-grid input:checked")).map((item) => item.value);
}

function outputForInput(inputPath: string): string {
  const separator = inputPath.includes("\\") ? "\\" : "/";
  const parts = inputPath.split(separator);
  const filename = parts.pop() ?? "document.pdf";
  const base = filename.toLowerCase().endsWith(".pdf") ? filename.slice(0, -4) : filename;
  parts.push(`${base}-readest.pdf`);
  return parts.join(separator);
}

function companionTextPath(outputPath: string): string {
  return outputPath.toLowerCase().endsWith(".pdf") ? `${outputPath.slice(0, -4)}-text.txt` : `${outputPath}-text.txt`;
}

function selectMode(mode: UiMode): void {
  const radio = document.querySelector<HTMLInputElement>(`input[name="mode"][value="${mode}"]`);
  if (radio) radio.checked = true;
  updateModeUi();
}

function setAnalysisState(state: "empty" | "loading" | "result" | "error", error = ""): void {
  elements.analysisEmpty.classList.toggle("hidden", state !== "empty");
  elements.analysisLoading.classList.toggle("hidden", state !== "loading");
  elements.analysisResult.classList.toggle("hidden", state !== "result");
  elements.analysisError.classList.toggle("hidden", state !== "error");
  if (state === "error") elements.analysisError.textContent = error;
}

function renderAnalysis(result: DocumentAnalysis): void {
  elements.recommendedMode.textContent = MODE_LABELS[result.recommendedMode as ActualMode];
  elements.analysisSummary.textContent = result.summary;
  elements.analysisConfidence.textContent = `${Math.round(result.confidence * 100)}%`;
  elements.metricPages.textContent = String(result.pageCount);
  elements.metricSamples.textContent = String(result.sampleCount);
  elements.metricText.textContent = `${result.pagesWithText} 页`;
  elements.metricImage.textContent = `${result.pagesWithoutText} 页`;
  setAnalysisState("result");
}

async function analyzeCurrentPdf(): Promise<void> {
  const path = elements.inputPath.value.trim();
  if (!path || analysisRunning || running) return;
  analysisRunning = true;
  analysis = null;
  elements.analyzeButton.disabled = true;
  setAnalysisState("loading");
  elements.statusTitle.textContent = "正在分析";
  elements.statusMessage.textContent = "正在抽样检查页面图像与文字层。";
  elements.progressBar.classList.add("indeterminate");
  appendLog(`分析 PDF：${path}`);
  try {
    const result = await invoke<DocumentAnalysis>("analyze_pdf", { path });
    analysis = result;
    renderAnalysis(result);
    appendLog(`分析完成：${MODE_LABELS[result.recommendedMode as ActualMode]}；置信度 ${Math.round(result.confidence * 100)}%。`);
    elements.statusTitle.textContent = "分析完成";
    elements.statusMessage.textContent = result.summary;
  } catch (error) {
    const message = `自动分析失败：${String(error)}。仍可手动选择处理方式。`;
    setAnalysisState("error", message);
    appendLog(message);
    elements.statusTitle.textContent = "需要手动选择";
    elements.statusMessage.textContent = "自动分析暂不可用，请选择一种明确的处理方式。";
  } finally {
    analysisRunning = false;
    elements.analyzeButton.disabled = false;
    elements.progressBar.classList.remove("indeterminate");
    updateModeUi();
  }
}

function setInputFile(path: string): void {
  elements.inputPath.value = path;
  elements.outputPath.value = outputForInput(path);
  const filename = path.split(/[\\/]/).pop() ?? path;
  elements.dropTitle.textContent = filename;
  elements.dropSubtitle.textContent = "文件已选择；正在判断它属于扫描书、乱码文字层、混合 PDF 还是正常文字 PDF。";
  analysis = null;
  setAnalysisState("empty");
  elements.analyzeButton.disabled = false;
  elements.resultActions.classList.add("hidden");
  lastOutputPath = "";
  lastTextPath = "";
  updateModeUi();
  void analyzeCurrentPdf();
}

async function chooseInput(): Promise<void> {
  const result = await open({ multiple: false, directory: false, filters: [{ name: "PDF", extensions: ["pdf"] }] });
  if (typeof result === "string") setInputFile(result);
}

async function chooseOutput(): Promise<void> {
  const current = elements.outputPath.value.trim() || outputForInput(elements.inputPath.value.trim());
  const result = await save({ defaultPath: current, filters: [{ name: "PDF", extensions: ["pdf"] }] });
  if (typeof result === "string") {
    elements.outputPath.value = result.toLowerCase().endsWith(".pdf") ? result : `${result}.pdf`;
    updateStartAvailability();
  }
}

function applyPreset(value: string): void {
  if (value === "novel") {
    elements.readingProfile.value = "novel";
    elements.contentStartMode.value = "auto";
    elements.filterMargins.checked = true;
    elements.dropFootnotes.checked = true;
    elements.skipToc.checked = true;
    elements.dropCitationLines.checked = true;
    elements.dropCreditLines.checked = true;
    elements.mergeContinuousPages.checked = true;
    elements.keepTitlePage.checked = true;
  } else if (value === "prose") {
    elements.readingProfile.value = "prose";
    elements.contentStartMode.value = "all";
    elements.filterMargins.checked = true;
    elements.dropFootnotes.checked = true;
    elements.skipToc.checked = true;
    elements.dropCitationLines.checked = true;
    elements.dropCreditLines.checked = false;
    elements.mergeContinuousPages.checked = true;
    elements.keepTitlePage.checked = true;
  } else if (value === "archive") {
    elements.readingProfile.value = "prose";
    elements.contentStartMode.value = "all";
    elements.filterMargins.checked = false;
    elements.dropFootnotes.checked = false;
    elements.skipToc.checked = false;
    elements.dropCitationLines.checked = false;
    elements.dropCreditLines.checked = false;
    elements.dropDiagramLabels.checked = false;
    elements.mergeContinuousPages.checked = false;
  }
  updateModeUi();
  savePreferences();
}

function updateLanguageWarning(): void {
  const mode = actualMode();
  const languages = selectedLanguages();
  if (!languages.length) {
    elements.languageWarning.textContent = "至少选择一种识别语言。";
    elements.languageWarning.classList.remove("hidden");
    return;
  }
  if (mode && ["force", "skip", "redo"].includes(mode) && environment) {
    const missing = languages.filter((language) => !environment!.tesseractLanguages.includes(language));
    if (missing.length) {
      elements.languageWarning.textContent = `Tesseract 尚未安装这些语言包：${missing.join("、")}。`;
      elements.languageWarning.classList.remove("hidden");
      return;
    }
  }
  elements.languageWarning.classList.add("hidden");
}

function requiredEnvironmentReady(mode: ActualMode | null): boolean {
  if (!mode || !environment) return false;
  if (mode === "scan") return environment.paddleReady;
  if (mode === "reading") return environment.readingOptimizerReady;
  if (["force", "skip", "redo"].includes(mode)) {
    return environment.ready && (!elements.readingOptimized.checked || environment.readingOptimizerReady);
  }
  return false;
}

function updateModeUi(): void {
  document.querySelectorAll<HTMLElement>(".mode-option").forEach((card) => {
    const input = card.querySelector<HTMLInputElement>('input[type="radio"]');
    card.classList.toggle("selected", Boolean(input?.checked));
  });
  const uiMode = selectedUiMode();
  const mode = actualMode();
  elements.activeModeHint.textContent = uiMode === "auto"
    ? (mode ? `自动：${MODE_LABELS[mode]}` : "等待分析")
    : MODE_LABELS[uiMode];
  elements.runModeSummary.textContent = mode ? MODE_LABELS[mode] : "等待自动分析";

  const isScan = mode === "scan";
  const isReading = mode === "reading";
  const isLegacy = Boolean(mode && ["force", "skip", "redo"].includes(mode));
  document.querySelectorAll<HTMLElement>(".scan-setting").forEach((row) => row.classList.toggle("inactive", !isScan));
  document.querySelectorAll<HTMLElement>(".legacy-only").forEach((row) => row.classList.toggle("inactive", !isLegacy));
  [elements.modelTier, elements.oversample, elements.scoreThreshold].forEach((control) => { control.disabled = running || !isScan; });
  [elements.deskew, elements.clean, elements.removeBackground, elements.optimize, elements.jobs]
    .forEach((control) => { control.disabled = running || !isLegacy || mode === "redo"; });
  elements.debugReport.disabled = running || !isScan;
  if (!isScan) elements.debugReport.checked = false;
  elements.readingOptimized.checked = isScan || isReading ? true : elements.readingOptimized.checked;
  elements.readingOptimized.disabled = running || isScan || isReading;
  const contentControlsEnabled = isScan;
  elements.readingProfile.disabled = running || (!isScan && !isReading);
  elements.contentStartMode.disabled = running || !contentControlsEnabled;
  elements.contentStartPage.disabled = running || !contentControlsEnabled || elements.contentStartMode.value !== "page";
  elements.keepTitlePage.disabled = running || !contentControlsEnabled || elements.contentStartMode.value !== "auto";
  elements.startPageRow.classList.toggle("inactive", elements.contentStartMode.value !== "page" || !contentControlsEnabled);
  elements.rotatePages.disabled = running || mode === "redo" || isReading;
  elements.mergeContinuousPages.disabled = running || !isScan;
  elements.dropFootnotes.disabled = running || (!isScan && !isReading);
  elements.skipToc.disabled = running || (!isScan && !isReading);
  elements.dropCitationLines.disabled = running || (!isScan && !isReading);
  elements.dropCreditLines.disabled = running || (!isScan && !isReading);

  const outputParts = ["PDF"];
  if (elements.exportText.checked) outputParts.push("TXT");
  if (elements.debugReport.checked && isScan) outputParts.push("复核报告");
  elements.runOutputSummary.textContent = outputParts.join(" + ");

  elements.engineWarning.classList.add("hidden");
  elements.optimizerWarning.classList.add("hidden");
  if (mode && environment && !requiredEnvironmentReady(mode)) {
    const message = mode === "scan" ? environment.paddleMessage
      : mode === "reading" ? environment.readingOptimizerMessage
      : environment.message;
    elements.engineWarning.textContent = message;
    elements.engineWarning.classList.remove("hidden");
  }
  updateLanguageWarning();
  updateStartAvailability();
  savePreferences();
}

function setRunningState(value: boolean): void {
  running = value;
  elements.startButton.classList.toggle("hidden", value);
  elements.cancelButton.classList.toggle("hidden", !value);
  elements.cancelButton.disabled = false;
  elements.browseButton.disabled = value;
  elements.saveAsButton.disabled = value;
  elements.analyzeButton.disabled = value || !elements.inputPath.value;
  document.querySelectorAll<HTMLInputElement | HTMLSelectElement>(".settings-card input, .settings-card select, .mode-option input")
    .forEach((control) => { if (value) control.disabled = true; });
  if (!value) updateModeUi();
}

function updateStartAvailability(): void {
  const mode = actualMode();
  const basic = Boolean(elements.inputPath.value.trim() && elements.outputPath.value.trim() && selectedLanguages().length);
  const autoReady = selectedUiMode() !== "auto" || Boolean(analysis);
  const pageReady = elements.contentStartMode.value !== "page" || Number(elements.contentStartPage.value) >= 1;
  elements.startButton.disabled = running || analysisRunning || !basic || !autoReady || !pageReady || !requiredEnvironmentReady(mode);
}

async function checkEnvironment(): Promise<void> {
  elements.engineBadge.className = "engine-badge checking";
  elements.engineBadgeText.textContent = "正在检查本地组件";
  try {
    const status = await invoke<EnvironmentStatus>("check_environment");
    environment = status;
    const allReady = status.ready && status.paddleReady && status.readingOptimizerReady;
    if (allReady) {
      elements.engineBadge.className = "engine-badge ready";
      elements.engineBadgeText.textContent = `本地组件已就绪 · PaddleOCR ${status.paddleocrVersion ?? ""}`;
      elements.engineHelp.classList.add("hidden");
    } else if (status.ready || status.paddleReady || status.readingOptimizerReady) {
      elements.engineBadge.className = "engine-badge partial";
      elements.engineBadgeText.textContent = "部分组件已安装";
      elements.engineHelp.classList.remove("hidden");
    } else {
      elements.engineBadge.className = "engine-badge missing";
      elements.engineBadgeText.textContent = "需要安装本地组件";
      elements.engineHelp.classList.remove("hidden");
    }
    appendLog(status.paddleMessage);
    appendLog(status.message);
    appendLog(status.readingOptimizerMessage);
  } catch (error) {
    environment = null;
    elements.engineBadge.className = "engine-badge missing";
    elements.engineBadgeText.textContent = "组件检查失败";
    elements.engineHelp.classList.remove("hidden");
    appendLog(`组件检查失败：${String(error)}`);
  }
  updateModeUi();
}

function buildRequest(): OcrRequest | null {
  const mode = actualMode();
  if (!mode) return null;
  const languages = selectedLanguages();
  const jobsValue = elements.jobs.value.trim();
  const startPageValue = elements.contentStartPage.value.trim();
  const engine: OcrEngine = mode === "scan" ? "paddle" : "tesseract";
  return {
    inputPath: elements.inputPath.value.trim(),
    outputPath: elements.outputPath.value.trim(),
    mode,
    ocrEngine: engine,
    modelTier: elements.modelTier.value as ModelTier,
    scoreThreshold: Number(elements.scoreThreshold.value),
    languages,
    rotatePages: mode !== "redo" && mode !== "reading" && elements.rotatePages.checked,
    deskew: ["force", "skip"].includes(mode) && elements.deskew.checked,
    clean: ["force", "skip"].includes(mode) && elements.clean.checked,
    removeBackground: ["force", "skip"].includes(mode) && elements.removeBackground.checked,
    oversample: mode === "redo" || mode === "reading" ? 0 : Number(elements.oversample.value),
    filterMargins: elements.filterMargins.checked,
    dropDiagramLabels: elements.dropDiagramLabels.checked,
    dropFootnotes: elements.dropFootnotes.checked,
    skipToc: elements.skipToc.checked,
    dropRunningHeaders: elements.filterMargins.checked,
    dropCitationLines: elements.dropCitationLines.checked,
    dropCreditLines: elements.dropCreditLines.checked,
    mergeContinuousPages: mode === "scan" && elements.mergeContinuousPages.checked,
    readingProfile: elements.readingProfile.value as ReadingProfile,
    contentStartMode: mode === "scan" ? elements.contentStartMode.value as ContentStartMode : "all",
    contentStartPage: mode === "scan" && startPageValue ? Number(startPageValue) : null,
    keepTitlePage: elements.keepTitlePage.checked,
    optimize: Number(elements.optimize.value),
    jobs: jobsValue ? Number(jobsValue) : null,
    readingOptimized: mode === "scan" || mode === "reading" ? true : elements.readingOptimized.checked,
    exportText: elements.exportText.checked,
    debugReport: mode === "scan" && elements.debugReport.checked
  };
}

async function startOcr(): Promise<void> {
  const request = buildRequest();
  if (!request) return;
  setRunningState(true);
  lastOutputPath = request.outputPath;
  lastTextPath = "";
  elements.resultActions.classList.add("hidden");
  elements.statusTitle.textContent = "正在处理";
  elements.statusMessage.textContent = request.mode === "scan" ? "正在准备 PP-OCRv6 模型。" : "正在准备本地处理流程。";
  elements.pageCounter.textContent = "准备中";
  elements.progressBar.style.width = "0%";
  elements.progressBar.classList.add("indeterminate");
  appendLog(`开始处理：${request.inputPath}`);
  appendLog(`实际方案：${MODE_LABELS[request.mode]}；语言：${request.languages.join("+")}`);
  try {
    await invoke("start_ocr", { request });
  } catch (error) {
    setRunningState(false);
    elements.progressBar.classList.remove("indeterminate");
    elements.statusTitle.textContent = "无法开始";
    elements.statusMessage.textContent = String(error);
    appendLog(`启动失败：${String(error)}`);
  }
}

async function cancelOcr(): Promise<void> {
  elements.cancelButton.disabled = true;
  elements.statusMessage.textContent = "正在请求取消，请稍候。";
  try { await invoke("cancel_ocr"); }
  catch (error) { elements.cancelButton.disabled = false; appendLog(`取消失败：${String(error)}`); }
}

async function openPath(path: string): Promise<void> {
  if (!path) return;
  try { await invoke("open_path", { path }); }
  catch (error) { appendLog(`无法打开文件：${String(error)}`); }
}

function savePreferences(): void {
  const preferences = {
    preset: elements.presetSelect.value,
    modelTier: elements.modelTier.value,
    oversample: elements.oversample.value,
    scoreThreshold: elements.scoreThreshold.value,
    languages: selectedLanguages()
  };
  localStorage.setItem("pdf-text-repair-v020", JSON.stringify(preferences));
}

function restorePreferences(): void {
  try {
    const raw = localStorage.getItem("pdf-text-repair-v020");
    if (!raw) return;
    const settings = JSON.parse(raw) as { preset?: string; modelTier?: string; oversample?: string; scoreThreshold?: string; languages?: string[] };
    if (settings.modelTier) elements.modelTier.value = settings.modelTier;
    if (settings.oversample) elements.oversample.value = settings.oversample;
    if (settings.scoreThreshold) elements.scoreThreshold.value = settings.scoreThreshold;
    if (Array.isArray(settings.languages)) {
      document.querySelectorAll<HTMLInputElement>(".language-grid input").forEach((input) => { input.checked = settings.languages!.includes(input.value); });
    }
  } catch {}
}

async function setupEvents(): Promise<void> {
  unlisteners.push(await listen<LogPayload>("ocr-log", ({ payload }: { payload: LogPayload }) => appendLog(payload.message)));
  unlisteners.push(await listen<ProgressPayload>("ocr-started", ({ payload }: { payload: ProgressPayload }) => {
    elements.statusTitle.textContent = "正在生成 Readest 版";
    elements.statusMessage.textContent = payload.stage;
    elements.pageCounter.textContent = payload.total > 0 ? `0 / ${payload.total}` : "运行中";
  }));
  unlisteners.push(await listen<ProgressPayload>("ocr-progress", ({ payload }: { payload: ProgressPayload }) => {
    elements.progressBar.classList.remove("indeterminate");
    const percent = Math.max(0, Math.min(100, payload.percent));
    elements.progressBar.style.width = `${percent}%`;
    elements.statusMessage.textContent = payload.stage || "正在处理页面。";
    elements.pageCounter.textContent = payload.total > 0 ? `${payload.current} / ${payload.total}` : `${Math.round(percent)}%`;
  }));
  unlisteners.push(await listen<FinishPayload>("ocr-finished", ({ payload }: { payload: FinishPayload }) => {
    setRunningState(false);
    elements.progressBar.classList.remove("indeterminate");
    lastOutputPath = payload.outputPath;
    lastTextPath = payload.textPath ?? "";
    if (payload.success) {
      elements.progressBar.style.width = "100%";
      elements.statusTitle.textContent = "生成完成";
      elements.statusMessage.textContent = payload.message;
      elements.pageCounter.textContent = "100%";
      elements.resultActions.classList.remove("hidden");
      elements.openTextButton.classList.toggle("hidden", !lastTextPath);
    } else if (payload.cancelled) {
      elements.progressBar.style.width = "0%";
      elements.statusTitle.textContent = "已取消";
      elements.statusMessage.textContent = payload.message;
      elements.pageCounter.textContent = "—";
    } else {
      elements.statusTitle.textContent = "处理失败";
      elements.statusMessage.textContent = payload.message;
      elements.pageCounter.textContent = "错误";
    }
    appendLog(payload.message);
    if (lastTextPath) appendLog(`整理后的文字：${lastTextPath}`);
  }));
  unlisteners.push(await getCurrentWebview().onDragDropEvent((event: { payload: { type: string; paths: string[] } }) => {
    if (event.payload.type === "over") elements.dropZone.classList.add("dragging");
    else if (event.payload.type === "drop") {
      elements.dropZone.classList.remove("dragging");
      const pdf = event.payload.paths.find((path: string) => path.toLowerCase().endsWith(".pdf"));
      if (pdf && !running) setInputFile(pdf);
    } else elements.dropZone.classList.remove("dragging");
  }));
}

function bindControls(): void {
  elements.browseButton.addEventListener("click", () => void chooseInput());
  elements.dropZone.addEventListener("click", (event) => { if (!(event.target as HTMLElement).closest("button")) void chooseInput(); });
  elements.dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void chooseInput(); }
  });
  elements.saveAsButton.addEventListener("click", () => void chooseOutput());
  elements.analyzeButton.addEventListener("click", () => void analyzeCurrentPdf());
  document.querySelectorAll<HTMLInputElement>('input[name="mode"]').forEach((input) => input.addEventListener("change", updateModeUi));
  elements.presetSelect.addEventListener("change", () => applyPreset(elements.presetSelect.value));
  elements.contentStartMode.addEventListener("change", updateModeUi);
  [elements.readingProfile, elements.modelTier, elements.oversample, elements.scoreThreshold, elements.contentStartPage,
   elements.filterMargins, elements.dropFootnotes, elements.skipToc, elements.dropCitationLines, elements.dropCreditLines,
   elements.dropDiagramLabels, elements.mergeContinuousPages, elements.keepTitlePage, elements.rotatePages,
   elements.readingOptimized, elements.exportText, elements.debugReport, elements.deskew, elements.clean,
   elements.removeBackground, elements.optimize, elements.jobs]
    .forEach((control) => control.addEventListener("change", updateModeUi));
  document.querySelectorAll<HTMLInputElement>(".language-grid input").forEach((input) => input.addEventListener("change", updateModeUi));
  elements.outputPath.addEventListener("input", updateStartAvailability);
  elements.startButton.addEventListener("click", () => void startOcr());
  elements.cancelButton.addEventListener("click", () => void cancelOcr());
  elements.openResultButton.addEventListener("click", () => void openPath(lastOutputPath));
  elements.openTextButton.addEventListener("click", () => void openPath(lastTextPath));
  elements.revealButton.addEventListener("click", async () => {
    if (!lastOutputPath) return;
    try { await invoke("reveal_in_finder", { path: lastOutputPath }); }
    catch (error) { appendLog(`无法在 Finder 中显示：${String(error)}`); }
  });
  elements.installButton.addEventListener("click", async () => {
    try { await invoke("launch_installer"); appendLog("已在 Terminal 中打开组件安装器。"); }
    catch (error) { appendLog(`无法启动安装器：${String(error)}`); }
  });
  elements.recheckButton.addEventListener("click", () => void checkEnvironment());
  elements.clearLogButton.addEventListener("click", (event) => { event.preventDefault(); elements.logOutput.textContent = ""; });
  window.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && !elements.startButton.disabled && !running) {
      event.preventDefault(); void startOcr();
    }
  });
}

async function initialize(): Promise<void> {
  restorePreferences();
  bindControls();
  updateModeUi();
  await setupEvents();
  await checkEnvironment();
}

window.addEventListener("beforeunload", () => unlisteners.forEach((unlisten) => unlisten()));
void initialize();
