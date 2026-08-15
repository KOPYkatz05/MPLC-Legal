"""Non-widget state owned by the Missionary Detail page."""

from dataclasses import dataclass, field


@dataclass
class MissionaryDetailState:
    """Authoritative client-side state for one detail-page instance."""

    requested_missionary_id: int | None = None
    detail_loaded: bool = False
    snapshot_cache: dict = field(default_factory=dict)
    cache_ttl_seconds: float = 15.0
    workflow_records: list = field(default_factory=list)
    document_records: dict = field(default_factory=dict)

    def begin_request(self, missionary_id):
        self.requested_missionary_id = missionary_id

    def accepts(self, missionary_id):
        return missionary_id == self.requested_missionary_id

    def clear_rendered_records(self):
        self.workflow_records = []
        self.document_records = {}
