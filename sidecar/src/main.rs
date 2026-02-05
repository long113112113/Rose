use anyhow::Result;
use clap::Parser;
use iroh::{Endpoint, SecretKey};
use iroh_gossip::ALPN as GOSSIP_ALPN;
use iroh_gossip::net::Gossip;
use std::path::PathBuf;
use tokio::net::TcpListener;
use tracing::info;
use tracing_subscriber::prelude::*;

mod nodemaster_client;
mod protocol;
mod server;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// Directory to store logs
    #[arg(long)]
    log_dir: Option<PathBuf>,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    // Setup logging registry
    let registry = tracing_subscriber::registry();

    if let Some(log_dir) = args.log_dir {
        // Ensure log directory exists
        if !log_dir.exists() {
            std::fs::create_dir_all(&log_dir)?;
        }

        // Create file appender
        let file_appender = tracing_appender::rolling::daily(&log_dir, "sidecar.log");
        let (non_blocking, _guard) = tracing_appender::non_blocking(file_appender);

        let file_layer = tracing_subscriber::fmt::layer()
            .with_target(false)
            .with_thread_ids(false)
            .with_file(false)
            .with_line_number(false)
            .with_writer(non_blocking)
            .with_timer(tracing_subscriber::fmt::time::LocalTime::new(
                time::macros::format_description!("[year]-[month]-[day] [hour]:[minute]:[second]"),
            ))
            .with_ansi(false);

        // Also print to stdout for dev/debug
        let stdout_layer = tracing_subscriber::fmt::layer()
            .with_target(false)
            .with_timer(tracing_subscriber::fmt::time::LocalTime::new(
                time::macros::format_description!("[year]-[month]-[day] [hour]:[minute]:[second]"),
            ));

        registry.with(file_layer).with(stdout_layer).init();
        info!("Sidecar started. Logging to {:?}", log_dir);
    } else {
        // Default to stdout only
        let stdout_layer = tracing_subscriber::fmt::layer()
            .with_target(false)
            .with_timer(tracing_subscriber::fmt::time::LocalTime::new(
                time::macros::format_description!("[year]-[month]-[day] [hour]:[minute]:[second]"),
            ));
        registry.with(stdout_layer).init();
        info!("Sidecar started. Logging to stdout (no --log-dir provided)");
    }

    // Generate secret key (for persistent identity, save this to disk)
    let secret_key = SecretKey::generate(&mut rand::rng());

    let endpoint = Endpoint::builder()
        .secret_key(secret_key)
        .alpns(vec![GOSSIP_ALPN.to_vec()])
        .bind()
        .await?;

    let endpoint_id = endpoint.id();
    info!("Endpoint ID: {}", endpoint_id);

    // Wait for connection to relay network to ensure peer discovery works
    info!("Connecting to relay network...");
    endpoint.online().await;

    // Log relay info - confirms we're connected to relay network
    let addr = endpoint.addr();
    if let Some(url) = addr.relay_urls().next() {
        info!("Connected to relay: {}", url);
        info!("Peers will find each other via DNS/relay, then connect directly P2P");
    } else {
        info!("Warning: No relay connection, peer discovery may not work");
    }

    // Initialize Gossip
    let gossip = Gossip::builder().spawn(endpoint.clone());

    // Spawn router to handle incoming gossip connections
    let _router = iroh::protocol::Router::builder(endpoint.clone())
        .accept(GOSSIP_ALPN, gossip.clone())
        .spawn();

    let ws_addr = "127.0.0.1:13337";
    info!("WebSocket server listening on {}", ws_addr);
    let listener = TcpListener::bind(&ws_addr).await?;

    while let Ok((stream, _)) = listener.accept().await {
        let gossip_clone = gossip.clone();
        let endpoint_id_str = endpoint_id.to_string();
        tokio::spawn(server::handle_connection(
            stream,
            gossip_clone,
            endpoint_id_str,
        ));
    }

    Ok(())
}
