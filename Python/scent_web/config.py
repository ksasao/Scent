"""Runtime configuration constants."""

# Serial reader
MAX_RETRIES: int = 10
BASE_RETRY_DELAY: float = 1.0   # seconds (doubles each retry, capped at 30 s)
LOG_FLUSH_INTERVAL_S: float = 1.0  # seconds between raw-log flushes

# Communication health indicator
COMM_TIMEOUT_S: float = 6.0   # seconds since last valid frame before comm_ok → False
CONNECT_GRACE_S: float = 6.0  # warm-up grace period after connect
