use anyhow::Result;
use iroh::{Endpoint, SecretKey};
use iroh_gossip::ALPN as GOSSIP_ALPN;
use iroh_gossip::net::Gossip;
use tokio::net::TcpListener;

mod protocol;
mod server;

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    // Initialize Iroh Endpoint
    let _secret_key = SecretKey::generate(&mut rand::rng());
    let endpoint = Endpoint::builder()
        .alpns(vec![GOSSIP_ALPN.to_vec()])
        .bind()
        .await?;

    let node_id = endpoint.id().to_string();

    // Initialize Gossip
    let gossip = Gossip::builder().spawn(endpoint.clone());

    // Spawn router to handle incoming gossip connections
    let _router = iroh::protocol::Router::builder(endpoint.clone())
        .accept(GOSSIP_ALPN, gossip.clone())
        .spawn();

    let addr = "127.0.0.1:13337";
    let listener = TcpListener::bind(&addr).await?;

    while let Ok((stream, _)) = listener.accept().await {
        let gossip_clone = gossip.clone();
        let node_id_clone = node_id.clone();
        tokio::spawn(server::handle_connection(
            stream,
            gossip_clone,
            node_id_clone,
        ));
    }

    Ok(())
}
