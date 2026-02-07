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

use crate::nodemaster_client::{NodeMasterClient, NodeMasterEvent};
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
    let mut nodemaster_event_task: Option<tokio::task::JoinHandle<()>> = None;
    let mut _nodemaster_client: Option<NodeMasterClient> = None;
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
                                                        let _ = tx_clone
                                                            .send(ServerMessage::PeerJoined {
                                                                peer_id: peer_id.to_string(),
                                                            })
                                                            .await;
                                                    }
                                                    Ok(iroh_gossip::api::Event::NeighborDown(
                                                        peer_id,
                                                    )) => {
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

                                        // Subscribe WITH bootstrap peers
                                        match gossip
                                            .subscribe(topic_id, bootstrap_peers.clone())
                                            .await
                                        {
                                            Ok(sub) => {
                                                _current_topic = Some(topic_id);

                                                let (sender, mut stream) = sub.split();
                                                current_topic_sender = Some(sender.clone());

                                                // Send confirmation
                                                let _ = to_client_tx
                                                    .send(ServerMessage::JoinedRoom {
                                                        ticket: ticket.clone(),
                                                    })
                                                    .await;

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
                            ClientMessage::JoinViaNodeMaster {
                                ticket,
                                nodemaster_url,
                            } => {
                                // Connect to NodeMaster for peer discovery

                                // Abort previous tasks
                                if let Some(handle) = current_receiver_task.take() {
                                    handle.abort();
                                }
                                if let Some(handle) = nodemaster_event_task.take() {
                                    handle.abort();
                                }

                                // Connect to NodeMaster
                                let nm_url = nodemaster_url.as_deref();
                                match NodeMasterClient::connect(nm_url).await {
                                    Ok((client, mut event_rx)) => {
                                        // Register with ticket
                                        client.register(ticket.clone(), my_node_id.clone());
                                        _nodemaster_client = Some(client);

                                        // Wait for initial peer list
                                        let initial_peers =
                                            if let Some(event) = event_rx.recv().await {
                                                match event {
                                                    NodeMasterEvent::PeerList(peers) => peers,
                                                    _ => vec![],
                                                }
                                            } else {
                                                vec![]
                                            };

                                        // Convert peer strings to EndpointIds
                                        let bootstrap_peers: Vec<EndpointId> = initial_peers
                                            .iter()
                                            .filter_map(|p| EndpointId::from_str(p).ok())
                                            .collect();

                                        // Create topic from ticket hash
                                        let topic_bytes: [u8; 32] = match hex::decode(&ticket) {
                                            Ok(bytes) if bytes.len() == 32 => {
                                                bytes.try_into().unwrap()
                                            }
                                            _ => {
                                                // Hash the ticket if it's not already a valid hex
                                                use std::collections::hash_map::DefaultHasher;
                                                use std::hash::{Hash, Hasher};
                                                let mut hasher = DefaultHasher::new();
                                                ticket.hash(&mut hasher);
                                                let hash = hasher.finish();
                                                // Generate 32 bytes from hash
                                                let mut bytes = [0u8; 32];
                                                bytes[..8].copy_from_slice(&hash.to_le_bytes());
                                                bytes[8..16].copy_from_slice(&hash.to_be_bytes());
                                                bytes[16..24].copy_from_slice(&hash.to_le_bytes());
                                                bytes[24..32].copy_from_slice(&hash.to_be_bytes());
                                                bytes
                                            }
                                        };
                                        let topic_id = iroh_gossip::TopicId::from(topic_bytes);

                                        // Subscribe to gossip with peers from NodeMaster
                                        match gossip
                                            .subscribe(topic_id, bootstrap_peers.clone())
                                            .await
                                        {
                                            Ok(sub) => {
                                                _current_topic = Some(topic_id);

                                                let (sender, mut stream) = sub.split();
                                                current_topic_sender = Some(sender.clone());

                                                // Send confirmation
                                                let _ = to_client_tx
                                                    .send(ServerMessage::JoinedRoom {
                                                        ticket: ticket.clone(),
                                                    })
                                                    .await;

                                                // Task to handle gossip events
                                                let tx_clone = to_client_tx.clone();
                                                let my_node_id_clone = my_node_id.clone();
                                                let sender_clone = sender.clone();
                                                let gossip_handle = tokio::spawn(async move {
                                                    while let Some(event_res) = stream.next().await
                                                    {
                                                        match event_res {
                                                            Ok(iroh_gossip::api::Event::Received(msg)) => {
                                                                if let Ok(gossip_msg) = serde_json::from_slice::<GossipMessage>(&msg.content) {
                                                                    match gossip_msg {
                                                                        GossipMessage::SkinUpdate { peer_id, skin_id, champion_id, skin_name, is_custom } => {

                                                                            let _ = tx_clone.send(ServerMessage::RemoteSkinUpdate {
                                                                                peer_id: peer_id.clone(),
                                                                                skin_id, champion_id, skin_name, is_custom
                                                                            }).await;
                                                                            // Auto ACK
                                                                            let ack = GossipMessage::SkinAck { target_peer_id: peer_id };
                                                                            if let Ok(json) = serde_json::to_vec(&ack) {
                                                                                sender_clone.broadcast(Bytes::from(json)).await.ok();
                                                                            }
                                                                        }
                                                                        GossipMessage::SkinAck { target_peer_id } => {
                                                                            if target_peer_id == my_node_id_clone {
                                                                                let _ = tx_clone.send(ServerMessage::SyncConfirmed {
                                                                                    peer_id: msg.delivered_from.to_string(),
                                                                                }).await;
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                            Ok(iroh_gossip::api::Event::NeighborUp(peer_id)) => {

                                                                let _ = tx_clone.send(ServerMessage::PeerJoined {
                                                                    peer_id: peer_id.to_string(),
                                                                }).await;
                                                            }
                                                            Ok(iroh_gossip::api::Event::NeighborDown(peer_id)) => {

                                                                let _ = tx_clone.send(ServerMessage::PeerLeft {
                                                                    peer_id: peer_id.to_string(),
                                                                }).await;
                                                            }
                                                            _ => {}
                                                        }
                                                    }
                                                });
                                                current_receiver_task = Some(gossip_handle);

                                                // Task to handle NodeMaster events (new peers joining later)
                                                let _gossip_clone = gossip.clone();
                                                let _tx_clone2 = to_client_tx.clone();
                                                let _topic_id_clone = topic_id;
                                                let tx_clone = to_client_tx.clone();
                                                let nm_handle = tokio::spawn(async move {
                                                    while let Some(event) = event_rx.recv().await {
                                                        match event {
                                                            NodeMasterEvent::PeerJoined(
                                                                node_id,
                                                            ) => {
                                                                // Add new peer to gossip
                                                                if let Ok(_endpoint_id) =
                                                                    EndpointId::from_str(&node_id)
                                                                {

                                                                    // Re-subscribe with new peer to add them
                                                                    // Note: iroh-gossip handles this via ALPN discovery
                                                                }
                                                            }
                                                            NodeMasterEvent::PeerLeft(node_id) => {
                                                                let _ = tx_clone
                                                                    .send(ServerMessage::PeerLeft {
                                                                        peer_id: node_id,
                                                                    })
                                                                    .await;
                                                            }
                                                            NodeMasterEvent::Disconnected => {
                                                                break;
                                                            }
                                                            NodeMasterEvent::Error(msg) => {
                                                                error!("[NM] Error: {}", msg);
                                                            }
                                                            _ => {}
                                                        }
                                                    }
                                                });
                                                nodemaster_event_task = Some(nm_handle);
                                            }
                                            Err(e) => {
                                                error!(
                                                    "[NM-JOIN] Failed to subscribe to gossip: {}",
                                                    e
                                                );
                                                let _ = to_client_tx
                                                    .send(ServerMessage::Error {
                                                        message: format!(
                                                            "Gossip subscribe failed: {}",
                                                            e
                                                        ),
                                                    })
                                                    .await;
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        error!("[NM-JOIN] Failed to connect to NodeMaster: {}", e);
                                        let _ = to_client_tx
                                            .send(ServerMessage::Error {
                                                message: format!(
                                                    "NodeMaster connection failed: {}",
                                                    e
                                                ),
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
                                        match sender.broadcast(Bytes::from(json)).await {
                                            Ok(_) => {}
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
                            ClientMessage::ReportPeerLeft { node_id } => {
                                if let Some(ref client) = _nodemaster_client {
                                    client.report_peer_left(node_id);
                                }
                            }
                            ClientMessage::LeaveRoom => {
                                // 1. Notify NodeMaster (if connected)
                                if let Some(ref client) = _nodemaster_client {
                                    client.leave();
                                }
                                _nodemaster_client = None;

                                // 2. Abort gossip receiver task
                                if let Some(handle) = current_receiver_task.take() {
                                    handle.abort();
                                }

                                // 3. Abort NodeMaster event task
                                if let Some(handle) = nodemaster_event_task.take() {
                                    handle.abort();
                                }

                                // 4. Drop gossip sender (triggers NeighborDown for peers)
                                current_topic_sender = None;
                                _current_topic = None;

                                let _ = to_client_tx.send(ServerMessage::LeftRoom).await;
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
