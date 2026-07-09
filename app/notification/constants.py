MAX_TITLE_LENGTH = 255
MAX_MESSAGE_LENGTH = 2000

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100

# Performance targets from the spec, used only for logging/observability
# (e.g. flagging a delivery attempt that exceeded target in logs) — not
# enforced as hard timeouts.
NOTIFICATION_DELIVERY_TARGET_SECONDS = 2
DASHBOARD_REFRESH_TARGET_SECONDS = 1

# Automation retry engine defaults.
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_BACKOFF_SECONDS = 60  # multiplied by 2^attempt, capped below
MAX_RETRY_BACKOFF_SECONDS = 3600

RETRYABLE_REASONS = frozenset(
    {
        "temporary_network_failure",
        "browser_crash",
        "platform_timeout",
        "api_timeout",
        "email_sync_failure",
    }
)

# Redis key prefix for the WebSocket pub/sub channel used to push live
# notification events to connected clients (consumed by a separate
# WebSocket gateway process, not part of this module).
WEBSOCKET_NOTIFICATION_CHANNEL_PREFIX = "ws:notifications:user:"
