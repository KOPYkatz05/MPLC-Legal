APP_VERSION = "0.2.1"
API_VERSION = "1"
SCHEMA_VERSION = 1

# Client/server releases are allowed to roll out independently while they use a
# compatible API.  Keep this range wider than one value when a future API
# release remains backward compatible.
MIN_SUPPORTED_SERVER_API_VERSION = "1"
MAX_SUPPORTED_SERVER_API_VERSION = "1"

# This responsive-client/server rollout is release-locked: the server tells
# older installed clients to update to this same application version, while
# clients also reject a server from a different application release.
MIN_SUPPORTED_CLIENT_VERSION = APP_VERSION
