use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "action", content = "payload")]
pub enum ClientMessage {
    CreateTicket,
    JoinTicket(String),
    UpdateSkin {
        skin_id: u32,
        champion_id: u32,
        skin_name: String,
        is_custom: bool,
    },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "event", content = "data")]
pub enum ServerMessage {
    TicketCreated(String),
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
