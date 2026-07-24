APP_VERSION = "0.1.3"
API_VERSION = "1"
SCHEMA_VERSION = 1

# Client/server releases are allowed to roll out independently while they use a
# compatible API.  Keep this range wider than one value when a future API
# release remains backward compatible.
MIN_SUPPORTED_SERVER_API_VERSION = "1"
MAX_SUPPORTED_SERVER_API_VERSION = "1"

# The server publishes this floor to connected clients.  Raise it only when an
# older installed client can no longer safely use the current API.
MIN_SUPPORTED_CLIENT_VERSION = "0.1.0"
