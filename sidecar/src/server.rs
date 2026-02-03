use std::sync::Arc;

use bytes::Bytes;
use futures::{SinkExt, StreamExt};
use iroh_gossip::net::Gossip;
use tokio::net::TcpStream;
use tokio::sync::mpsc;
use tokio_tungstenite::accept_async;
use tracing::{error, info};

use crate::protocol::{ClientMessage, GossipMessage, ServerMessage};

pub async fn handle_connection(stream: TcpStream, gossip: Gossip, my_node_id: String) {
    let ws_stream = match accept_async(stream).await {
        Ok(ws) => ws,
        Err(e) => {
            error!("Error during websocket handshake: {}", e);
            return;
        }
    };

    info!("New WebSocket connection");

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
                                let ticket = hex::encode(topic_bytes);

                                // subscribe
                                match gossip.subscribe(topic_id, vec![]).await {
                                    Ok(sub) => {
                                        _current_topic = Some(topic_id);
                                        let (sender, mut stream) = sub.split();
                                        current_topic_sender = Some(sender);

                                        // Handle receiver
                                        let tx_clone = to_client_tx.clone();
                                        let handle = tokio::spawn(async move {
                                            while let Some(event_res) = stream.next().await {
                                                if let Ok(iroh_gossip::api::Event::Received(msg)) =
                                                    event_res
                                                {
                                                    if let Ok(gossip_msg) =
                                                        serde_json::from_slice::<GossipMessage>(
                                                            &msg.content,
                                                        )
                                                    {
                                                        let _ = tx_clone
                                                            .send(ServerMessage::RemoteSkinUpdate {
                                                                peer_id: gossip_msg.peer_id,
                                                                skin_id: gossip_msg.skin_id,
                                                                champion_id: gossip_msg.champion_id,
                                                            })
                                                            .await;
                                                    }
                                                } else {
                                                    break;
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
                            ClientMessage::JoinTicket(ticket) => {
                                if let Some(array) =
                                    hex::decode(&ticket).ok().and_then(|v| v.try_into().ok())
                                {
                                    // Abort previous receiver task if exists
                                    if let Some(handle) = current_receiver_task.take() {
                                        handle.abort();
                                    }

                                    let array: [u8; 32] = array;
                                    let topic_id = iroh_gossip::TopicId::from(array);

                                    match gossip.subscribe(topic_id, vec![]).await {
                                        Ok(sub) => {
                                            _current_topic = Some(topic_id);
                                            let (sender, mut stream) = sub.split();
                                            current_topic_sender = Some(sender);

                                            let tx_clone = to_client_tx.clone();
                                            let handle = tokio::spawn(async move {
                                                while let Some(event_res) = stream.next().await {
                                                    if let Ok(iroh_gossip::api::Event::Received(
                                                        msg,
                                                    )) = event_res
                                                    {
                                                        if let Ok(gossip_msg) =
                                                            serde_json::from_slice::<GossipMessage>(
                                                                &msg.content,
                                                            )
                                                        {
                                                            let _ = tx_clone.send(ServerMessage::RemoteSkinUpdate {
                                                                    peer_id: gossip_msg.peer_id,
                                                                    skin_id: gossip_msg.skin_id,
                                                                    champion_id: gossip_msg.champion_id
                                                                }).await;
                                                        }
                                                    } else {
                                                        break;
                                                    }
                                                }
                                            });
                                            current_receiver_task = Some(handle);
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
                            }
                            ClientMessage::UpdateSkin {
                                skin_id,
                                champion_id,
                            } => {
                                if let Some(sender) = &current_topic_sender {
                                    let payload = GossipMessage {
                                        peer_id: my_node_id.clone(),
                                        skin_id,
                                        champion_id,
                                    };
                                    if let Ok(json) = serde_json::to_vec(&payload) {
                                        sender.broadcast(Bytes::from(json)).await.ok();
                                        info!("Broadcasted skin update");
                                    }
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
