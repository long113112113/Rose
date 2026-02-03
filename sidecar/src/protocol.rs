use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "action", content = "payload")]
pub enum ClientMessage {
    CreateTicket,
    JoinTicket(String),
    UpdateSkin { skin_id: u32, champion_id: u32 },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
#[serde(tag = "event", content = "data")]
pub enum ServerMessage {
    TicketCreated(String),
    #[allow(dead_code)]
    PeerJoined {
        peer_id: String,
    },
    #[allow(dead_code)]
    RemoteSkinUpdate {
        peer_id: String,
        skin_id: u32,
        champion_id: u32,
    },
    Error {
        message: String,
    },
    #[allow(dead_code)]
    Log {
        level: String,
        message: String,
    },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct GossipMessage {
    pub peer_id: String,
    pub skin_id: u32,
    pub champion_id: u32,
}
