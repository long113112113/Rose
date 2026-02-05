//! NodeMaster client for peer discovery
//!
//! Connects to the NodeMaster server to register and discover peers
//! in the same ticket room. Includes auto-reconnect with exponential backoff.

use futures::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{Mutex, mpsc};
use tokio_tungstenite::connect_async;
use tracing::{error, warn};

/// NodeMaster server address
const NODEMASTER_URL: &str = "ws://127.0.0.1:31337";

/// Reconnect configuration
const INITIAL_BACKOFF_MS: u64 = 2000;
const MAX_BACKOFF_MS: u64 = 30000;
const MAX_RECONNECT_ATTEMPTS: u32 = 10;

/// Client -> NodeMaster messages
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum NMClientMessage {
    Register { ticket: String, node_id: String },
    Leave,
    Ping,
}

/// NodeMaster -> Client messages
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum NMServerMessage {
    Peers { node_ids: Vec<String> },
    PeerJoined { node_id: String },
    PeerLeft { node_id: String },
    Pong,
    Error { message: String },
}

/// Events from NodeMaster client
#[derive(Debug, Clone)]
pub enum NodeMasterEvent {
    /// Initial peer list when joining a room
    PeerList(Vec<String>),
    /// A new peer joined
    PeerJoined(String),
    /// A peer left
    PeerLeft(String),
    /// Connection error
    Error(String),
    /// Disconnected from server
    Disconnected,
    /// Attempting to reconnect
    Reconnecting,
    /// Successfully reconnected
    Reconnected,
}

/// Registration info for auto-reconnect
#[derive(Debug, Clone, Default)]
struct RegistrationInfo {
    ticket: Option<String>,
    node_id: Option<String>,
}

pub struct NodeMasterClient {
    tx: mpsc::UnboundedSender<NMClientMessage>,
}

impl NodeMasterClient {
    /// Connect to NodeMaster with auto-reconnect support
    pub async fn connect(
        nodemaster_url: Option<&str>,
    ) -> Result<(Self, mpsc::UnboundedReceiver<NodeMasterEvent>), String> {
        let url = nodemaster_url.unwrap_or(NODEMASTER_URL).to_string();

        // Channel for events from NodeMaster
        let (event_tx, event_rx) = mpsc::unbounded_channel::<NodeMasterEvent>();

        // Channel for sending commands
        let (cmd_tx, cmd_rx) = mpsc::unbounded_channel::<NMClientMessage>();

        // Shared registration info for auto-reconnect
        let registration = Arc::new(Mutex::new(RegistrationInfo::default()));
        let registration_clone = registration.clone();

        // Spawn the connection manager with auto-reconnect
        let event_tx_clone = event_tx.clone();
        tokio::spawn(async move {
            Self::connection_loop(url, cmd_rx, event_tx_clone, registration_clone).await;
        });

        Ok((Self { tx: cmd_tx }, event_rx))
    }

    /// Main connection loop with auto-reconnect
    async fn connection_loop(
        url: String,
        mut cmd_rx: mpsc::UnboundedReceiver<NMClientMessage>,
        event_tx: mpsc::UnboundedSender<NodeMasterEvent>,
        registration: Arc<Mutex<RegistrationInfo>>,
    ) {
        let mut backoff_ms = INITIAL_BACKOFF_MS;
        let mut attempt = 0u32;

        loop {
            match connect_async(&url).await {
                Ok((ws_stream, _)) => {
                    backoff_ms = INITIAL_BACKOFF_MS; // Reset backoff on success
                    attempt = 0;

                    // Notify reconnected if this wasn't the first attempt
                    if attempt > 0 {
                        let _ = event_tx.send(NodeMasterEvent::Reconnected);
                    }

                    let (mut ws_sender, mut ws_receiver) = ws_stream.split();

                    // Auto re-register if we have saved registration info
                    {
                        let reg = registration.lock().await;
                        if let (Some(ticket), Some(node_id)) = (&reg.ticket, &reg.node_id) {
                            let msg = NMClientMessage::Register {
                                ticket: ticket.clone(),
                                node_id: node_id.clone(),
                            };
                            if let Ok(json) = serde_json::to_string(&msg) {
                                let _ = ws_sender
                                    .send(tokio_tungstenite::tungstenite::Message::Text(
                                        json.into(),
                                    ))
                                    .await;
                            }
                        }
                    }

                    // Process messages until disconnect
                    let disconnect_reason = Self::process_messages(
                        &mut ws_sender,
                        &mut ws_receiver,
                        &mut cmd_rx,
                        &event_tx,
                        &registration,
                    )
                    .await;

                    match disconnect_reason {
                        DisconnectReason::Leave => {
                            let _ = event_tx.send(NodeMasterEvent::Disconnected);
                            break; // Exit loop, no reconnect
                        }
                        DisconnectReason::Error(e) => {
                            warn!("[NM] Connection lost: {}", e);
                            // Fall through to reconnect
                        }
                        DisconnectReason::ServerClosed => {

                            // Fall through to reconnect
                        }
                    }
                }
                Err(e) => {
                    warn!("[NM] Failed to connect: {}", e);
                }
            }

            // Check if we should retry
            attempt += 1;
            if attempt > MAX_RECONNECT_ATTEMPTS {
                error!(
                    "[NM] Max reconnect attempts ({}) reached, giving up",
                    MAX_RECONNECT_ATTEMPTS
                );
                let _ = event_tx.send(NodeMasterEvent::Error(
                    "Max reconnect attempts reached".to_string(),
                ));
                break;
            }

            // Notify about reconnect attempt
            let _ = event_tx.send(NodeMasterEvent::Reconnecting);

            // Wait with exponential backoff

            tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
            backoff_ms = (backoff_ms * 2).min(MAX_BACKOFF_MS);
        }
    }

    /// Process messages until disconnect
    async fn process_messages(
        ws_sender: &mut futures::stream::SplitSink<
            tokio_tungstenite::WebSocketStream<
                tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
            >,
            tokio_tungstenite::tungstenite::Message,
        >,
        ws_receiver: &mut futures::stream::SplitStream<
            tokio_tungstenite::WebSocketStream<
                tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
            >,
        >,
        cmd_rx: &mut mpsc::UnboundedReceiver<NMClientMessage>,
        event_tx: &mpsc::UnboundedSender<NodeMasterEvent>,
        registration: &Arc<Mutex<RegistrationInfo>>,
    ) -> DisconnectReason {
        loop {
            tokio::select! {
                // Handle outgoing commands
                Some(cmd) = cmd_rx.recv() => {
                    // Save registration info for auto-reconnect
                    if let NMClientMessage::Register { ref ticket, ref node_id } = cmd {
                        let mut reg = registration.lock().await;
                        reg.ticket = Some(ticket.clone());
                        reg.node_id = Some(node_id.clone());
                    }

                    // Check for Leave command
                    if matches!(cmd, NMClientMessage::Leave) {
                        let _ = serde_json::to_string(&cmd)
                            .map(|json| ws_sender.send(tokio_tungstenite::tungstenite::Message::Text(json.into())));
                        return DisconnectReason::Leave;
                    }

                    // Send command
                    match serde_json::to_string(&cmd) {
                        Ok(json) => {
                            if ws_sender
                                .send(tokio_tungstenite::tungstenite::Message::Text(json.into()))
                                .await
                                .is_err()
                            {
                                return DisconnectReason::Error("Send failed".to_string());
                            }
                        }
                        Err(e) => {
                            error!("[NM] Failed to serialize: {}", e);
                        }
                    }
                }

                // Handle incoming messages
                msg_result = ws_receiver.next() => {
                    match msg_result {
                        Some(Ok(tokio_tungstenite::tungstenite::Message::Text(text))) => {
                            if let Ok(msg) = serde_json::from_str::<NMServerMessage>(&text) {
                                let event = match msg {
                                    NMServerMessage::Peers { node_ids } => {

                                        NodeMasterEvent::PeerList(node_ids)
                                    }
                                    NMServerMessage::PeerJoined { node_id } => {
                                        NodeMasterEvent::PeerJoined(node_id)
                                    }
                                    NMServerMessage::PeerLeft { node_id } => {
                                        NodeMasterEvent::PeerLeft(node_id)
                                    }
                                    NMServerMessage::Pong => continue,
                                    NMServerMessage::Error { message } => {
                                        warn!("[NM] Error: {}", message);
                                        NodeMasterEvent::Error(message)
                                    }
                                };
                                if event_tx.send(event).is_err() {
                                    return DisconnectReason::Error("Event channel closed".to_string());
                                }
                            }
                        }
                        Some(Ok(tokio_tungstenite::tungstenite::Message::Close(_))) => {
                            return DisconnectReason::ServerClosed;
                        }
                        Some(Err(e)) => {
                            return DisconnectReason::Error(e.to_string());
                        }
                        None => {
                            return DisconnectReason::ServerClosed;
                        }
                        _ => {}
                    }
                }
            }
        }
    }

    /// Register to a ticket room
    pub fn register(&self, ticket: String, node_id: String) {
        let _ = self.tx.send(NMClientMessage::Register { ticket, node_id });
    }

    /// Leave current room
    #[allow(dead_code)]
    pub fn leave(&self) {
        let _ = self.tx.send(NMClientMessage::Leave);
    }
}

/// Reason for disconnect
enum DisconnectReason {
    Leave,
    Error(String),
    ServerClosed,
}
