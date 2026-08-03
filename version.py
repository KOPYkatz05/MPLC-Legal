APP_VERSION = "0.3.1"
API_VERSION = "2"
SCHEMA_VERSION = 3

# Client/server releases are allowed to roll out independently while they use a
# compatible API.  Keep this range wider than one value when a future API
# release remains backward compatible.
MIN_SUPPORTED_SERVER_API_VERSION = "2"
MAX_SUPPORTED_SERVER_API_VERSION = "2"

# A server can require a minimum client version. Newer clients may continue to
# work with an older server when their API versions remain compatible.
MIN_SUPPORTED_CLIENT_VERSION = APP_VERSION
