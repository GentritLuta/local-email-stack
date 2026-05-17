//! Filesystem layout.
//!
//! The desktop app needs to find the stack repo (docker-compose lives there)
//! and an app-data dir (config, logs, portable bundles). On first run we
//! prompt the user for the repo path; subsequent runs read it from settings.

use std::path::PathBuf;
use anyhow::{anyhow, Result};
use tauri::{AppHandle, Manager};

pub const SETTINGS_KEY_REPO: &str = "stack_repo_path";

pub fn app_data_dir(app: &AppHandle) -> Result<PathBuf> {
    app.path()
        .app_data_dir()
        .map_err(|e| anyhow!("no app data dir: {e}"))
}

pub fn portable_dir(app: &AppHandle) -> Result<PathBuf> {
    let mut p = app_data_dir(app)?;
    p.push("portable");
    Ok(p)
}

pub async fn ensure_app_dir(app: &AppHandle) -> Result<()> {
    let d = app_data_dir(app)?;
    tokio::fs::create_dir_all(&d).await?;
    Ok(())
}

/// Resolve the path to the stack repo (where docker-compose.yml lives).
/// Order of precedence:
///   1. Settings store key `stack_repo_path`
///   2. Env var `LES_REPO`
///   3. Two reasonable defaults relative to the exe (when shipped as a
///      portable bundle alongside the repo).
pub fn stack_repo_path(app: &AppHandle) -> Result<PathBuf> {
    if let Ok(env) = std::env::var("LES_REPO") {
        return Ok(PathBuf::from(env));
    }
    // Try a sibling 'stack' directory next to the exe — the portable layout.
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            let candidate = parent.join("stack");
            if candidate.join("docker").join("docker-compose.yml").exists() {
                return Ok(candidate);
            }
            // Or the repo itself, if exe ships inside it during dev
            let dev_candidate = parent.join("..").join("..").join("..");
            if dev_candidate.join("docker").join("docker-compose.yml").exists() {
                return Ok(dev_candidate.canonicalize()?);
            }
        }
    }
    Err(anyhow!(
        "stack repo path unset — open Settings → Stack repo path, or set LES_REPO env var"
    ))
}

pub fn compose_dir(app: &AppHandle) -> Result<PathBuf> {
    let mut p = stack_repo_path(app)?;
    p.push("docker");
    Ok(p)
}

pub fn niches_dir(app: &AppHandle) -> Result<PathBuf> {
    let mut p = stack_repo_path(app)?;
    p.push("niches");
    Ok(p)
}

pub fn personas_path(app: &AppHandle) -> Result<PathBuf> {
    let mut p = stack_repo_path(app)?;
    p.push("docker");
    p.push("persona-engine");
    p.push("personas.yaml");
    Ok(p)
}

pub fn bootstrap_env_path(app: &AppHandle) -> Result<PathBuf> {
    let mut p = stack_repo_path(app)?;
    p.push("bootstrap.env");
    Ok(p)
}
