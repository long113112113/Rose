mod connection_limiter;
mod protocol;
mod room;
mod server;

use tokio::net::TcpListener;
use tracing::{info, warn};

use connection_limiter::ConnectionLimiter;

/// NodeMaster server port
const PORT: u16 = 31337;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_target(false)
        .with_thread_ids(false)
        .init();

    let addr = format!("0.0.0.0:{}", PORT);
    let listener = TcpListener::bind(&addr).await?;

    info!("NodeMaster server listening on {}", addr);

    let rooms = room::RoomManager::new();
    let limiter = ConnectionLimiter::new();

    loop {
        let (stream, addr) = listener.accept().await?;

        // Check connection limits before accepting
        let client_ip = addr.ip();
        if let Err(e) = limiter.try_connect(client_ip).await {
            warn!("Connection rejected from {}: {}", addr, e);
            drop(stream); // Close connection immediately
            continue;
        }

        let rooms = rooms.clone();
        let limiter = limiter.clone();

        tokio::spawn(async move {
            server::handle_connection(stream, addr, rooms, limiter).await;
        });
    }
}
