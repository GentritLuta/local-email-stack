//! Wrapper around the local `docker` and `docker compose` CLIs.

use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};
use std::path::Path;
use tokio::process::Command;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ServiceStatus {
    pub name: String,
    pub state: String,           // running | exited | restarting | created | dead
    pub health: Option<String>,  // healthy | unhealthy | starting | none
    pub uptime: Option<String>,
    pub image: Option<String>,
}

pub async fn compose_ps(compose_dir: &Path) -> Result<Vec<ServiceStatus>> {
    let out = Command::new("docker")
        .args(["compose", "ps", "--format", "json"])
        .current_dir(compose_dir)
        .output()
        .await?;
    if !out.status.success() {
        return Err(anyhow!(
            "docker compose ps failed: {}",
            String::from_utf8_lossy(&out.stderr)
        ));
    }
    let body = String::from_utf8_lossy(&out.stdout);
    let mut services = Vec::new();
    // Compose emits NDJSON when --format json
    for line in body.lines().filter(|l| !l.trim().is_empty()) {
        match serde_json::from_str::<serde_json::Value>(line) {
            Ok(v) => services.push(ServiceStatus {
                name: v.get("Name").and_then(|x| x.as_str()).unwrap_or("?").to_string(),
                state: v.get("State").and_then(|x| x.as_str()).unwrap_or("?").to_string(),
                health: v.get("Health").and_then(|x| x.as_str()).map(String::from),
                uptime: v.get("RunningFor").and_then(|x| x.as_str()).map(String::from),
                image: v.get("Image").and_then(|x| x.as_str()).map(String::from),
            }),
            Err(_) => {}
        }
    }
    Ok(services)
}

pub async fn compose_up(compose_dir: &Path) -> Result<String> {
    let out = Command::new("docker")
        .args(["compose", "up", "-d", "--remove-orphans"])
        .current_dir(compose_dir)
        .output()
        .await?;
    if !out.status.success() {
        return Err(anyhow!(
            "docker compose up failed: {}",
            String::from_utf8_lossy(&out.stderr)
        ));
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

pub async fn compose_down(compose_dir: &Path) -> Result<String> {
    let out = Command::new("docker")
        .args(["compose", "down"])
        .current_dir(compose_dir)
        .output()
        .await?;
    if !out.status.success() {
        return Err(anyhow!(
            "docker compose down failed: {}",
            String::from_utf8_lossy(&out.stderr)
        ));
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

pub async fn compose_restart(compose_dir: &Path, service: &str) -> Result<()> {
    let out = Command::new("docker")
        .args(["compose", "restart", service])
        .current_dir(compose_dir)
        .output()
        .await?;
    if !out.status.success() {
        return Err(anyhow!(
            "docker compose restart {service} failed: {}",
            String::from_utf8_lossy(&out.stderr)
        ));
    }
    Ok(())
}

/// Spawn `docker logs --follow` for a container and return the child + a stream
/// of stdout lines. The caller listens on the stream via the event channel.
pub fn spawn_log_tail(container: &str) -> Result<tokio::process::Child> {
    let child = Command::new("docker")
        .args(["logs", "--follow", "--tail", "200", "--timestamps", container])
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()?;
    Ok(child)
}

pub async fn volume_list() -> Result<Vec<String>> {
    let out = Command::new("docker")
        .args(["volume", "ls", "--format", "{{.Name}}"])
        .output()
        .await?;
    if !out.status.success() {
        return Err(anyhow!("docker volume ls failed: {}", String::from_utf8_lossy(&out.stderr)));
    }
    Ok(String::from_utf8_lossy(&out.stdout)
        .lines()
        .map(String::from)
        .collect())
}

pub async fn volume_export(volume: &str, target_path: &Path) -> Result<()> {
    // Mount the named volume into a busybox container and tar its contents out.
    let target_dir = target_path.parent().ok_or_else(|| anyhow!("no parent"))?;
    let target_name = target_path
        .file_name()
        .ok_or_else(|| anyhow!("no filename"))?
        .to_string_lossy()
        .to_string();
    let bind = format!("{}:/backup", target_dir.to_string_lossy());
    let out = Command::new("docker")
        .args([
            "run", "--rm",
            "-v", &format!("{volume}:/data:ro"),
            "-v", &bind,
            "busybox",
            "tar", "czf", &format!("/backup/{target_name}"), "-C", "/data", ".",
        ])
        .output()
        .await?;
    if !out.status.success() {
        return Err(anyhow!("volume export {volume} failed: {}", String::from_utf8_lossy(&out.stderr)));
    }
    Ok(())
}

pub async fn volume_import(volume: &str, source_path: &Path) -> Result<()> {
    let source_dir = source_path.parent().ok_or_else(|| anyhow!("no parent"))?;
    let source_name = source_path
        .file_name()
        .ok_or_else(|| anyhow!("no filename"))?
        .to_string_lossy()
        .to_string();
    let bind = format!("{}:/backup:ro", source_dir.to_string_lossy());
    // Ensure volume exists
    let _ = Command::new("docker")
        .args(["volume", "create", volume])
        .output()
        .await?;
    let out = Command::new("docker")
        .args([
            "run", "--rm",
            "-v", &format!("{volume}:/data"),
            "-v", &bind,
            "busybox",
            "sh", "-c", &format!("rm -rf /data/* && tar xzf /backup/{source_name} -C /data"),
        ])
        .output()
        .await?;
    if !out.status.success() {
        return Err(anyhow!("volume import {volume} failed: {}", String::from_utf8_lossy(&out.stderr)));
    }
    Ok(())
}
