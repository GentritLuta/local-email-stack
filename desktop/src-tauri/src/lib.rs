//! LocalEmailStack — desktop control panel.
//!
//! Tauri app that exposes commands the React frontend calls:
//!
//! - `stack_status()`         — `docker compose ps` summary per service
//! - `stack_up()` / `stack_down()` — lifecycle
//! - `stream_logs(service)`   — tails `docker logs --follow` over an event channel
//! - `dashboard_metrics()`    — top-level KPIs (pulls Postgres + service /healthz)
//! - `niches_list/save`       — niches/*.yaml CRUD
//! - `personas_list/save`     — docker/persona-engine/personas.yaml CRUD
//! - `env_get/set`            — bootstrap.env editor
//! - `replies_recent()`       — recent CF Worker inbound
//! - `portable_export/import` — backup + transfer-to-another-PC

mod commands;
mod docker;
mod stats;
mod portable;
mod paths;

use tauri::{Manager, RunEvent};
use tracing::{info, level_filters::LevelFilter};
use tracing_subscriber::{prelude::*, EnvFilter};

pub fn run() {
    init_logging();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .invoke_handler(tauri::generate_handler![
            commands::stack_status,
            commands::stack_up,
            commands::stack_down,
            commands::stack_restart_service,
            commands::stream_logs,
            commands::stop_log_stream,
            commands::dashboard_metrics,
            commands::pipeline_snapshot,
            commands::warmup_health,
            commands::bandit_leaderboard,
            commands::niches_list,
            commands::niche_get,
            commands::niche_save,
            commands::niche_delete,
            commands::niche_reload_service,
            commands::personas_get,
            commands::personas_save,
            commands::env_get,
            commands::env_set,
            commands::replies_recent,
            commands::portable_export,
            commands::portable_import,
            commands::settings_get,
            commands::settings_set,
            commands::open_in_browser,
            commands::detect_first_run,
            commands::run_smoke_test,
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            // On boot, ensure the stack is at least visible — but don't force-start.
            tauri::async_runtime::spawn(async move {
                if let Err(e) = paths::ensure_app_dir(&handle).await {
                    tracing::warn!("ensure_app_dir failed: {e}");
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, event| match event {
            RunEvent::ExitRequested { .. } => {
                info!("LocalEmailStack exit requested");
            }
            _ => {}
        });
}

fn init_logging() {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::default().add_directive(LevelFilter::INFO.into()));
    tracing_subscriber::registry()
        .with(filter)
        .with(tracing_subscriber::fmt::layer().compact())
        .init();
}
