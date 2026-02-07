use std::net::SocketAddr;

use futures::{SinkExt, StreamExt};
use std::time::Duration;
use tokio::net::TcpStream;
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::Message;
use tracing::{error, warn};

use crate::connection_limiter::ConnectionLimiter;
use crate::protocol::{ClientMessage, ServerMessage};
use crate::room::RoomManager;

/// Handle a single WebSocket connection
pub async fn handle_connection(
    stream: TcpStream,
    addr: SocketAddr,
    rooms: RoomManager,
    limiter: ConnectionLimiter,
) {
    let ws_stream = match tokio_tungstenite::accept_async(stream).await {
        Ok(ws) => ws,
        Err(e) => {
            error!("WebSocket handshake failed for {}: {}", addr, e);
            limiter.disconnect(addr.ip()).await;
            return;
        }
    };

    let (mut ws_sender, mut ws_receiver) = ws_stream.split();

    // Channel for sending messages to this client
    let (tx, mut rx) = mpsc::unbounded_channel::<ServerMessage>();

    // Current node_id for this connection
    let mut current_node_id: Option<String> = None;

    // Task to forward messages from channel to WebSocket
    let send_task = tokio::spawn(async move {
        while let Some(msg) = rx.recv().await {
            let json = match serde_json::to_string(&msg) {
                Ok(j) => j,
                Err(e) => {
                    error!("Failed to serialize message: {}", e);
                    continue;
                }
            };
            if ws_sender.send(Message::Text(json)).await.is_err() {
                break;
            }
        }
    });

    // Process incoming messages with timeout
    loop {
        // 45 seconds timeout for heartbeat
        let msg_future = ws_receiver.next();
        let result = match tokio::time::timeout(Duration::from_secs(45), msg_future).await {
            Ok(res) => res,
            Err(_) => {
                // Timeout exceeded
                // warn!("Connection timed out for {}", addr); // Optional logging
                break;
            }
        };

        // Handle the message result (same as before, just unwrapped from timeout)
        let result = match result {
            Some(r) => r,
            None => break, // Stream closed
        };
        let msg = match result {
            Ok(Message::Text(text)) => text,
            Ok(Message::Ping(_)) => {
                // Pong is handled automatically by tungstenite
                continue;
            }
            Ok(Message::Close(_)) => {
                break;
            }
            Ok(_) => continue,
            Err(e) => {
                warn!("WebSocket error from {}: {}", addr, e);
                break;
            }
        };

        // Parse client message
        let client_msg: ClientMessage = match serde_json::from_str(&msg) {
            Ok(m) => m,
            Err(e) => {
                let _ = tx.send(ServerMessage::Error {
                    message: format!("Invalid message format: {}", e),
                });
                continue;
            }
        };

        match client_msg {
            ClientMessage::ReportPeerLeft { node_id } => {
                // Host reports a peer left - remove them from the room
                if current_node_id.is_some() {
                    rooms.leave(&node_id).await;
                } else {
                    warn!("Received ReportPeerLeft from unregistered client {}", addr);
                }
            }
            ClientMessage::Register { ticket, node_id } => {
                // If already registered with different node_id, leave first
                if let Some(ref old_id) = current_node_id {
                    if old_id != &node_id {
                        rooms.leave(old_id).await;
                    }
                }

                current_node_id = Some(node_id.clone());

                // Register and get existing peers
                let peers = rooms.register(ticket, node_id, tx.clone()).await;

                // Send current peers to client
                let _ = tx.send(ServerMessage::Peers { node_ids: peers });
            }

            ClientMessage::Leave => {
                if let Some(ref node_id) = current_node_id {
                    rooms.leave(node_id).await;
                    current_node_id = None;
                }
            }

            ClientMessage::Ping => {
                let _ = tx.send(ServerMessage::Pong);
            }
        }
    }

    // Cleanup on disconnect
    if let Some(ref node_id) = current_node_id {
        rooms.leave(node_id).await;
    }

    // Release connection slot
    limiter.disconnect(addr.ip()).await;

    send_task.abort();
}
