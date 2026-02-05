use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{mpsc, RwLock};

use crate::protocol::ServerMessage;

/// Sender channel for a connected client
pub type ClientSender = mpsc::UnboundedSender<ServerMessage>;

/// Represents a client in a room
#[derive(Debug, Clone)]
pub struct RoomMember {
    pub sender: ClientSender,
}

/// A room that holds clients with the same ticket
#[derive(Debug, Default)]
pub struct Room {
    /// Map of node_id -> RoomMember
    members: HashMap<String, RoomMember>,
}

impl Room {
    pub fn new() -> Self {
        Self {
            members: HashMap::new(),
        }
    }

    /// Add a member to the room, returns list of existing peer node_ids
    pub fn add_member(&mut self, node_id: String, sender: ClientSender) -> Vec<String> {
        // Get existing peers before adding
        let existing_peers: Vec<String> = self.members.keys().cloned().collect();

        // Notify existing members about new peer
        for member in self.members.values() {
            let _ = member.sender.send(ServerMessage::PeerJoined {
                node_id: node_id.clone(),
            });
        }

        // Add the new member
        self.members.insert(node_id.clone(), RoomMember { sender });

        existing_peers
    }

    /// Remove a member from the room
    pub fn remove_member(&mut self, node_id: &str) {
        self.members.remove(node_id);

        // Notify remaining members
        for member in self.members.values() {
            let _ = member.sender.send(ServerMessage::PeerLeft {
                node_id: node_id.to_string(),
            });
        }
    }

    /// Check if room is empty
    pub fn is_empty(&self) -> bool {
        self.members.is_empty()
    }
}

/// Manager for all rooms
#[derive(Debug, Default, Clone)]
pub struct RoomManager {
    /// Map of ticket -> Room
    rooms: Arc<RwLock<HashMap<String, Room>>>,
    /// Map of node_id -> current ticket (for single-ticket constraint)
    client_tickets: Arc<RwLock<HashMap<String, String>>>,
}

impl RoomManager {
    pub fn new() -> Self {
        Self {
            rooms: Arc::new(RwLock::new(HashMap::new())),
            client_tickets: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Register a client to a ticket room
    /// If client was in another room, they are removed from it first
    pub async fn register(
        &self,
        ticket: String,
        node_id: String,
        sender: ClientSender,
    ) -> Vec<String> {
        // Check if client is already in a room
        {
            let client_tickets = self.client_tickets.read().await;
            if let Some(old_ticket) = client_tickets.get(&node_id) {
                if old_ticket != &ticket {
                    // Leave old room first
                    drop(client_tickets);
                    self.leave(&node_id).await;
                }
            }
        }

        // Record client's current ticket
        {
            let mut client_tickets = self.client_tickets.write().await;
            client_tickets.insert(node_id.clone(), ticket.clone());
        }

        // Add to room
        let mut rooms = self.rooms.write().await;
        let room = rooms.entry(ticket).or_insert_with(Room::new);
        room.add_member(node_id, sender)
    }

    /// Remove a client from their current room
    pub async fn leave(&self, node_id: &str) {
        // Get and remove the client's ticket
        let ticket = {
            let mut client_tickets = self.client_tickets.write().await;
            client_tickets.remove(node_id)
        };

        if let Some(ticket) = ticket {
            let mut rooms = self.rooms.write().await;
            if let Some(room) = rooms.get_mut(&ticket) {
                room.remove_member(node_id);

                // Clean up empty rooms
                if room.is_empty() {
                    rooms.remove(&ticket);
                }
            }
        }
    }

    /// Get stats for logging
    #[allow(dead_code)]
    pub async fn stats(&self) -> (usize, usize) {
        let rooms = self.rooms.read().await;
        let clients = self.client_tickets.read().await;
        (rooms.len(), clients.len())
    }
}
