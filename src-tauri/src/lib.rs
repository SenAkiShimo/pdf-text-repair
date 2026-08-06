use regex::Regex;
use serde::{Deserialize, Serialize};
use std::{
    env,
    fs,
    io::Read,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::Mutex,
    thread,
    time::{SystemTime, UNIX_EPOCH},
};
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use tauri::{AppHandle, Emitter, Manager, State};

#[derive(Default)]
struct JobState {
    running: Mutex<Option<RunningJob>>,
}

#[derive(Clone)]
struct RunningJob {
    pid: u32,
    cancel_requested: bool,
}

#[derive(serde::Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
struct OcrRequest {
    input_path: String,
    output_path: String,
    mode: String,
    ocr_engine: String,
    model_tier: String,
    score_threshold: f64,
    languages: Vec<String>,
    rotate_pages: bool,
    deskew: bool,
    clean: bool,
    remove_background: bool,
    oversample: u16,
    filter_margins: bool,
    drop_diagram_labels: bool,
    drop_footnotes: bool,
    skip_toc: bool,
    drop_running_headers: bool,
    drop_citation_lines: bool,
    drop_credit_lines: bool,
    merge_continuous_pages: bool,
    reading_profile: String,
    content_start_mode: String,
    content_start_page: Option<u32>,
    keep_title_page: bool,
    optimize: u8,
    jobs: Option<u8>,
    reading_optimized: bool,
    export_text: bool,
    debug_report: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EnvironmentStatus {
    ready: bool,
    paddle_ready: bool,
    paddle_python: Option<String>,
    paddleocr_version: Option<String>,
    paddle_message: String,
    ocrmypdf_path: Option<String>,
    ocrmypdf_version: Option<String>,
    tesseract_path: Option<String>,
    tesseract_languages: Vec<String>,
    reading_optimizer_ready: bool,
    reading_optimizer_python: Option<String>,
    reading_optimizer_message: String,
    message: String,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AnalysisSample {
    page: u32,
    text_chars: u32,
    cjk_chars: u32,
    suspicious_ratio: f64,
    image_coverage: f64,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DocumentAnalysis {
    page_count: u32,
    sampled_pages: Vec<u32>,
    sample_count: u32,
    pages_with_text: u32,
    pages_without_text: u32,
    suspicious_text_pages: u32,
    image_dominant_pages: u32,
    recommended_mode: String,
    confidence: f64,
    summary: String,
    samples: Vec<AnalysisSample>,
}

#[derive(Clone, Serialize)]
struct LogPayload {
    message: String,
}

#[derive(Clone, Serialize)]
struct ProgressPayload {
    current: u32,
    total: u32,
    percent: f64,
    stage: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct FinishPayload {
    success: bool,
    cancelled: bool,
    output_path: String,
    text_path: Option<String>,
    message: String,
}

fn executable_candidates(name: &str) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(path_var) = env::var_os("PATH") {
        for directory in env::split_paths(&path_var) {
            candidates.push(directory.join(name));
        }
    }
    for directory in [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/opt/local/bin",
    ] {
        candidates.push(Path::new(directory).join(name));
    }
    candidates
}

fn find_executable(name: &str) -> Option<PathBuf> {
    executable_candidates(name)
        .into_iter()
        .find(|candidate| candidate.is_file())
}

fn enhanced_path() -> String {
    let current = env::var("PATH").unwrap_or_default();
    let mut entries = vec![
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/opt/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    .into_iter()
    .map(ToOwned::to_owned)
    .collect::<Vec<String>>();

    for entry in current.split(':').filter(|entry| !entry.is_empty()) {
        if !entries.iter().any(|existing| existing == entry) {
            entries.push(entry.to_owned());
        }
    }
    entries.join(":")
}

fn capture_command(executable: &Path, args: &[&str]) -> Result<String, String> {
    let output = Command::new(executable)
        .args(args)
        .env("PATH", enhanced_path())
        .output()
        .map_err(|error| format!("无法运行 {}：{error}", executable.display()))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        return Err(if stderr.is_empty() {
            format!("{} 返回错误状态", executable.display())
        } else {
            stderr
        });
    }

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
    Ok(if stdout.is_empty() { stderr } else { stdout })
}

fn installed_languages(tesseract: &Path) -> Vec<String> {
    capture_command(tesseract, &["--list-langs"])
        .unwrap_or_default()
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty() && !line.starts_with("List of available languages"))
        .map(ToOwned::to_owned)
        .collect()
}

fn reading_optimizer_script(app: &AppHandle) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(resource_directory) = app.path().resource_dir() {
        candidates.push(resource_directory.join("resources/readest_text_layer.py"));
        candidates.push(resource_directory.join("readest_text_layer.py"));
    }
    candidates.push(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/readest_text_layer.py"),
    );
    candidates.into_iter().find(|path| path.is_file())
}

fn paddle_scan_script(app: &AppHandle) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(resource_directory) = app.path().resource_dir() {
        candidates.push(resource_directory.join("resources/paddle_scan_pipeline.py"));
        candidates.push(resource_directory.join("paddle_scan_pipeline.py"));
    }
    candidates.push(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/paddle_scan_pipeline.py"),
    );
    candidates.into_iter().find(|path| path.is_file())
}

fn pdf_analyze_script(app: &AppHandle) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(resource_directory) = app.path().resource_dir() {
        candidates.push(resource_directory.join("resources/pdf_analyze.py"));
        candidates.push(resource_directory.join("pdf_analyze.py"));
    }
    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/pdf_analyze.py"));
    candidates.into_iter().find(|path| path.is_file())
}

fn installer_script(app: &AppHandle) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(resource_directory) = app.path().resource_dir() {
        candidates.push(resource_directory.join("resources/install-ocr-engine-macos.command"));
        candidates.push(resource_directory.join("install-ocr-engine-macos.command"));
    }
    candidates.push(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/install-ocr-engine-macos.command"),
    );
    candidates.into_iter().find(|path| path.is_file())
}

fn private_optimizer_python() -> Option<PathBuf> {
    let home = env::var_os("HOME").map(PathBuf::from)?;
    let candidate = home
        .join("Library/Application Support/PDF Text Repair/venv/bin/python");
    candidate.is_file().then_some(candidate)
}

fn python_supports_pymupdf(python: &Path) -> bool {
    capture_command(
        python,
        &[
            "-c",
            "import pymupdf; print(getattr(pymupdf, '__version__', 'ready'))",
        ],
    )
    .is_ok()
}

fn python_supports_paddle(python: &Path) -> bool {
    capture_command(
        python,
        &[
            "-c",
            "import importlib.util, paddleocr, pymupdf; assert importlib.util.find_spec('paddle') or importlib.util.find_spec('onnxruntime'); print(getattr(paddleocr, '__version__', 'ready'))",
        ],
    )
    .is_ok()
}

fn find_paddle_python() -> Option<PathBuf> {
    let private_python = private_optimizer_python()?;
    python_supports_paddle(&private_python).then_some(private_python)
}

fn find_reading_optimizer_python() -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(private_python) = private_optimizer_python() {
        candidates.push(private_python);
    }
    for name in ["python3", "python3.14", "python3.13", "python3.12"] {
        if let Some(path) = find_executable(name) {
            candidates.push(path);
        }
    }
    candidates
        .into_iter()
        .find(|candidate| python_supports_pymupdf(candidate))
}

#[tauri::command]
fn check_environment(app: AppHandle) -> EnvironmentStatus {
    let ocrmypdf = find_executable("ocrmypdf");
    let tesseract = find_executable("tesseract");
    let version = ocrmypdf
        .as_deref()
        .and_then(|path| capture_command(path, &["--version"]).ok())
        .and_then(|text| text.lines().next().map(ToOwned::to_owned));
    let languages = tesseract
        .as_deref()
        .map(installed_languages)
        .unwrap_or_default();
    let ready = ocrmypdf.is_some() && tesseract.is_some();

    let optimizer_script_ready = reading_optimizer_script(&app).is_some();
    let optimizer_python = find_reading_optimizer_python();
    let reading_optimizer_ready = optimizer_script_ready && optimizer_python.is_some();
    let reading_optimizer_message = if reading_optimizer_ready {
        "Readest 连续朗读优化器已就绪。".to_owned()
    } else if !optimizer_script_ready {
        "应用中缺少朗读优化脚本，请重新下载完整源码包。".to_owned()
    } else {
        "尚未安装朗读优化运行环境。请再次运行安装脚本，以创建私有 PyMuPDF 环境。"
            .to_owned()
    };

    let paddle_script_ready = paddle_scan_script(&app).is_some();
    let paddle_python = find_paddle_python();
    let paddleocr_version = paddle_python.as_deref().and_then(|python| {
        capture_command(
            python,
            &[
                "-c",
                "import paddleocr; print(getattr(paddleocr, '__version__', 'unknown'))",
            ],
        )
        .ok()
        .and_then(|text| text.lines().next().map(ToOwned::to_owned))
    });
    let paddle_ready = paddle_script_ready && paddle_python.is_some();
    let paddle_message = if paddle_ready {
        format!(
            "PaddleOCR {} 与 PP-OCRv6 扫描书引擎已就绪。",
            paddleocr_version.as_deref().unwrap_or("版本未知")
        )
    } else if !paddle_script_ready {
        "应用中缺少 PaddleOCR 扫描书脚本，请重新下载完整源码包。".to_owned()
    } else {
        "尚未安装 PaddleOCR。请再次运行安装脚本；安装器会使用独立的 Python 3.13 环境。"
            .to_owned()
    };

    let message = if ready {
        format!(
            "兼容 OCR 引擎已就绪。OCRmyPDF：{}；已检测到 {} 个 Tesseract 语言包。",
            version.as_deref().unwrap_or("版本未知"),
            languages.len()
        )
    } else {
        let mut missing = Vec::new();
        if ocrmypdf.is_none() {
            missing.push("OCRmyPDF");
        }
        if tesseract.is_none() {
            missing.push("Tesseract");
        }
        format!(
            "兼容模式缺少 {}。请运行 scripts/install-ocr-engine-macos.command。",
            missing.join("、")
        )
    };

    EnvironmentStatus {
        ready,
        paddle_ready,
        paddle_python: paddle_python.map(|path| path.to_string_lossy().into_owned()),
        paddleocr_version,
        paddle_message,
        ocrmypdf_path: ocrmypdf.map(|path| path.to_string_lossy().into_owned()),
        ocrmypdf_version: version,
        tesseract_path: tesseract.map(|path| path.to_string_lossy().into_owned()),
        tesseract_languages: languages,
        reading_optimizer_ready,
        reading_optimizer_python: optimizer_python
            .map(|path| path.to_string_lossy().into_owned()),
        reading_optimizer_message,
        message,
    }
}

#[tauri::command]
fn analyze_pdf(app: AppHandle, path: String) -> Result<DocumentAnalysis, String> {
    let input = PathBuf::from(path.trim());
    if !input.is_file() {
        return Err("输入 PDF 不存在。".to_owned());
    }
    let python = find_reading_optimizer_python()
        .ok_or_else(|| "分析 PDF 需要本地 PyMuPDF 环境，请先安装组件。".to_owned())?;
    let script = pdf_analyze_script(&app)
        .ok_or_else(|| "应用中缺少 PDF 分析脚本。".to_owned())?;
    let input_string = input.to_string_lossy().into_owned();
    let script_string = script.to_string_lossy().into_owned();
    let output = capture_command(&python, &[script_string.as_str(), input_string.as_str()])?;
    serde_json::from_str::<DocumentAnalysis>(output.trim())
        .map_err(|error| format!("无法解析 PDF 分析结果：{error}"))
}

fn count_pdf_pages(input: &Path) -> u32 {
    let Some(qpdf) = find_executable("qpdf") else {
        return 0;
    };
    let input_string = input.to_string_lossy().into_owned();
    capture_command(&qpdf, &["--show-npages", input_string.as_str()])
        .ok()
        .and_then(|value| value.trim().parse::<u32>().ok())
        .unwrap_or(0)
}

fn stage_from_line(line: &str) -> String {
    let lower = line.to_lowercase();
    if lower.contains("paddle_init") {
        "正在加载 PP-OCRv6 模型".to_owned()
    } else if lower.contains("paddle_page") {
        "正在使用 PaddleOCR 识别页面".to_owned()
    } else if lower.contains("paddle_layout") {
        "正在整理目录、正文与阅读顺序".to_owned()
    } else if lower.contains("paddle_done") {
        "正在完成扫描书 PDF".to_owned()
    } else if lower.contains("reading_layer") {
        "正在合并连续朗读文字层".to_owned()
    } else if lower.contains("scanning contents") {
        "正在分析页面结构".to_owned()
    } else if lower.contains("raster") {
        "正在重新渲染页面".to_owned()
    } else if lower.contains("deskew") {
        "正在纠正页面倾斜".to_owned()
    } else if lower.contains("rotate") || lower.contains("orientation") {
        "正在检测页面方向".to_owned()
    } else if lower.contains("ocr") || lower.contains("tesseract") {
        "正在识别文字".to_owned()
    } else if lower.contains("optimiz") || lower.contains("compress") {
        "正在优化输出 PDF".to_owned()
    } else if lower.contains("pdf/a") || lower.contains("metadata") {
        "正在写入 PDF".to_owned()
    } else {
        "正在处理 PDF".to_owned()
    }
}

fn emit_output_line(app: &AppHandle, line: &str, known_total: u32) {
    let cleaned = line.trim_matches(|character: char| character.is_whitespace() || character == '\0');
    if cleaned.is_empty() {
        return;
    }

    let _ = app.emit(
        "ocr-log",
        LogPayload {
            message: cleaned.to_owned(),
        },
    );

    let ratio_regex = Regex::new(r"(?P<current>\d+)\s*/\s*(?P<total>\d+)").expect("valid regex");
    let percent_regex =
        Regex::new(r"(?P<percent>\d{1,3}(?:\.\d+)?)%").expect("valid regex");
    let stage = stage_from_line(cleaned);

    if let Some(captures) = ratio_regex.captures(cleaned) {
        let current = captures
            .name("current")
            .and_then(|value| value.as_str().parse::<u32>().ok())
            .unwrap_or(0);
        let parsed_total = captures
            .name("total")
            .and_then(|value| value.as_str().parse::<u32>().ok())
            .unwrap_or(known_total);
        let total = if parsed_total == 0 {
            known_total
        } else {
            parsed_total
        };
        let percent = if total > 0 {
            (current as f64 / total as f64 * 100.0).clamp(0.0, 100.0)
        } else {
            0.0
        };
        let _ = app.emit(
            "ocr-progress",
            ProgressPayload {
                current,
                total,
                percent,
                stage,
            },
        );
        return;
    }

    if let Some(captures) = percent_regex.captures(cleaned) {
        let percent = captures
            .name("percent")
            .and_then(|value| value.as_str().parse::<f64>().ok())
            .unwrap_or(0.0)
            .clamp(0.0, 100.0);
        let current = if known_total > 0 {
            ((percent / 100.0) * known_total as f64).round() as u32
        } else {
            0
        };
        let _ = app.emit(
            "ocr-progress",
            ProgressPayload {
                current,
                total: known_total,
                percent,
                stage,
            },
        );
    }
}

fn stream_process_output<R: Read + Send + 'static>(mut reader: R, app: AppHandle, total: u32) {
    let mut buffer = [0_u8; 2048];
    let mut pending = Vec::<u8>::new();

    loop {
        match reader.read(&mut buffer) {
            Ok(0) => break,
            Ok(read_count) => {
                for byte in &buffer[..read_count] {
                    if *byte == b'\n' || *byte == b'\r' {
                        if !pending.is_empty() {
                            let line = String::from_utf8_lossy(&pending).into_owned();
                            emit_output_line(&app, &line, total);
                            pending.clear();
                        }
                    } else {
                        pending.push(*byte);
                    }
                }
            }
            Err(error) => {
                let _ = app.emit(
                    "ocr-log",
                    LogPayload {
                        message: format!("读取处理输出时发生错误：{error}"),
                    },
                );
                break;
            }
        }
    }

    if !pending.is_empty() {
        let line = String::from_utf8_lossy(&pending).into_owned();
        emit_output_line(&app, &line, total);
    }
}

fn companion_text_path(output: &Path) -> PathBuf {
    let stem = output
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("output");
    output.with_file_name(format!("{stem}-text.txt"))
}

fn companion_debug_path(output: &Path) -> PathBuf {
    let stem = output
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("output");
    output.with_file_name(format!("{stem}-ocr-report.json"))
}

fn companion_review_path(output: &Path) -> PathBuf {
    let stem = output
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("output");
    output.with_file_name(format!("{stem}-review.txt"))
}

fn standard_fallback_path(output: &Path) -> PathBuf {
    let stem = output
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("output");
    output.with_file_name(format!("{stem}-standard.pdf"))
}

fn temporary_sibling(output: &Path, label: &str, extension: &str) -> PathBuf {
    let stem = output
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("output");
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();
    output.with_file_name(format!(
        ".{stem}.pdf-text-repair-{}-{timestamp}-{label}.{extension}",
        std::process::id()
    ))
}

fn validate_request(request: &OcrRequest) -> Result<(PathBuf, PathBuf, Option<PathBuf>), String> {
    let input = PathBuf::from(request.input_path.trim());
    let output = PathBuf::from(request.output_path.trim());

    if !input.is_file() {
        return Err("输入 PDF 不存在。".to_owned());
    }
    if input
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_lowercase)
        .as_deref()
        != Some("pdf")
    {
        return Err("输入文件必须是 PDF。".to_owned());
    }
    if output
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_lowercase)
        .as_deref()
        != Some("pdf")
    {
        return Err("输出文件必须使用 .pdf 扩展名。".to_owned());
    }
    if input == output {
        return Err("输出路径不能与原始 PDF 相同；软件不会覆盖原文件。".to_owned());
    }
    if output.exists() {
        return Err("输出文件已经存在，请选择新的名称。".to_owned());
    }
    if request.languages.is_empty() {
        return Err("至少选择一种识别语言。".to_owned());
    }
    if !matches!(request.mode.as_str(), "force" | "scan" | "skip" | "redo" | "reading") {
        return Err("未知的处理模式。".to_owned());
    }
    if !matches!(request.ocr_engine.as_str(), "paddle" | "tesseract") {
        return Err("未知的 OCR 引擎。".to_owned());
    }
    if request.ocr_engine == "paddle" && request.mode != "scan" {
        return Err("PaddleOCR 高精度引擎目前用于图片书 / 扫描书模式。".to_owned());
    }
    if !matches!(request.model_tier.as_str(), "tiny" | "small" | "medium") {
        return Err("PaddleOCR 模型档位无效。".to_owned());
    }
    if !matches!(request.reading_profile.as_str(), "auto" | "prose" | "novel") {
        return Err("朗读排版模式无效。".to_owned());
    }
    if !matches!(request.content_start_mode.as_str(), "all" | "auto" | "page") {
        return Err("正文起始模式无效。".to_owned());
    }
    if request.content_start_mode == "page" && request.content_start_page.unwrap_or(0) < 1 {
        return Err("从指定页开始时，页码必须大于 0。".to_owned());
    }
    if !(0.0..=1.0).contains(&request.score_threshold) {
        return Err("识别置信度阈值必须在 0 到 1 之间。".to_owned());
    }
    if request.optimize > 3 {
        return Err("文件优化级别无效。".to_owned());
    }
    if request.oversample != 0 && !(150..=600).contains(&request.oversample) {
        return Err("扫描增强 DPI 必须在 150 到 600 之间，或设为 0 关闭。".to_owned());
    }
    if let Some(parent) = output
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        if !parent.exists() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("无法创建输出文件夹：{error}"))?;
        }
    }

    let text_output = request.export_text.then(|| companion_text_path(&output));
    if text_output.as_ref().is_some_and(|path| path.exists()) {
        return Err("配套 TXT 已存在，请更换输出 PDF 名称或移走旧 TXT。".to_owned());
    }
    if request.debug_report && companion_debug_path(&output).exists() {
        return Err("OCR 识别报告已存在，请更换输出 PDF 名称或移走旧 JSON。".to_owned());
    }
    if request.debug_report && companion_review_path(&output).exists() {
        return Err("低置信度复核清单已存在，请更换输出 PDF 名称或移走旧 TXT。".to_owned());
    }

    Ok((input, output, text_output))
}

fn set_running_job(state: &State<'_, JobState>, pid: u32) -> Result<(), String> {
    let mut guard = state.running.lock().map_err(|_| "无法更新任务状态。")?;
    let cancel_requested = guard
        .as_ref()
        .map(|job| job.cancel_requested)
        .unwrap_or(false);
    *guard = Some(RunningJob {
        pid,
        cancel_requested,
    });
    Ok(())
}

fn was_cancelled(state: &State<'_, JobState>) -> bool {
    state
        .running
        .lock()
        .ok()
        .and_then(|guard| guard.as_ref().map(|job| job.cancel_requested))
        .unwrap_or(false)
}

fn clear_running_job(state: &State<'_, JobState>) {
    if let Ok(mut guard) = state.running.lock() {
        *guard = None;
    }
}

fn start_paddle_scan_job(
    app: AppHandle,
    state: &State<'_, JobState>,
    request: &OcrRequest,
    input: PathBuf,
    output: PathBuf,
    text_output: Option<PathBuf>,
) -> Result<(), String> {
    let python = find_paddle_python().ok_or_else(|| {
        "PaddleOCR 高精度环境尚未安装。请再次运行安装脚本。".to_owned()
    })?;
    let script = paddle_scan_script(&app)
        .ok_or_else(|| "应用中缺少 PaddleOCR 扫描书脚本。".to_owned())?;
    let debug_output = request.debug_report.then(|| companion_debug_path(&output));
    let review_output = request.debug_report.then(|| companion_review_path(&output));
    let total_pages = count_pdf_pages(&input);
    let dpi = if request.oversample > 0 {
        request.oversample
    } else {
        300
    };
    let font_name = if request.languages.iter().any(|language| language == "jpn") {
        "japan"
    } else if request.languages.iter().any(|language| language == "chi_tra")
        && !request.languages.iter().any(|language| language == "chi_sim")
    {
        "china-t"
    } else {
        "china-s"
    };

    let mut command = Command::new(&python);
    command
        .arg(&script)
        .arg(&input)
        .arg(&output)
        .arg("--languages")
        .arg(request.languages.join("+"))
        .arg("--dpi")
        .arg(dpi.to_string())
        .arg("--model-tier")
        .arg(&request.model_tier)
        .arg("--score-threshold")
        .arg(format!("{:.3}", request.score_threshold))
        .arg("--font-name")
        .arg(font_name)
        .arg("--font-size")
        .arg("3.2")
        .arg("--reading-profile")
        .arg(&request.reading_profile)
        .arg("--content-start-mode")
        .arg(&request.content_start_mode)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("PYTHONUNBUFFERED", "1")
        .env("PADDLE_PDX_MODEL_SOURCE", "modelscope")
        .env("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        .env("PDF_TEXT_REPAIR_MODEL_SOURCES", "modelscope,bos,huggingface")
        .env("PATH", enhanced_path());
    if let Some(start_page) = request.content_start_page {
        if request.content_start_mode == "page" {
            command.arg("--content-start-page").arg(start_page.to_string());
        }
    }
    if !request.keep_title_page {
        command.arg("--skip-title-page");
    }
    if request.filter_margins {
        command.arg("--filter-margins");
    }
    if request.drop_diagram_labels {
        command.arg("--drop-diagram-labels");
    }
    if !request.drop_footnotes {
        command.arg("--include-footnotes");
    }
    if !request.skip_toc {
        command.arg("--read-toc");
    }
    if !request.drop_running_headers {
        command.arg("--keep-running-headers");
    }
    if !request.drop_citation_lines {
        command.arg("--keep-citation-lines");
    }
    if !request.drop_credit_lines {
        command.arg("--keep-credit-lines");
    }
    if request.rotate_pages {
        command.arg("--use-orientation");
    }
    if !request.merge_continuous_pages {
        command.arg("--no-merge-continuous-pages");
    }
    if let Some(text_path) = &text_output {
        command.arg("--text-output").arg(text_path);
    }
    if let Some(debug_path) = &debug_output {
        command.arg("--debug-json").arg(debug_path);
    }
    if let Some(review_path) = &review_output {
        command.arg("--review-output").arg(review_path);
    }

    let mut child = command
        .spawn()
        .map_err(|error| format!("无法启动 PaddleOCR：{error}"))?;
    set_running_job(state, child.id())?;
    let _ = app.emit(
        "ocr-started",
        ProgressPayload {
            current: 0,
            total: total_pages,
            percent: 0.0,
            stage: "正在加载 PP-OCRv6 高精度模型".to_owned(),
        },
    );

    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    let app_for_thread = app.clone();
    let output_for_thread = output.clone();
    let text_for_thread = text_output.clone();
    let debug_for_thread = debug_output.clone();
    let review_for_thread = review_output.clone();

    thread::spawn(move || {
        let stdout_thread = stdout.map(|stream| {
            let app = app_for_thread.clone();
            thread::spawn(move || stream_process_output(stream, app, total_pages))
        });
        let stderr_thread = stderr.map(|stream| {
            let app = app_for_thread.clone();
            thread::spawn(move || stream_process_output(stream, app, total_pages))
        });
        let status = child.wait();
        if let Some(handle) = stdout_thread {
            let _ = handle.join();
        }
        if let Some(handle) = stderr_thread {
            let _ = handle.join();
        }

        let state_for_thread = app_for_thread.state::<JobState>();
        let cancelled = was_cancelled(&state_for_thread);
        let success = status
            .as_ref()
            .map(|value| value.success())
            .unwrap_or(false)
            && output_for_thread.is_file()
            && !cancelled;
        let message = if success {
            let mut details = vec![format!(
                "PaddleOCR 扫描书处理完成：{}",
                output_for_thread.display()
            )];
            if let Some(path) = &review_for_thread {
                details.push(format!("低置信度复核清单：{}", path.display()));
            }
            details.join("\n")
        } else if cancelled {
            let _ = fs::remove_file(&output_for_thread);
            if let Some(path) = &text_for_thread {
                let _ = fs::remove_file(path);
            }
            if let Some(path) = &debug_for_thread {
                let _ = fs::remove_file(path);
            }
            if let Some(path) = &review_for_thread {
                let _ = fs::remove_file(path);
            }
            "任务已取消。".to_owned()
        } else {
            let _ = fs::remove_file(&output_for_thread);
            if let Some(path) = &text_for_thread {
                let _ = fs::remove_file(path);
            }
            if let Some(path) = &debug_for_thread {
                let _ = fs::remove_file(path);
            }
            if let Some(path) = &review_for_thread {
                let _ = fs::remove_file(path);
            }
            match status {
                Ok(value) => format!("PaddleOCR 处理失败，退出状态：{value}"),
                Err(error) => format!("等待 PaddleOCR 结束时发生错误：{error}"),
            }
        };
        clear_running_job(&state_for_thread);
        let _ = app_for_thread.emit(
            "ocr-finished",
            FinishPayload {
                success,
                cancelled,
                output_path: output_for_thread.to_string_lossy().into_owned(),
                text_path: text_for_thread.map(|path| path.to_string_lossy().into_owned()),
                message,
            },
        );
    });

    Ok(())
}

fn start_existing_reading_job(
    app: AppHandle,
    state: &State<'_, JobState>,
    request: &OcrRequest,
    input: PathBuf,
    output: PathBuf,
    text_output: Option<PathBuf>,
) -> Result<(), String> {
    let python = find_reading_optimizer_python()
        .ok_or_else(|| "Readest 朗读优化环境尚未安装。".to_owned())?;
    let script = reading_optimizer_script(&app)
        .ok_or_else(|| "应用中缺少 Readest 朗读优化脚本。".to_owned())?;
    let total_pages = count_pdf_pages(&input);
    let font_name = if request.languages.iter().any(|language| language == "jpn") {
        "japan"
    } else if request.languages.iter().any(|language| language == "chi_tra")
        && !request.languages.iter().any(|language| language == "chi_sim")
    {
        "china-t"
    } else {
        "china-s"
    };
    let mut command = Command::new(&python);
    command
        .arg(&script)
        .arg(&input)
        .arg(&output)
        .arg("--prefer-pdf-text")
        .arg("--scan-layout")
        .arg("--font-name")
        .arg(font_name)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("PYTHONUNBUFFERED", "1")
        .env("PATH", enhanced_path());
    if request.filter_margins {
        command.arg("--filter-margins");
    }
    if request.drop_diagram_labels {
        command.arg("--drop-diagram-labels");
    }
    if let Some(text_path) = &text_output {
        command.arg("--text-output").arg(text_path);
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("无法启动朗读层整理器：{error}"))?;
    set_running_job(state, child.id())?;
    let _ = app.emit(
        "ocr-started",
        ProgressPayload {
            current: 0,
            total: total_pages,
            percent: 0.0,
            stage: "正在提取并整理现有文字层".to_owned(),
        },
    );
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    let app_for_thread = app.clone();
    let output_for_thread = output.clone();
    let text_for_thread = text_output.clone();
    thread::spawn(move || {
        let stdout_thread = stdout.map(|stream| {
            let app = app_for_thread.clone();
            thread::spawn(move || stream_process_output(stream, app, total_pages))
        });
        let stderr_thread = stderr.map(|stream| {
            let app = app_for_thread.clone();
            thread::spawn(move || stream_process_output(stream, app, total_pages))
        });
        let status = child.wait();
        if let Some(handle) = stdout_thread { let _ = handle.join(); }
        if let Some(handle) = stderr_thread { let _ = handle.join(); }
        let state_for_thread = app_for_thread.state::<JobState>();
        let cancelled = was_cancelled(&state_for_thread);
        let success = status.as_ref().map(|value| value.success()).unwrap_or(false)
            && output_for_thread.is_file() && !cancelled;
        let message = if success {
            format!("Readest 连续朗读层整理完成：{}", output_for_thread.display())
        } else if cancelled {
            let _ = fs::remove_file(&output_for_thread);
            if let Some(path) = &text_for_thread { let _ = fs::remove_file(path); }
            "任务已取消。".to_owned()
        } else {
            let _ = fs::remove_file(&output_for_thread);
            match status {
                Ok(value) => format!("朗读层整理失败，退出状态：{value}"),
                Err(error) => format!("等待朗读层整理器结束时发生错误：{error}"),
            }
        };
        clear_running_job(&state_for_thread);
        let _ = app_for_thread.emit(
            "ocr-finished",
            FinishPayload {
                success, cancelled,
                output_path: output_for_thread.to_string_lossy().into_owned(),
                text_path: text_for_thread.map(|path| path.to_string_lossy().into_owned()),
                message,
            },
        );
    });
    Ok(())
}

#[tauri::command]
fn start_ocr(
    app: AppHandle,
    state: State<'_, JobState>,
    request: OcrRequest,
) -> Result<(), String> {
    {
        let guard = state.running.lock().map_err(|_| "无法读取任务状态。")?;
        if guard.is_some() {
            return Err("已有一个 OCR 任务正在运行。".to_owned());
        }
    }

    let (input, output, text_output) = validate_request(&request)?;
    if request.mode == "reading" {
        return start_existing_reading_job(app, &state, &request, input, output, text_output);
    }
    if request.mode == "scan" && request.ocr_engine == "paddle" {
        return start_paddle_scan_job(app, &state, &request, input, output, text_output);
    }

    let ocrmypdf = find_executable("ocrmypdf")
        .ok_or_else(|| "未找到 OCRmyPDF。请运行安装脚本。".to_owned())?;
    let tesseract = find_executable("tesseract")
        .ok_or_else(|| "未找到 Tesseract。请运行安装脚本。".to_owned())?;
    let available_languages = installed_languages(&tesseract);
    let missing_languages = request
        .languages
        .iter()
        .filter(|language| !available_languages.contains(language))
        .cloned()
        .collect::<Vec<String>>();
    if !missing_languages.is_empty() {
        return Err(format!(
            "Tesseract 缺少语言包：{}。请安装 tesseract-lang 后重新检查。",
            missing_languages.join("、")
        ));
    }

    let optimizer = if request.reading_optimized {
        let python = find_reading_optimizer_python().ok_or_else(|| {
            "Readest 朗读优化运行环境尚未安装。请再次运行安装脚本。".to_owned()
        })?;
        let script = reading_optimizer_script(&app)
            .ok_or_else(|| "应用中缺少 Readest 朗读优化脚本。".to_owned())?;
        Some((python, script))
    } else {
        None
    };

    let stage_output = if request.reading_optimized {
        temporary_sibling(&output, "ocr-stage", "pdf")
    } else {
        output.clone()
    };
    let sidecar_output = if request.reading_optimized {
        Some(temporary_sibling(&output, "ocr-sidecar", "txt"))
    } else {
        text_output.clone()
    };

    let mut args = Vec::<String>::new();
    match request.mode.as_str() {
        "force" | "scan" => args.push("--force-ocr".to_owned()),
        "skip" => args.push("--skip-text".to_owned()),
        "redo" => args.push("--redo-ocr".to_owned()),
        _ => unreachable!(),
    }
    args.push("--language".to_owned());
    args.push(request.languages.join("+"));
    args.push("--output-type".to_owned());
    args.push("pdf".to_owned());
    args.push("--optimize".to_owned());
    args.push(request.optimize.to_string());
    args.push("--tesseract-timeout".to_owned());
    args.push("180".to_owned());
    if let Some(sidecar) = &sidecar_output {
        args.push("--sidecar".to_owned());
        args.push(sidecar.to_string_lossy().into_owned());
    }
    if request.mode != "redo" {
        if request.rotate_pages {
            args.push("--rotate-pages".to_owned());
        }
        if request.deskew {
            args.push("--deskew".to_owned());
        }
        if request.clean {
            args.push("--clean".to_owned());
        }
        if request.remove_background {
            args.push("--remove-background".to_owned());
        }
        if request.oversample > 0 {
            args.push("--oversample".to_owned());
            args.push(request.oversample.to_string());
        }
    }
    if let Some(jobs) = request.jobs.filter(|jobs| *jobs > 0) {
        args.push("--jobs".to_owned());
        args.push(jobs.to_string());
    }
    args.push(input.to_string_lossy().into_owned());
    args.push(stage_output.to_string_lossy().into_owned());

    let total_pages = count_pdf_pages(&input);
    let mut command = Command::new(&ocrmypdf);
    command
        .args(&args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("PYTHONUNBUFFERED", "1")
        .env("PATH", enhanced_path());

    let mut child = command
        .spawn()
        .map_err(|error| format!("无法启动 OCRmyPDF：{error}"))?;
    let initial_pid = child.id();
    set_running_job(&state, initial_pid)?;

    let start_stage = if total_pages > 0 {
        format!("OCRmyPDF 已启动，共检测到 {total_pages} 页。")
    } else {
        "OCRmyPDF 已启动，正在读取页面。".to_owned()
    };
    let _ = app.emit(
        "ocr-started",
        ProgressPayload {
            current: 0,
            total: total_pages,
            percent: 0.0,
            stage: start_stage,
        },
    );

    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    let app_for_thread = app.clone();
    let output_for_thread = output.clone();
    let input_for_thread = input.clone();
    let stage_for_thread = stage_output.clone();
    let sidecar_for_thread = sidecar_output.clone();
    let text_for_thread = text_output.clone();
    let reading_optimized = request.reading_optimized;
    let mode_for_thread = request.mode.clone();
    let filter_margins_for_thread = request.filter_margins;
    let drop_diagram_labels_for_thread = request.drop_diagram_labels;
    let reading_font_for_thread = if request.languages.iter().any(|language| language == "jpn") {
        "japan".to_owned()
    } else if request.languages.iter().any(|language| language == "chi_tra")
        && !request.languages.iter().any(|language| language == "chi_sim")
    {
        "china-t".to_owned()
    } else {
        "china-s".to_owned()
    };

    thread::spawn(move || {
        let stdout_thread = stdout.map(|stream| {
            let app = app_for_thread.clone();
            thread::spawn(move || stream_process_output(stream, app, total_pages))
        });
        let stderr_thread = stderr.map(|stream| {
            let app = app_for_thread.clone();
            thread::spawn(move || stream_process_output(stream, app, total_pages))
        });

        let ocr_status = child.wait();
        if let Some(handle) = stdout_thread {
            let _ = handle.join();
        }
        if let Some(handle) = stderr_thread {
            let _ = handle.join();
        }

        let state_for_thread = app_for_thread.state::<JobState>();
        let mut success = false;
        let mut cancelled = was_cancelled(&state_for_thread);
        let mut message: String;

        match ocr_status {
            Ok(status) if status.success() && stage_for_thread.is_file() && !cancelled => {
                if let Some((python, script)) = optimizer {
                    let _ = app_for_thread.emit(
                        "ocr-log",
                        LogPayload {
                            message: "OCR 已完成，开始生成 Readest 连续朗读文字层。".to_owned(),
                        },
                    );
                    let _ = app_for_thread.emit(
                        "ocr-progress",
                        ProgressPayload {
                            current: 0,
                            total: total_pages,
                            percent: 0.0,
                            stage: "正在准备连续朗读文字层".to_owned(),
                        },
                    );

                    let mut postprocess = Command::new(&python);
                    postprocess
                        .arg(&script)
                        .arg(&stage_for_thread)
                        .arg(&output_for_thread)
                        .arg("--font-size")
                        .arg("3.2")
                        .arg("--font-name")
                        .arg(&reading_font_for_thread)
                        .stdout(Stdio::piped())
                        .stderr(Stdio::piped())
                        .env("PYTHONUNBUFFERED", "1")
                        .env("PATH", enhanced_path());
                    if let Some(sidecar) = &sidecar_for_thread {
                        postprocess.arg("--sidecar").arg(sidecar);
                    }
                    if let Some(text_path) = &text_for_thread {
                        postprocess.arg("--text-output").arg(text_path);
                    }
                    if mode_for_thread == "scan" {
                        postprocess.arg("--visible-source").arg(&input_for_thread);
                        postprocess.arg("--scan-layout");
                        if filter_margins_for_thread {
                            postprocess.arg("--filter-margins");
                        }
                        if drop_diagram_labels_for_thread {
                            postprocess.arg("--drop-diagram-labels");
                        }
                        postprocess.arg("--minimum-readable-characters").arg("6");
                    } else if mode_for_thread != "force" {
                        postprocess.arg("--prefer-pdf-text");
                    }

                    match postprocess.spawn() {
                        Ok(mut postprocess_child) => {
                            let postprocess_pid = postprocess_child.id();
                            if set_running_job(&state_for_thread, postprocess_pid).is_err()
                                || was_cancelled(&state_for_thread)
                            {
                                let _ = postprocess_child.kill();
                            }
                            let post_stdout = postprocess_child.stdout.take();
                            let post_stderr = postprocess_child.stderr.take();
                            let stdout_thread = post_stdout.map(|stream| {
                                let app = app_for_thread.clone();
                                thread::spawn(move || {
                                    stream_process_output(stream, app, total_pages)
                                })
                            });
                            let stderr_thread = post_stderr.map(|stream| {
                                let app = app_for_thread.clone();
                                thread::spawn(move || {
                                    stream_process_output(stream, app, total_pages)
                                })
                            });
                            let post_status = postprocess_child.wait();
                            if let Some(handle) = stdout_thread {
                                let _ = handle.join();
                            }
                            if let Some(handle) = stderr_thread {
                                let _ = handle.join();
                            }
                            cancelled = was_cancelled(&state_for_thread);
                            match post_status {
                                Ok(status)
                                    if status.success()
                                        && output_for_thread.is_file()
                                        && !cancelled =>
                                {
                                    success = true;
                                    message = format!(
                                        "Readest 朗读优化完成：{}",
                                        output_for_thread.display()
                                    );
                                    let _ = fs::remove_file(&stage_for_thread);
                                    if let Some(sidecar) = &sidecar_for_thread {
                                        let _ = fs::remove_file(sidecar);
                                    }
                                }
                                _ if cancelled => {
                                    message = "任务已取消。".to_owned();
                                }
                                Ok(status) => {
                                    let fallback = standard_fallback_path(&output_for_thread);
                                    let preserved = if !fallback.exists()
                                        && fs::rename(&stage_for_thread, &fallback).is_ok()
                                    {
                                        format!("标准 OCR 结果已保留在：{}", fallback.display())
                                    } else {
                                        format!(
                                            "标准 OCR 临时结果位于：{}",
                                            stage_for_thread.display()
                                        )
                                    };
                                    message = format!(
                                        "朗读文字层生成失败，退出状态：{status}。{preserved}"
                                    );
                                }
                                Err(error) => {
                                    message = format!("等待朗读优化器结束时发生错误：{error}");
                                }
                            }
                        }
                        Err(error) => {
                            message = format!("无法启动 Readest 朗读优化器：{error}");
                        }
                    }
                } else {
                    success = output_for_thread.is_file();
                    message = if success {
                        format!("修复完成：{}", output_for_thread.display())
                    } else {
                        "OCRmyPDF 已结束，但输出 PDF 不存在。".to_owned()
                    };
                }
            }
            Ok(_status) if cancelled => {
                message = "任务已取消。未完成的输出文件可能已被自动清理。".to_owned();
            }
            Ok(status) => {
                message = format!("OCRmyPDF 处理失败，退出状态：{status}");
            }
            Err(error) => {
                message = format!("等待 OCRmyPDF 结束时发生错误：{error}");
            }
        }

        if !success {
            if reading_optimized && output_for_thread.exists() {
                let _ = fs::remove_file(&output_for_thread);
            }
            if let Some(sidecar) = &sidecar_for_thread {
                if sidecar != text_for_thread.as_ref().unwrap_or(sidecar) {
                    let _ = fs::remove_file(sidecar);
                }
            }
        }
        clear_running_job(&state_for_thread);

        let _ = app_for_thread.emit(
            "ocr-finished",
            FinishPayload {
                success,
                cancelled,
                output_path: output_for_thread.to_string_lossy().into_owned(),
                text_path: text_for_thread.map(|path| path.to_string_lossy().into_owned()),
                message,
            },
        );
    });

    Ok(())
}

#[tauri::command]
fn cancel_ocr(state: State<'_, JobState>) -> Result<(), String> {
    let pid = {
        let mut guard = state.running.lock().map_err(|_| "无法读取任务状态。")?;
        let Some(job) = guard.as_mut() else {
            return Err("当前没有正在运行的任务。".to_owned());
        };
        job.cancel_requested = true;
        job.pid
    };

    #[cfg(unix)]
    {
        let status = Command::new("kill")
            .arg("-TERM")
            .arg(pid.to_string())
            .status()
            .map_err(|error| format!("无法发送取消信号：{error}"))?;
        if !status.success() {
            return Err("处理进程未接受取消信号。".to_owned());
        }
        Ok(())
    }

    #[cfg(not(unix))]
    {
        let _ = pid;
        Err("当前版本只在 macOS 上支持取消任务。".to_owned())
    }
}

#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    let target = PathBuf::from(path);
    if !target.exists() {
        return Err("文件不存在。".to_owned());
    }
    #[cfg(target_os = "macos")]
    {
        let status = Command::new("open")
            .arg(&target)
            .status()
            .map_err(|error| format!("无法打开文件：{error}"))?;
        if status.success() { Ok(()) } else { Err("系统未能打开文件。".to_owned()) }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = target;
        Err("当前版本仅支持 macOS。".to_owned())
    }
}

#[tauri::command]
fn launch_installer(app: AppHandle) -> Result<(), String> {
    let source = installer_script(&app)
        .ok_or_else(|| "应用中缺少组件安装器。".to_owned())?;
    let destination = env::temp_dir().join("PDF-Text-Repair-Install.command");
    fs::copy(&source, &destination)
        .map_err(|error| format!("无法准备安装器：{error}"))?;
    #[cfg(unix)]
    {
        let mut permissions = fs::metadata(&destination)
            .map_err(|error| format!("无法读取安装器权限：{error}"))?
            .permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&destination, permissions)
            .map_err(|error| format!("无法设置安装器权限：{error}"))?;
    }
    #[cfg(target_os = "macos")]
    {
        let status = Command::new("open")
            .arg(&destination)
            .status()
            .map_err(|error| format!("无法启动安装器：{error}"))?;
        if status.success() { Ok(()) } else { Err("Terminal 未能启动安装器。".to_owned()) }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = destination;
        Err("当前安装器仅支持 macOS。".to_owned())
    }
}

#[tauri::command]
fn reveal_in_finder(path: String) -> Result<(), String> {
    let target = PathBuf::from(path);
    if !target.exists() {
        return Err("输出文件不存在。".to_owned());
    }

    #[cfg(target_os = "macos")]
    {
        let status = Command::new("open")
            .arg("-R")
            .arg(&target)
            .status()
            .map_err(|error| format!("无法打开 Finder：{error}"))?;
        if status.success() {
            Ok(())
        } else {
            Err("Finder 未能显示输出文件。".to_owned())
        }
    }

    #[cfg(not(target_os = "macos"))]
    {
        let _ = target;
        Err("当前版本仅支持在 macOS Finder 中显示文件。".to_owned())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(JobState::default())
        .invoke_handler(tauri::generate_handler![
            check_environment,
            analyze_pdf,
            start_ocr,
            cancel_ocr,
            open_path,
            launch_installer,
            reveal_in_finder
        ])
        .run(tauri::generate_context!())
        .expect("error while running PDF Text Repair");
}
