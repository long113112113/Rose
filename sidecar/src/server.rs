use std::str::FromStr;
use std::sync::Arc;

use bytes::Bytes;
use futures::{SinkExt, StreamExt};
use iroh::EndpointId;
use iroh_gossip::net::Gossip;
use tokio::net::TcpStream;
use tokio::sync::mpsc;
use tokio_tungstenite::accept_async;
use tracing::{error, info, warn};

use crate::protocol::{ClientMessage, GossipMessage, ServerMessage};

/// Ticket format: "topic_hex|node_id"
/// This allows peers to bootstrap by knowing each other's node ID
fn encode_ticket(topic_bytes: &[u8; 32], node_id: &str) -> String {
    format!("{}|{}", hex::encode(topic_bytes), node_id)
}

fn decode_ticket(ticket: &str) -> Option<([u8; 32], Option<EndpointId>)> {
    // Support both formats:
    // 1. New format: "topic_hex|node_id"
    // 2. Legacy format: "topic_hex" only (no bootstrap peer)

    if let Some((topic_hex, node_id_str)) = ticket.split_once('|') {
        // New format with node_id
        let topic_bytes: [u8; 32] = hex::decode(topic_hex).ok()?.try_into().ok()?;
        let node_id = EndpointId::from_str(node_id_str).ok();
        Some((topic_bytes, node_id))
    } else {
        // Legacy format - just topic hex
        let topic_bytes: [u8; 32] = hex::decode(ticket).ok()?.try_into().ok()?;
        Some((topic_bytes, None))
    }
}

pub async fn handle_connection(stream: TcpStream, gossip: Gossip, my_node_id: String) {
    let ws_stream = match accept_async(stream).await {
        Ok(ws) => ws,
        Err(e) => {
            error!("Error during websocket handshake: {}", e);
            return;
        }
    };

    let (ws_sender, mut ws_receiver) = ws_stream.split();

    // State
    let mut current_topic_sender: Option<iroh_gossip::api::GossipSender> = None;
    let mut _current_topic: Option<iroh_gossip::TopicId> = None;
    let mut current_receiver_task: Option<tokio::task::JoinHandle<()>> = None;
    let (to_client_tx, mut to_client_rx) = mpsc::channel::<ServerMessage>(100);

    // Writer task
    let ws_sender_arc = Arc::new(tokio::sync::Mutex::new(ws_sender));
    let ws_sender_clone = ws_sender_arc.clone();

    tokio::spawn(async move {
        while let Some(msg) = to_client_rx.recv().await {
            let json = match serde_json::to_string(&msg) {
                Ok(j) => j,
                Err(e) => {
                    error!("Failed to serialize message: {}", e);
                    continue;
                }
            };
            let mut sender = ws_sender_clone.lock().await;
            if sender
                .send(tokio_tungstenite::tungstenite::Message::Text(json.into()))
                .await
                .is_err()
            {
                break;
            }
        }
    });

    while let Some(msg_result) = ws_receiver.next().await {
        match msg_result {
            Ok(msg) => {
                if msg.is_text() {
                    let text = msg.to_string();
                    if let Ok(client_msg) = serde_json::from_str::<ClientMessage>(&text) {
                        match client_msg {
                            ClientMessage::CreateTicket => {
                                // Abort previous receiver task if exists
                                if let Some(handle) = current_receiver_task.take() {
                                    handle.abort();
                                }

                                // Generate topic
                                let topic_bytes = rand::random::<[u8; 32]>();
                                let topic_id = iroh_gossip::TopicId::from(topic_bytes);

                                // Create ticket with our node ID so others can find us
                                let ticket = encode_ticket(&topic_bytes, &my_node_id);

                                info!("[CREATE] New topic: {:?}", topic_id);
                                info!("[CREATE] Ticket with NodeID: {}", ticket);

                                // subscribe (no bootstrap peers when creating - we ARE the first peer)
                                match gossip.subscribe(topic_id, vec![]).await {
                                    Ok(sub) => {
                                        _current_topic = Some(topic_id);
                                        let (sender, mut stream) = sub.split();
                                        current_topic_sender = Some(sender.clone());

                                        // Handle receiver
                                        let tx_clone = to_client_tx.clone();
                                        let my_node_id_clone = my_node_id.clone();
                                        let sender_clone = sender.clone();
                                        let handle = tokio::spawn(async move {
                                            while let Some(event_res) = stream.next().await {
                                                match event_res {
                                                    Ok(iroh_gossip::api::Event::Received(msg)) => {
                                                        if let Ok(gossip_msg) =
                                                            serde_json::from_slice::<GossipMessage>(
                                                                &msg.content,
                                                            )
                                                        {
                                                            match gossip_msg {
                                                                GossipMessage::SkinUpdate {
                                                                    peer_id,
                                                                    skin_id,
                                                                    champion_id,
                                                                    skin_name,
                                                                    is_custom,
                                                                } => {
                                                                    info!(
                                                                        "[RX] SkinUpdate from {}: skin_id={}",
                                                                        peer_id, skin_id
                                                                    );
                                                                    let _ = tx_clone.send(ServerMessage::RemoteSkinUpdate {
                                                                        peer_id: peer_id.clone(),
                                                                        skin_id,
                                                                        champion_id,
                                                                        skin_name,
                                                                        is_custom
                                                                    }).await;
                                                                    let ack =
                                                                        GossipMessage::SkinAck {
                                                                            target_peer_id: peer_id,
                                                                        };
                                                                    if let Ok(json) =
                                                                        serde_json::to_vec(&ack)
                                                                    {
                                                                        sender_clone
                                                                            .broadcast(Bytes::from(
                                                                                json,
                                                                            ))
                                                                            .await
                                                                            .ok();
                                                                    }
                                                                }
                                                                GossipMessage::SkinAck {
                                                                    target_peer_id,
                                                                } => {
                                                                    if target_peer_id
                                                                        == my_node_id_clone
                                                                    {
                                                                        let _ = tx_clone.send(ServerMessage::SyncConfirmed {
                                                                            peer_id: msg.delivered_from.to_string(),
                                                                        }).await;
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                    Ok(iroh_gossip::api::Event::NeighborUp(
                                                        peer_id,
                                                    )) => {
                                                        info!("[GOSSIP] Peer joined: {}", peer_id);
                                                        let _ = tx_clone
                                                            .send(ServerMessage::PeerJoined {
                                                                peer_id: peer_id.to_string(),
                                                            })
                                                            .await;
                                                    }
                                                    Ok(iroh_gossip::api::Event::NeighborDown(
                                                        peer_id,
                                                    )) => {
                                                        info!("[GOSSIP] Peer left: {}", peer_id);
                                                        let _ = tx_clone
                                                            .send(ServerMessage::PeerLeft {
                                                                peer_id: peer_id.to_string(),
                                                            })
                                                            .await;
                                                    }
                                                    _ => {}
                                                }
                                            }
                                        });
                                        current_receiver_task = Some(handle);

                                        let _ = to_client_tx
                                            .send(ServerMessage::TicketCreated(ticket))
                                            .await;
                                    }
                                    Err(e) => {
                                        let _ = to_client_tx
                                            .send(ServerMessage::Error {
                                                message: e.to_string(),
                                            })
                                            .await;
                                    }
                                }
                            }
                            ClientMessage::GetNodeId => {
                                let _ = to_client_tx
                                    .send(ServerMessage::NodeId(my_node_id.clone()))
                                    .await;
                            }
                            ClientMessage::JoinTicket(ticket) => {
                                // Decode ticket to get topic + optional bootstrap peer
                                match decode_ticket(&ticket) {
                                    Some((topic_bytes, bootstrap_node_id)) => {
                                        // Abort previous receiver task if exists
                                        if let Some(handle) = current_receiver_task.take() {
                                            handle.abort();
                                        }

                                        let topic_id = iroh_gossip::TopicId::from(topic_bytes);

                                        // Build bootstrap peers list
                                        let bootstrap_peers: Vec<EndpointId> =
                                            bootstrap_node_id.into_iter().collect();

                                        info!("[JOIN] Topic: {:?}", topic_id);
                                        info!("[JOIN] Bootstrap peers: {:?}", bootstrap_peers);

                                        // Subscribe WITH bootstrap peers
                                        match gossip
                                            .subscribe(topic_id, bootstrap_peers.clone())
                                            .await
                                        {
                                            Ok(sub) => {
                                                _current_topic = Some(topic_id);
                                                info!("[JOIN] Subscribed successfully!");

                                                let (sender, mut stream) = sub.split();
                                                current_topic_sender = Some(sender.clone());

                                                // Send confirmation
                                                let _ = to_client_tx
                                                    .send(ServerMessage::JoinedRoom {
                                                        ticket: ticket.clone(),
                                                    })
                                                    .await;

                                                // Send info about bootstrap
                                                let _ = to_client_tx.send(ServerMessage::Log {
                                                    level: "INFO".to_string(),
                                                    message: format!(
                                                        "Joined with {} bootstrap peer(s). Waiting for connection...",
                                                        bootstrap_peers.len()
                                                    ),
                                                }).await;

                                                let tx_clone = to_client_tx.clone();
                                                let my_node_id_clone = my_node_id.clone();
                                                let sender_clone = sender.clone();
                                                let handle = tokio::spawn(async move {
                                                    while let Some(event_res) = stream.next().await
                                                    {
                                                        match event_res {
                                                            Ok(iroh_gossip::api::Event::Received(
                                                                msg,
                                                            )) => {
                                                                if let Ok(gossip_msg) =
                                                                    serde_json::from_slice::<
                                                                        GossipMessage,
                                                                    >(
                                                                        &msg.content
                                                                    )
                                                                {
                                                                    match gossip_msg {
                                                                        GossipMessage::SkinUpdate {
                                                                            peer_id,
                                                                            skin_id,
                                                                            champion_id,
                                                                            skin_name,
                                                                            is_custom,
                                                                        } => {
                                                                            info!("[RX] SkinUpdate from {}: skin_id={}", peer_id, skin_id);
                                                                            let _ = tx_clone.send(ServerMessage::RemoteSkinUpdate {
                                                                                peer_id: peer_id.clone(),
                                                                                skin_id,
                                                                                champion_id,
                                                                                skin_name,
                                                                                is_custom
                                                                            }).await;

                                                                            // AUTO ACK
                                                                            let ack =
                                                                                GossipMessage::SkinAck {
                                                                                    target_peer_id: peer_id,
                                                                                };
                                                                            if let Ok(json) =
                                                                                serde_json::to_vec(&ack)
                                                                            {
                                                                                sender_clone
                                                                                    .broadcast(
                                                                                        Bytes::from(
                                                                                            json,
                                                                                        ),
                                                                                    )
                                                                                    .await
                                                                                    .ok();
                                                                            }
                                                                        }
                                                                        GossipMessage::SkinAck {
                                                                            target_peer_id,
                                                                        } => {
                                                                            if target_peer_id
                                                                                == my_node_id_clone
                                                                            {
                                                                                let _ = tx_clone.send(ServerMessage::SyncConfirmed {
                                                                                    peer_id: msg.delivered_from.to_string(),
                                                                                }).await;
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                            Ok(
                                                                iroh_gossip::api::Event::NeighborUp(
                                                                    peer_id,
                                                                ),
                                                            ) => {
                                                                info!("[GOSSIP] Peer joined: {}", peer_id);
                                                                let _ = tx_clone
                                                                    .send(ServerMessage::PeerJoined {
                                                                        peer_id: peer_id.to_string(),
                                                                    })
                                                                    .await;
                                                            }
                                                            Ok(
                                                                iroh_gossip::api::Event::NeighborDown(
                                                                    peer_id,
                                                                ),
                                                            ) => {
                                                                info!("[GOSSIP] Peer left: {}", peer_id);
                                                                let _ = tx_clone
                                                                    .send(ServerMessage::PeerLeft {
                                                                        peer_id: peer_id.to_string(),
                                                                    })
                                                                    .await;
                                                            }
                                                            _ => {}
                                                        }
                                                    }
                                                });
                                                current_receiver_task = Some(handle);
                                            }
                                            Err(e) => {
                                                error!("[JOIN] Subscribe failed: {}", e);
                                                let _ = to_client_tx
                                                    .send(ServerMessage::Error {
                                                        message: e.to_string(),
                                                    })
                                                    .await;
                                            }
                                        }
                                    }
                                    None => {
                                        warn!("[JOIN] Invalid ticket format: {}", ticket);
                                        let _ = to_client_tx
                                            .send(ServerMessage::InvalidTicket {
                                                ticket: ticket.clone(),
                                                reason: "Invalid ticket format. Expected: topic_hex|node_id".to_string(),
                                            })
                                            .await;
                                    }
                                }
                            }
                            ClientMessage::UpdateSkin {
                                skin_id,
                                champion_id,
                                skin_name,
                                is_custom,
                            } => {
                                if let Some(sender) = &current_topic_sender {
                                    let payload = GossipMessage::SkinUpdate {
                                        peer_id: my_node_id.clone(),
                                        skin_id,
                                        champion_id,
                                        skin_name,
                                        is_custom,
                                    };
                                    if let Ok(json) = serde_json::to_vec(&payload) {
                                        info!(
                                            "[TX] Broadcasting skin_id={}, champion_id={}",
                                            skin_id, champion_id
                                        );
                                        match sender.broadcast(Bytes::from(json)).await {
                                            Ok(_) => {
                                                info!("[TX] Broadcast queued successfully");
                                                let _ = to_client_tx
                                                    .send(ServerMessage::Log {
                                                        level: "DEBUG".to_string(),
                                                        message: format!(
                                                            "Broadcast queued for skin_id={}",
                                                            skin_id
                                                        ),
                                                    })
                                                    .await;
                                            }
                                            Err(e) => {
                                                error!("[TX] Broadcast failed: {}", e);
                                                let _ = to_client_tx
                                                    .send(ServerMessage::Log {
                                                        level: "ERROR".to_string(),
                                                        message: format!("Broadcast failed: {}", e),
                                                    })
                                                    .await;
                                            }
                                        }
                                    }
                                } else {
                                    error!("[TX] No topic sender! Not in any room.");
                                    let _ = to_client_tx
                                        .send(ServerMessage::Error {
                                            message: "Not in any room. Call JoinTicket first."
                                                .to_string(),
                                        })
                                        .await;
                                }
                            }
                        }
                    }
                }
            }
            Err(_) => break,
        }
    }

    // Cleanup on disconnect
    if let Some(handle) = current_receiver_task {
        handle.abort();
    }
}
