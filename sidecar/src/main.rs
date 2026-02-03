use anyhow::Result;
use iroh::{Endpoint, SecretKey};
use iroh_gossip::ALPN as GOSSIP_ALPN;
use iroh_gossip::net::Gossip;
use tokio::net::TcpListener;
use tracing::info;

mod protocol;
mod server;

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

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
