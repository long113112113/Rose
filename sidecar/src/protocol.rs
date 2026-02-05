use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "action", content = "payload")]
pub enum ClientMessage {
    CreateTicket,
    GetNodeId,
    JoinTicket(String),
    /// Join via NodeMaster server for peer discovery
    /// Payload is just the ticket (topic hash), NodeMaster provides peer list
    JoinViaNodeMaster {
        ticket: String,
        nodemaster_url: Option<String>,
    },
    UpdateSkin {
        skin_id: u32,
        champion_id: u32,
        skin_name: String,
        is_custom: bool,
    },
    LeaveRoom,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "event", content = "data")]
pub enum ServerMessage {
    TicketCreated(String),
    NodeId(String),
    JoinedRoom {
        ticket: String,
    },
    InvalidTicket {
        ticket: String,
        reason: String,
    },
    PeerJoined {
        peer_id: String,
    },
    PeerLeft {
        peer_id: String,
    },
    RemoteSkinUpdate {
        peer_id: String,
        skin_id: u32,
        champion_id: u32,
        skin_name: String,
        is_custom: bool,
    },
    SyncConfirmed {
        peer_id: String,
    },
    Error {
        message: String,
    },
    Log {
        level: String,
        message: String,
    },
    LeftRoom,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "type", content = "data")]
pub enum GossipMessage {
    SkinUpdate {
        peer_id: String,
        skin_id: u32,
        champion_id: u32,
        skin_name: String,
        is_custom: bool,
    },
    SkinAck {
        target_peer_id: String,
    },
}
