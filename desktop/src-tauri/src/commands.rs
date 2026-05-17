//! Tauri commands — the JS-facing surface.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::sync::Mutex;
use tauri::{AppHandle, Emitter, State, Manager};

use crate::{docker, paths, portable, stats};

type Tauri<R> = std::result::Result<R, String>;
fn map<E: std::fmt::Display>(e: E) -> String { format!("{e}") }

// ─── Stack lifecycle ───────────────────────────────────────────────────────

#[tauri::command]
pub async fn stack_status(app: AppHandle) -> Tauri<Vec<docker::ServiceStatus>> {
    let dir = paths::compose_dir(&app).map_err(map)?;
    docker::compose_ps(&dir).await.map_err(map)
}

#[tauri::command]
pub async fn stack_up(app: AppHandle) -> Tauri<String> {
    let dir = paths::compose_dir(&app).map_err(map)?;
    docker::compose_up(&dir).await.map_err(map)
}

#[tauri::command]
pub async fn stack_down(app: AppHandle) -> Tauri<String> {
    let dir = paths::compose_dir(&app).map_err(map)?;
    docker::compose_down(&dir).await.map_err(map)
}

#[tauri::command]
pub async fn stack_restart_service(app: AppHandle, service: String) -> Tauri<()> {
    let dir = paths::compose_dir(&app).map_err(map)?;
    docker::compose_restart(&dir, &service).await.map_err(map)
}

// ─── Log streaming ─────────────────────────────────────────────────────────

#[derive(Default)]
pub struct LogStreams(Mutex<std::collections::HashMap<String, tokio::process::Child>>);

#[tauri::command]
pub async fn stream_logs(app: AppHandle, container: String, stream_id: String) -> Tauri<()> {
    let mut child = docker::spawn_log_tail(&container).map_err(map)?;
    let stdout = child.stdout.take().ok_or_else(|| "no stdout".to_string())?;
    let stderr = child.stderr.take().ok_or_else(|| "no stderr".to_string())?;

    let stream_event = format!("logs:{stream_id}");
    let stream_event_err = stream_event.clone();
    let app_clone = app.clone();
    tokio::spawn(async move {
        let mut reader = BufReader::new(stdout).lines();
        while let Ok(Some(line)) = reader.next_line().await {
            let _ = app_clone.emit(&stream_event, line);
        }
    });
    let app_clone = app.clone();
    tokio::spawn(async move {
        let mut reader = BufReader::new(stderr).lines();
        while let Ok(Some(line)) = reader.next_line().await {
            let _ = app_clone.emit(&stream_event_err, format!("[stderr] {line}"));
        }
    });

    // Track child so we can kill it later
    let state: State<'_, LogStreams> = app.state();
    let mut map = state.0.lock().await;
    map.insert(stream_id, child);
    Ok(())
}

#[tauri::command]
pub async fn stop_log_stream(app: AppHandle, stream_id: String) -> Tauri<()> {
    let state: State<'_, LogStreams> = app.state();
    let mut map = state.0.lock().await;
    if let Some(mut child) = map.remove(&stream_id) {
        let _ = child.kill().await;
    }
    Ok(())
}

// ─── Dashboard / metrics ───────────────────────────────────────────────────

fn pg_dsn(app: &AppHandle) -> Result<String> {
    // Read DSN from bootstrap.env; default to the compose-internal hostname,
    // which only works if the desktop app reaches Docker via a port mapping —
    // for that, the compose Postgres must publish 5432 on the host. We default
    // to localhost:5432; user can override via Settings.
    let env_path = paths::bootstrap_env_path(app)?;
    if env_path.exists() {
        let body = std::fs::read_to_string(&env_path)?;
        let mut user = "stackadmin".to_string();
        let mut pass = String::new();
        for line in body.lines() {
            if let Some((k, v)) = line.split_once('=') {
                match k.trim() {
                    "POSTGRES_USER"     => user = v.trim().to_string(),
                    "POSTGRES_PASSWORD" => pass = v.trim().to_string(),
                    _ => {}
                }
            }
        }
        return Ok(format!("postgres://{user}:{pass}@127.0.0.1:5432/leads"));
    }
    Ok("postgres://stackadmin:devpw@127.0.0.1:5432/leads".to_string())
}

#[tauri::command]
pub async fn dashboard_metrics(app: AppHandle) -> Tauri<stats::DashboardMetrics> {
    let dsn = pg_dsn(&app).map_err(map)?;
    let mut m = stats::dashboard(&dsn).await.map_err(map)?;
    if let Ok(services) = docker::compose_ps(&paths::compose_dir(&app).map_err(map)?).await {
        m.services_total = services.len() as i32;
        m.services_healthy = services.iter()
            .filter(|s| s.state == "running" && s.health.as_deref().unwrap_or("none") != "unhealthy")
            .count() as i32;
    }
    Ok(m)
}

#[tauri::command]
pub async fn pipeline_snapshot(app: AppHandle) -> Tauri<stats::PipelineSnapshot> {
    let dsn = pg_dsn(&app).map_err(map)?;
    stats::pipeline(&dsn).await.map_err(map)
}

#[tauri::command]
pub async fn warmup_health(app: AppHandle) -> Tauri<stats::WarmupHealth> {
    let dsn = pg_dsn(&app).map_err(map)?;
    stats::warmup(&dsn).await.map_err(map)
}

#[tauri::command]
pub async fn bandit_leaderboard(app: AppHandle, limit: Option<i64>) -> Tauri<Vec<stats::BanditRow>> {
    let dsn = pg_dsn(&app).map_err(map)?;
    stats::bandit_top(&dsn, limit.unwrap_or(30)).await.map_err(map)
}

#[tauri::command]
pub async fn replies_recent(app: AppHandle, limit: Option<i64>) -> Tauri<Vec<stats::InboundReply>> {
    let dsn = pg_dsn(&app).map_err(map)?;
    stats::replies(&dsn, limit.unwrap_or(100)).await.map_err(map)
}

// ─── Niches ────────────────────────────────────────────────────────────────

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct NicheSummary {
    pub slug: String,
    pub name: String,
    pub engines: Vec<String>,
    pub path: String,
}

#[tauri::command]
pub async fn niches_list(app: AppHandle) -> Tauri<Vec<NicheSummary>> {
    let dir = paths::niches_dir(&app).map_err(map)?;
    let mut out = Vec::new();
    if let Ok(mut rd) = tokio::fs::read_dir(&dir).await {
        while let Ok(Some(entry)) = rd.next_entry().await {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("yaml") {
                continue;
            }
            let body = tokio::fs::read_to_string(&path).await.unwrap_or_default();
            // Parse minimally with serde_yaml-like approach via serde_json hack
            // We'll just regex out the fields we need for the list view.
            let slug = extract_yaml_string(&body, "slug").unwrap_or_else(|| {
                path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default()
            });
            let name = extract_yaml_string(&body, "name").unwrap_or_default();
            let engines = extract_yaml_engines(&body);
            out.push(NicheSummary {
                slug,
                name,
                engines,
                path: path.to_string_lossy().into_owned(),
            });
        }
    }
    Ok(out)
}

#[tauri::command]
pub async fn niche_get(path: String) -> Tauri<String> {
    tokio::fs::read_to_string(&path).await.map_err(map)
}

#[tauri::command]
pub async fn niche_save(path: String, content: String) -> Tauri<()> {
    if let Some(parent) = Path::new(&path).parent() {
        tokio::fs::create_dir_all(parent).await.map_err(map)?;
    }
    tokio::fs::write(&path, content).await.map_err(map)?;
    Ok(())
}

#[tauri::command]
pub async fn niche_delete(path: String) -> Tauri<()> {
    tokio::fs::remove_file(&path).await.map_err(map)?;
    Ok(())
}

#[tauri::command]
pub async fn niche_reload_service() -> Tauri<()> {
    let client = reqwest::Client::new();
    client.post("http://127.0.0.1:8000/niches/reload")
        .send().await.map_err(map)?;
    Ok(())
}

fn extract_yaml_string(body: &str, key: &str) -> Option<String> {
    for line in body.lines() {
        let trim = line.trim_start();
        if let Some(rest) = trim.strip_prefix(&format!("{key}:")) {
            return Some(rest.trim().trim_matches('"').trim_matches('\'').to_string());
        }
    }
    None
}

fn extract_yaml_engines(body: &str) -> Vec<String> {
    body.lines()
        .filter_map(|l| {
            let t = l.trim_start();
            if let Some(rest) = t.strip_prefix("- engine:") {
                Some(rest.trim().to_string())
            } else { None }
        })
        .collect()
}

// ─── Personas ──────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn personas_get(app: AppHandle) -> Tauri<String> {
    let path = paths::personas_path(&app).map_err(map)?;
    tokio::fs::read_to_string(&path).await.map_err(map)
}

#[tauri::command]
pub async fn personas_save(app: AppHandle, content: String) -> Tauri<()> {
    let path = paths::personas_path(&app).map_err(map)?;
    tokio::fs::write(&path, content).await.map_err(map)?;
    Ok(())
}

// ─── bootstrap.env editor ──────────────────────────────────────────────────

#[tauri::command]
pub async fn env_get(app: AppHandle) -> Tauri<String> {
    let path = paths::bootstrap_env_path(&app).map_err(map)?;
    if path.exists() {
        tokio::fs::read_to_string(&path).await.map_err(map)
    } else {
        Ok(String::new())
    }
}

#[tauri::command]
pub async fn env_set(app: AppHandle, content: String) -> Tauri<()> {
    let path = paths::bootstrap_env_path(&app).map_err(map)?;
    tokio::fs::write(&path, content).await.map_err(map)?;
    Ok(())
}

// ─── Portable export / import ──────────────────────────────────────────────

#[tauri::command]
pub async fn portable_export(
    app: AppHandle,
    destination_zip: String,
    include_models: bool,
) -> Tauri<String> {
    let repo = paths::stack_repo_path(&app).map_err(map)?;
    let work = paths::portable_dir(&app).map_err(map)?;
    let opts = portable::ExportOptions {
        include_models,
        include_volumes: Vec::new(),
        destination_zip,
    };
    let path = portable::export_bundle(&repo, &work, &opts).await.map_err(map)?;
    Ok(path.to_string_lossy().into_owned())
}

#[tauri::command]
pub async fn portable_import(
    app: AppHandle,
    source_zip: String,
    target_repo: String,
    restore_models: bool,
) -> Tauri<portable::BundleMeta> {
    let work = paths::portable_dir(&app).map_err(map)?;
    let opts = portable::ImportOptions {
        source_zip,
        target_repo,
        restore_models,
    };
    portable::import_bundle(&opts, &work).await.map_err(map)
}

// ─── App settings ──────────────────────────────────────────────────────────

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct AppSettings {
    pub stack_repo_path: Option<String>,
    pub pg_dsn_override: Option<String>,
    pub n8n_url: Option<String>,
    pub auto_start_stack: bool,
}

#[tauri::command]
pub async fn settings_get(app: AppHandle) -> Tauri<AppSettings> {
    let dir = paths::app_data_dir(&app).map_err(map)?;
    let path = dir.join("settings.json");
    if path.exists() {
        let body = tokio::fs::read_to_string(&path).await.map_err(map)?;
        let s: AppSettings = serde_json::from_str(&body).unwrap_or_default();
        Ok(s)
    } else {
        Ok(AppSettings::default())
    }
}

#[tauri::command]
pub async fn settings_set(app: AppHandle, settings: AppSettings) -> Tauri<()> {
    let dir = paths::app_data_dir(&app).map_err(map)?;
    tokio::fs::create_dir_all(&dir).await.map_err(map)?;
    let path = dir.join("settings.json");
    let body = serde_json::to_string_pretty(&settings).map_err(map)?;
    tokio::fs::write(&path, body).await.map_err(map)?;
    Ok(())
}

#[tauri::command]
pub async fn detect_first_run(app: AppHandle) -> Tauri<bool> {
    let dir = paths::app_data_dir(&app).map_err(map)?;
    Ok(!dir.join("settings.json").exists())
}

// ─── Misc ──────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn open_in_browser(url: String) -> Tauri<()> {
    if let Err(e) = open::that(&url) { return Err(format!("{e}")); }
    Ok(())
}

#[tauri::command]
pub async fn run_smoke_test(app: AppHandle) -> Tauri<Vec<(String, bool, String)>> {
    let services = [
        ("n8n",          "http://127.0.0.1:5678/healthz"),
        ("ollama",       "http://127.0.0.1:11434/api/tags"),
        ("litellm",      "http://127.0.0.1:4000/health"),
        ("searxng",      "http://127.0.0.1:8080/healthz"),
        ("scraper",      "http://127.0.0.1:8081/healthz"),
        ("email-finder", "http://127.0.0.1:8082/healthz"),
        ("route-picker", "http://127.0.0.1:8083/healthz"),
        ("bandit-scorer","http://127.0.0.1:8084/healthz"),
        ("persona-engine","http://127.0.0.1:8085/healthz"),
        ("sourcing",     "http://127.0.0.1:8086/healthz"),
        ("enricher",     "http://127.0.0.1:8087/healthz"),
    ];
    let mut out = Vec::new();
    for (name, url) in services {
        let ok = stats::probe_health(url).await;
        out.push((name.to_string(), ok, url.to_string()));
    }
    Ok(out)
}
