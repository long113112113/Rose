use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::warn;

/// Configuration
const MAX_TOTAL_CONNECTIONS: usize = 1000;
const MAX_PER_IP: usize = 5;

/// Error when connection limit is reached
#[derive(Debug)]
pub enum LimitError {
    TotalLimitReached,
    IpLimitReached,
}

impl std::fmt::Display for LimitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LimitError::TotalLimitReached => write!(f, "Maximum total connections reached"),
            LimitError::IpLimitReached => write!(f, "Maximum connections per IP reached"),
        }
    }
}

/// Connection limiter to prevent DoS attacks
#[derive(Debug, Clone)]
pub struct ConnectionLimiter {
    inner: Arc<Mutex<ConnectionLimiterInner>>,
}

#[derive(Debug)]
struct ConnectionLimiterInner {
    /// Connections per IP address
    connections_per_ip: HashMap<IpAddr, usize>,
    /// Total active connections
    total_connections: usize,
}

impl ConnectionLimiter {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(ConnectionLimiterInner {
                connections_per_ip: HashMap::new(),
                total_connections: 0,
            })),
        }
    }

    /// Try to accept a new connection from the given IP
    /// Returns Ok(()) if allowed, Err(LimitError) if rejected
    pub async fn try_connect(&self, ip: IpAddr) -> Result<(), LimitError> {
        let mut inner = self.inner.lock().await;

        // Check total limit
        if inner.total_connections >= MAX_TOTAL_CONNECTIONS {
            warn!(
                "[LIMIT] Total connection limit reached ({})",
                MAX_TOTAL_CONNECTIONS
            );
            return Err(LimitError::TotalLimitReached);
        }

        // Check per-IP limit
        let ip_count = inner.connections_per_ip.get(&ip).copied().unwrap_or(0);
        if ip_count >= MAX_PER_IP {
            warn!("[LIMIT] IP {} exceeded limit ({})", ip, MAX_PER_IP);
            return Err(LimitError::IpLimitReached);
        }

        // Accept connection
        inner.total_connections += 1;
        *inner.connections_per_ip.entry(ip).or_insert(0) += 1;

        Ok(())
    }

    /// Called when a connection is closed
    pub async fn disconnect(&self, ip: IpAddr) {
        let mut inner = self.inner.lock().await;

        inner.total_connections = inner.total_connections.saturating_sub(1);

        if let Some(count) = inner.connections_per_ip.get_mut(&ip) {
            *count = count.saturating_sub(1);
            if *count == 0 {
                inner.connections_per_ip.remove(&ip);
            }
        }
    }

    /// Get current stats
    #[allow(dead_code)]
    pub async fn stats(&self) -> (usize, usize) {
        let inner = self.inner.lock().await;
        (inner.total_connections, inner.connections_per_ip.len())
    }
}
