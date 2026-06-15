from database.db import SessionLocal
from database.models.missionary import Missionary
from database.models.secretary_work import MissionaryGroup, MissionaryGroupMember
from services.secretary_work_service import SecretaryWorkError
from utils.logger import logger


def _clean_text(value):
    return (value or "").strip()


def _unique_ids(values):
    ids = []
    for value in values or []:
        if value is None:
            continue
        try:
            missionary_id = int(value)
        except (TypeError, ValueError):
            continue
        if missionary_id not in ids:
            ids.append(missionary_id)
    return ids


class MissionaryGroupService:
    def create_group(self, name, description="", missionary_ids=None):
        name = _clean_text(name)
        if not name:
            raise SecretaryWorkError("Group name is required.")

        session = SessionLocal()
        try:
            group = MissionaryGroup(
                name=name,
                description=_clean_text(description) or None,
            )
            session.add(group)
            session.flush()
            self._replace_members(session, group.id, missionary_ids)
            session.commit()
            session.refresh(group)
            return self._group_snapshot(group, session)
        except Exception:
            session.rollback()
            logger.exception("Failed to create missionary group")
            raise
        finally:
            session.close()

    def update_group(
        self,
        group_id,
        name=None,
        description=None,
        missionary_ids=None,
    ):
        session = SessionLocal()
        try:
            group = session.query(MissionaryGroup).filter_by(id=group_id).first()
            if group is None:
                raise SecretaryWorkError("Group not found.")

            if name is not None:
                clean_name = _clean_text(name)
                if not clean_name:
                    raise SecretaryWorkError("Group name is required.")
                group.name = clean_name
            if description is not None:
                group.description = _clean_text(description) or None
            if missionary_ids is not None:
                self._replace_members(session, group.id, missionary_ids)

            session.commit()
            session.refresh(group)
            return self._group_snapshot(group, session)
        except Exception:
            session.rollback()
            logger.exception("Failed to update missionary group")
            raise
        finally:
            session.close()

    def list_groups(self):
        session = SessionLocal()
        try:
            groups = session.query(MissionaryGroup).order_by(MissionaryGroup.name).all()
            return [self._group_snapshot(group, session) for group in groups]
        finally:
            session.close()

    def missionary_ids_for_group(self, group_id):
        session = SessionLocal()
        try:
            return self._member_ids(group_id, session)
        finally:
            session.close()

    def missionaries_for_group(self, group_id):
        session = SessionLocal()
        try:
            ids = self._member_ids(group_id, session)
            if not ids:
                return []
            missionaries = (
                session.query(Missionary)
                .filter(Missionary.id.in_(ids))
                .order_by(Missionary.full_name)
                .all()
            )
            return [
                {
                    "id": missionary.id,
                    "name": missionary.full_name,
                }
                for missionary in missionaries
            ]
        finally:
            session.close()

    def _replace_members(self, session, group_id, missionary_ids):
        session.query(MissionaryGroupMember).filter_by(group_id=group_id).delete()
        for missionary_id in _unique_ids(missionary_ids):
            session.add(
                MissionaryGroupMember(
                    group_id=group_id,
                    missionary_id=missionary_id,
                )
            )

    def _member_ids(self, group_id, session):
        rows = (
            session.query(MissionaryGroupMember.missionary_id)
            .filter_by(group_id=group_id)
            .all()
        )
        return [row[0] for row in rows]

    def _group_snapshot(self, group, session):
        members = (
            session.query(Missionary)
            .join(
                MissionaryGroupMember,
                MissionaryGroupMember.missionary_id == Missionary.id,
            )
            .filter(MissionaryGroupMember.group_id == group.id)
            .order_by(Missionary.full_name)
            .all()
        )
        return {
            "id": group.id,
            "name": group.name,
            "description": group.description or "",
            "missionary_ids": [missionary.id for missionary in members],
            "missionary_names": [missionary.full_name for missionary in members],
            "member_count": len(members),
            "created_at": group.created_at,
            "updated_at": group.updated_at,
        }
