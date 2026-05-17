//! Portable bundle: full one-click backup + transfer to another PC.
//!
//! A LocalEmailStack portable bundle is a single .zip containing:
//!
//!     bundle/
//!       META.json              — version, created_at, source machine, bundle_id
//!       repo/                  — the entire stack repo (docker/, niches/, scripts/, …)
//!       env/
//!         bootstrap.env        — the configured env file (with secrets — encrypt before mailing!)
//!       volumes/
//!         postgres_data.tar.gz       — exported via docker run busybox tar
//!         n8n_data.tar.gz
//!         twenty_data.tar.gz
//!         minio_data.tar.gz
//!         ollama_models.tar.gz       — large (~25 GB); optional flag to skip
//!         qdrant_data.tar.gz
//!         redis_data.tar.gz
//!         nocodb_data.tar.gz
//!         grafana_data.tar.gz
//!         prometheus_data.tar.gz
//!         loki_data.tar.gz
//!         searxng_data.tar.gz
//!         federation_repo.tar.gz
//!         traefik_certs.tar.gz
//!
//! On the destination PC: install LocalEmailStack.exe → Settings → Import →
//! pick the .zip. The app extracts, restores volumes, points settings at the
//! repo, runs `docker compose up -d`.

use anyhow::{anyhow, Result};
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use walkdir::WalkDir;
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipArchive, ZipWriter};

use crate::docker;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct BundleMeta {
    pub version: String,
    pub created_at: String,
    pub source_machine: String,
    pub bundle_id: String,
    pub includes_models: bool,
    pub volumes: Vec<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ExportOptions {
    pub include_models: bool,        // bloats by ~25 GB if true
    pub include_volumes: Vec<String>, // empty = all known volumes
    pub destination_zip: String,     // absolute path where to write
}

pub const DEFAULT_VOLUMES: &[&str] = &[
    "local-email-stack_postgres_data",
    "local-email-stack_n8n_data",
    "local-email-stack_twenty_data",
    "local-email-stack_minio_data",
    "local-email-stack_qdrant_data",
    "local-email-stack_redis_data",
    "local-email-stack_nocodb_data",
    "local-email-stack_grafana_data",
    "local-email-stack_prometheus_data",
    "local-email-stack_loki_data",
    "local-email-stack_searxng_data",
    "local-email-stack_federation_repo",
    "local-email-stack_traefik_certs",
];

pub const MODEL_VOLUMES: &[&str] = &[
    "local-email-stack_ollama_models",
];

pub async fn export_bundle(
    repo_path: &Path,
    work_dir: &Path,
    opts: &ExportOptions,
) -> Result<PathBuf> {
    tokio::fs::create_dir_all(work_dir).await?;
    let bundle_dir = work_dir.join("bundle");
    let _ = tokio::fs::remove_dir_all(&bundle_dir).await;
    tokio::fs::create_dir_all(&bundle_dir).await?;
    tokio::fs::create_dir_all(bundle_dir.join("repo")).await?;
    tokio::fs::create_dir_all(bundle_dir.join("env")).await?;
    tokio::fs::create_dir_all(bundle_dir.join("volumes")).await?;

    // 1. Copy repo (everything except .git + node_modules + target + caches)
    let exclude = ["target", "node_modules", ".git", "dist", "build", "__pycache__"];
    copy_dir_filtered(repo_path, &bundle_dir.join("repo"), &exclude).await?;

    // 2. Copy bootstrap.env if it exists
    let env_path = repo_path.join("bootstrap.env");
    if env_path.exists() {
        tokio::fs::copy(&env_path, bundle_dir.join("env").join("bootstrap.env")).await?;
    }

    // 3. Export Docker volumes
    let mut chosen: Vec<String> = if opts.include_volumes.is_empty() {
        DEFAULT_VOLUMES.iter().map(|s| s.to_string()).collect()
    } else {
        opts.include_volumes.clone()
    };
    if opts.include_models {
        chosen.extend(MODEL_VOLUMES.iter().map(|s| s.to_string()));
    }
    let existing = docker::volume_list().await?;
    let chosen: Vec<String> = chosen
        .into_iter()
        .filter(|v| existing.iter().any(|e| e == v))
        .collect();
    for v in &chosen {
        let target = bundle_dir.join("volumes").join(format!("{v}.tar.gz"));
        tracing::info!("exporting volume {v}");
        docker::volume_export(v, &target).await?;
    }

    // 4. META.json
    let meta = BundleMeta {
        version: env!("CARGO_PKG_VERSION").to_string(),
        created_at: Utc::now().to_rfc3339(),
        source_machine: hostname().unwrap_or_else(|| "unknown".into()),
        bundle_id: format!("les-{}", Utc::now().timestamp()),
        includes_models: opts.include_models,
        volumes: chosen.clone(),
    };
    let meta_json = serde_json::to_string_pretty(&meta)?;
    tokio::fs::write(bundle_dir.join("META.json"), meta_json).await?;

    // 5. Zip the bundle dir
    let final_zip = PathBuf::from(&opts.destination_zip);
    zip_directory(&bundle_dir, &final_zip)?;

    // Clean up working dir
    let _ = tokio::fs::remove_dir_all(&bundle_dir).await;
    Ok(final_zip)
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ImportOptions {
    pub source_zip: String,
    pub target_repo: String,
    pub restore_models: bool,
}

pub async fn import_bundle(opts: &ImportOptions, work_dir: &Path) -> Result<BundleMeta> {
    tokio::fs::create_dir_all(work_dir).await?;
    let extract_dir = work_dir.join("import");
    let _ = tokio::fs::remove_dir_all(&extract_dir).await;
    tokio::fs::create_dir_all(&extract_dir).await?;

    // 1. Unzip
    unzip_to(Path::new(&opts.source_zip), &extract_dir)?;

    // 2. Read META.json
    let meta: BundleMeta = serde_json::from_str(
        &tokio::fs::read_to_string(extract_dir.join("META.json")).await?
    )?;

    // 3. Restore repo
    let target_repo = PathBuf::from(&opts.target_repo);
    tokio::fs::create_dir_all(&target_repo).await?;
    copy_dir_filtered(&extract_dir.join("repo"), &target_repo, &[]).await?;

    // 4. Restore bootstrap.env
    let env_src = extract_dir.join("env").join("bootstrap.env");
    if env_src.exists() {
        tokio::fs::copy(&env_src, target_repo.join("bootstrap.env")).await?;
    }

    // 5. Restore volumes
    for v in &meta.volumes {
        if !opts.restore_models && MODEL_VOLUMES.contains(&v.as_str()) {
            continue;
        }
        let tarball = extract_dir.join("volumes").join(format!("{v}.tar.gz"));
        if tarball.exists() {
            tracing::info!("restoring volume {v}");
            docker::volume_import(v, &tarball).await?;
        }
    }

    let _ = tokio::fs::remove_dir_all(&extract_dir).await;
    Ok(meta)
}

// ─── Helpers ──────────────────────────────────────────────────────────────

fn hostname() -> Option<String> {
    if let Ok(h) = std::env::var("COMPUTERNAME") { return Some(h); }
    if let Ok(h) = std::env::var("HOSTNAME") { return Some(h); }
    None
}

async fn copy_dir_filtered(src: &Path, dst: &Path, exclude: &[&str]) -> Result<()> {
    let src = src.to_path_buf();
    let dst = dst.to_path_buf();
    let exclude: Vec<String> = exclude.iter().map(|s| s.to_string()).collect();
    tokio::task::spawn_blocking(move || -> Result<()> {
        for entry in WalkDir::new(&src) {
            let entry = entry?;
            let rel = entry.path().strip_prefix(&src)?;
            if rel.components().any(|c| {
                let s = c.as_os_str().to_string_lossy();
                exclude.iter().any(|e| e == s.as_ref())
            }) {
                continue;
            }
            let target = dst.join(rel);
            if entry.file_type().is_dir() {
                std::fs::create_dir_all(&target)?;
            } else if entry.file_type().is_file() {
                if let Some(p) = target.parent() {
                    std::fs::create_dir_all(p)?;
                }
                std::fs::copy(entry.path(), &target)?;
            }
        }
        Ok(())
    })
    .await??;
    Ok(())
}

fn zip_directory(src: &Path, dst: &Path) -> Result<()> {
    let file = File::create(dst)?;
    let mut zip = ZipWriter::new(file);
    let opts = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
    for entry in WalkDir::new(src) {
        let entry = entry?;
        let path = entry.path();
        let name = path.strip_prefix(src)?.to_string_lossy().replace('\\', "/");
        if path.is_dir() {
            if !name.is_empty() {
                zip.add_directory(format!("{name}/"), opts)?;
            }
            continue;
        }
        zip.start_file(name, opts)?;
        let mut f = File::open(path)?;
        let mut buf = Vec::new();
        f.read_to_end(&mut buf)?;
        zip.write_all(&buf)?;
    }
    zip.finish()?;
    Ok(())
}

fn unzip_to(src_zip: &Path, dst: &Path) -> Result<()> {
    let file = File::open(src_zip)?;
    let mut archive = ZipArchive::new(file)?;
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i)?;
        let outpath = match entry.enclosed_name() {
            Some(p) => dst.join(p),
            None => continue,
        };
        if entry.is_dir() {
            std::fs::create_dir_all(&outpath)?;
        } else {
            if let Some(p) = outpath.parent() {
                std::fs::create_dir_all(p)?;
            }
            let mut out = File::create(&outpath)?;
            std::io::copy(&mut entry, &mut out)?;
        }
    }
    Ok(())
}
