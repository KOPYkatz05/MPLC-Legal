from database.db import SessionLocal
from database.models.document import Document
from database.models.missionary import Missionary
from database.models.secretary_work import SecretaryTask
from database.models.stage_history import StageHistory
from services.remote_service import RemoteServiceMixin


class ReportsDataService(RemoteServiceMixin):
    REMOTE_SERVICE = "reports"
    REMOTE_METHODS = frozenset({"get_data"})

    def get_data(self):
        session = SessionLocal()
        try:
            return {
                "missionaries": session.query(Missionary).filter_by(status="ACTIVE").all(),
                "documents": session.query(Document).all(),
                "stage_history": session.query(StageHistory).all(),
                "completed_tasks": (
                    session.query(SecretaryTask)
                    .filter(SecretaryTask.completed_at.isnot(None))
                    .all()
                ),
            }
        finally:
            session.close()
