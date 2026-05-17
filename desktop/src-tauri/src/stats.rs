//! Dashboard statistics — queries Postgres + service /healthz endpoints.

use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tokio_postgres::NoTls;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct DashboardMetrics {
    pub leads_raw_total: i64,
    pub leads_enriched_total: i64,
    pub leads_verified_total: i64,
    pub leads_queued: i64,
    pub leads_sent_today: i64,
    pub replies_today: i64,
    pub bounces_today: i64,
    pub avg_reply_rate_7d: f64,
    pub active_personas: i64,
    pub active_niches: i64,
    pub last_sent_at: Option<String>,
    pub warmup_spam_rate_7d: f64,
    pub services_healthy: i32,
    pub services_total: i32,
}

pub async fn dashboard(pg_dsn: &str) -> Result<DashboardMetrics> {
    let (client, conn) = tokio_postgres::connect(pg_dsn, NoTls).await?;
    let handle = tokio::spawn(async move {
        if let Err(e) = conn.await {
            tracing::warn!("pg conn dropped: {e}");
        }
    });

    let leads_raw_total: i64 = client
        .query_one("SELECT COUNT(*)::BIGINT FROM leads_raw", &[])
        .await
        .map(|r| r.get(0))
        .unwrap_or(0);
    let leads_enriched_total: i64 = client
        .query_one("SELECT COUNT(*)::BIGINT FROM leads_enriched", &[])
        .await
        .map(|r| r.get(0))
        .unwrap_or(0);
    let leads_verified_total: i64 = client
        .query_one(
            "SELECT COUNT(*)::BIGINT FROM leads_enriched WHERE profile->>'email_verified'='true'",
            &[],
        )
        .await
        .map(|r| r.get(0))
        .unwrap_or(0);

    let leads_queued: i64 = client
        .query_one(
            "SELECT COUNT(*)::BIGINT FROM outbound_messages WHERE status='queued'",
            &[],
        )
        .await
        .map(|r| r.get(0))
        .unwrap_or(0);

    let leads_sent_today: i64 = client
        .query_one(
            "SELECT COUNT(*)::BIGINT FROM outbound_messages
             WHERE status='sent' AND sent_at >= CURRENT_DATE",
            &[],
        )
        .await
        .map(|r| r.get(0))
        .unwrap_or(0);

    let replies_today: i64 = client
        .query_one(
            "SELECT COUNT(*)::BIGINT FROM outbound_messages
             WHERE status='replied' AND replied_at >= CURRENT_DATE",
            &[],
        )
        .await
        .map(|r| r.get(0))
        .unwrap_or(0);

    let bounces_today: i64 = client
        .query_one(
            "SELECT COUNT(*)::BIGINT FROM suppression_list
             WHERE added_at >= CURRENT_DATE AND reason LIKE 'bounce%'",
            &[],
        )
        .await
        .map(|r| r.get(0))
        .unwrap_or(0);

    let avg_reply_rate_7d: f64 = client
        .query_one(
            "SELECT COALESCE(SUM(CASE WHEN status='replied' THEN 1 ELSE 0 END)::FLOAT8
                  / NULLIF(COUNT(*), 0), 0) FROM outbound_messages
              WHERE sent_at >= NOW() - INTERVAL '7 days'",
            &[],
        )
        .await
        .map(|r| r.get(0))
        .unwrap_or(0.0);

    let active_personas: i64 = client
        .query_one(
            "SELECT COUNT(DISTINCT persona)::BIGINT FROM variants WHERE enabled",
            &[],
        )
        .await
        .map(|r| r.get(0))
        .unwrap_or(0);

    let active_niches: i64 = client
        .query_one(
            "SELECT COUNT(DISTINCT niche_slug)::BIGINT FROM leads_raw",
            &[],
        )
        .await
        .map(|r| r.get(0))
        .unwrap_or(0);

    let last_sent_at: Option<String> = client
        .query_opt(
            "SELECT to_char(MAX(sent_at), 'YYYY-MM-DD HH24:MI:SS') FROM outbound_messages WHERE status='sent'",
            &[],
        )
        .await
        .ok()
        .flatten()
        .map(|r| r.get::<_, Option<String>>(0))
        .flatten();

    let warmup_spam_rate_7d: f64 = client
        .query_one(
            "SELECT COALESCE(SUM(CASE WHEN was_spam THEN 1 ELSE 0 END)::FLOAT8
                  / NULLIF(COUNT(*), 0), 0)
             FROM warmup_log
             WHERE event='received' AND created_at >= NOW() - INTERVAL '7 days'",
            &[],
        )
        .await
        .map(|r| r.get(0))
        .unwrap_or(0.0);

    handle.abort();

    Ok(DashboardMetrics {
        leads_raw_total,
        leads_enriched_total,
        leads_verified_total,
        leads_queued,
        leads_sent_today,
        replies_today,
        bounces_today,
        avg_reply_rate_7d,
        active_personas,
        active_niches,
        last_sent_at,
        warmup_spam_rate_7d,
        services_healthy: 0,   // filled in by command after compose ps
        services_total: 0,
    })
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct PipelineSnapshot {
    pub by_stage: Vec<StageBucket>,
    pub recent_leads: Vec<LeadSummary>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct StageBucket {
    pub stage: String,    // sourced | enriched | verified | queued | sent | replied | bounced
    pub count: i64,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct LeadSummary {
    pub id: String,
    pub source: String,
    pub display_name: String,
    pub niche_slug: String,
    pub stage: String,
    pub last_event_at: Option<String>,
}

pub async fn pipeline(pg_dsn: &str) -> Result<PipelineSnapshot> {
    let (client, conn) = tokio_postgres::connect(pg_dsn, NoTls).await?;
    let handle = tokio::spawn(async move { let _ = conn.await; });

    let rows = client
        .query(
            "WITH s AS (
               SELECT 'sourced'   AS stage, COUNT(*)::BIGINT AS n FROM leads_raw
               UNION ALL
               SELECT 'enriched',  COUNT(*)::BIGINT FROM leads_enriched
               UNION ALL
               SELECT 'queued',    COUNT(*)::BIGINT FROM outbound_messages WHERE status='queued'
               UNION ALL
               SELECT 'sent',      COUNT(*)::BIGINT FROM outbound_messages WHERE status='sent'
               UNION ALL
               SELECT 'replied',   COUNT(*)::BIGINT FROM outbound_messages WHERE status='replied'
               UNION ALL
               SELECT 'bounced',   COUNT(*)::BIGINT FROM outbound_messages WHERE status='bounced'
             ) SELECT stage, n FROM s",
            &[],
        )
        .await?;
    let by_stage = rows
        .into_iter()
        .map(|r| StageBucket { stage: r.get::<_, String>(0), count: r.get::<_, i64>(1) })
        .collect();

    let recent = client
        .query(
            "SELECT r.id::text, r.source, r.niche_slug,
                    COALESCE(r.core->>'display_name', r.core->>'handle', '?') AS display_name,
                    CASE
                      WHEN o.status='replied' THEN 'replied'
                      WHEN o.status='sent'    THEN 'sent'
                      WHEN o.status='queued'  THEN 'queued'
                      WHEN e.lead_id IS NOT NULL THEN 'enriched'
                      ELSE 'sourced'
                    END AS stage,
                    to_char(GREATEST(r.fetched_at, e.updated_at, o.sent_at), 'YYYY-MM-DD HH24:MI:SS') AS last_at
             FROM leads_raw r
             LEFT JOIN leads_enriched e ON e.lead_id = r.id
             LEFT JOIN outbound_messages o ON o.lead_id = r.id
             ORDER BY r.fetched_at DESC LIMIT 50",
            &[],
        )
        .await?;
    let recent_leads = recent
        .into_iter()
        .map(|r| LeadSummary {
            id: r.get(0),
            source: r.get(1),
            niche_slug: r.get(2),
            display_name: r.get(3),
            stage: r.get(4),
            last_event_at: r.try_get(5).ok(),
        })
        .collect();

    handle.abort();
    Ok(PipelineSnapshot { by_stage, recent_leads })
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WarmupHealth {
    pub per_subdomain: Vec<WarmupRow>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WarmupRow {
    pub subdomain: String,
    pub day_of_ramp: i32,
    pub spam_rate_7d: f64,
    pub sends_today: i64,
    pub receives_today: i64,
    pub replies_today: i64,
    pub status: String,   // ramping | maintenance | cooldown | unhealthy
}

pub async fn warmup(pg_dsn: &str) -> Result<WarmupHealth> {
    let (client, conn) = tokio_postgres::connect(pg_dsn, NoTls).await?;
    let handle = tokio::spawn(async move { let _ = conn.await; });
    let rows = client
        .query(
            "SELECT subdomain, day_of_ramp,
                    COALESCE((SELECT SUM(CASE WHEN was_spam THEN 1 ELSE 0 END)::FLOAT8
                              / NULLIF(COUNT(*), 0)
                              FROM warmup_log
                              WHERE w.subdomain = warmup_log.subdomain
                                AND event='received'
                                AND created_at >= NOW() - INTERVAL '7 days'), 0) AS spam_rate,
                    (SELECT COUNT(*) FROM warmup_log
                     WHERE w.subdomain = warmup_log.subdomain
                       AND event='sent' AND created_at >= CURRENT_DATE)::BIGINT AS sends_today,
                    (SELECT COUNT(*) FROM warmup_log
                     WHERE w.subdomain = warmup_log.subdomain
                       AND event='received' AND created_at >= CURRENT_DATE)::BIGINT AS recv_today,
                    (SELECT COUNT(*) FROM warmup_log
                     WHERE w.subdomain = warmup_log.subdomain
                       AND event='replied' AND created_at >= CURRENT_DATE)::BIGINT AS rep_today,
                    status
             FROM warmup_state w ORDER BY subdomain",
            &[],
        )
        .await
        .unwrap_or_default();
    let per_subdomain = rows
        .into_iter()
        .map(|r| WarmupRow {
            subdomain: r.get(0),
            day_of_ramp: r.get::<_, i32>(1),
            spam_rate_7d: r.get::<_, f64>(2),
            sends_today: r.get(3),
            receives_today: r.get(4),
            replies_today: r.get(5),
            status: r.get(6),
        })
        .collect();
    handle.abort();
    Ok(WarmupHealth { per_subdomain })
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct BanditRow {
    pub kind: String,
    pub persona: String,
    pub text: String,
    pub impressions: i64,
    pub rewards: i64,
    pub rate: f64,
}

pub async fn bandit_top(pg_dsn: &str, limit: i64) -> Result<Vec<BanditRow>> {
    let (client, conn) = tokio_postgres::connect(pg_dsn, NoTls).await?;
    let handle = tokio::spawn(async move { let _ = conn.await; });
    let rows = client
        .query(
            "SELECT kind, persona, text, impressions, rewards,
                    CASE WHEN impressions=0 THEN 0 ELSE rewards::FLOAT8/impressions END
             FROM variants WHERE enabled AND impressions >= 10
             ORDER BY (rewards::FLOAT8/GREATEST(impressions,1)) DESC LIMIT $1",
            &[&limit],
        )
        .await
        .unwrap_or_default();
    let out = rows
        .into_iter()
        .map(|r| BanditRow {
            kind: r.get(0),
            persona: r.get(1),
            text: r.get(2),
            impressions: r.get(3),
            rewards: r.get(4),
            rate: r.get(5),
        })
        .collect();
    handle.abort();
    Ok(out)
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct InboundReply {
    pub id: String,
    pub received_at: String,
    pub from_addr: String,
    pub to_addr: String,
    pub subject: String,
    pub class: String,
    pub snippet: String,
}

pub async fn replies(pg_dsn: &str, limit: i64) -> Result<Vec<InboundReply>> {
    let (client, conn) = tokio_postgres::connect(pg_dsn, NoTls).await?;
    let handle = tokio::spawn(async move { let _ = conn.await; });
    let rows = client
        .query(
            "SELECT id::text, to_char(received_at,'YYYY-MM-DD HH24:MI:SS'),
                    from_addr, to_addr, subject, class, snippet
             FROM inbound_mail ORDER BY received_at DESC LIMIT $1",
            &[&limit],
        )
        .await
        .unwrap_or_default();
    let out = rows
        .into_iter()
        .map(|r| InboundReply {
            id: r.get(0),
            received_at: r.get::<_, String>(1),
            from_addr: r.get(2),
            to_addr: r.get(3),
            subject: r.get(4),
            class: r.get(5),
            snippet: r.get(6),
        })
        .collect();
    handle.abort();
    Ok(out)
}

/// Quick HTTP probe for service /healthz endpoints.
pub async fn probe_health(url: &str) -> bool {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };
    client.get(url).send().await.map(|r| r.status().is_success()).unwrap_or(false)
}
