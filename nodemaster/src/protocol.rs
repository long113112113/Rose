use serde::{Deserialize, Serialize};

/// Client -> Server messages
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    /// Register to a ticket room with node_id
    Register { ticket: String, node_id: String },
    /// Leave current room
    Leave,
    /// Keep-alive ping
    Ping,
    /// Report a peer has left (Host only)
    ReportPeerLeft { node_id: String },
}

/// Server -> Client messages
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    /// Current list of peers in the room
    Peers { node_ids: Vec<String> },
    /// A new peer joined
    PeerJoined { node_id: String },
    /// A peer left
    PeerLeft { node_id: String },
    /// Pong response
    Pong,
    /// Error message
    Error { message: String },
}
