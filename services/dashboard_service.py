from datetime import date, timedelta

from database.db import SessionLocal

from database.models.missionary import Missionary

from database.models.secretary_work import SecretaryTask

from utils.constants import (
    WORKFLOW_STAGES,
)

from services.notification_feed_service import (
    AUTOMATION_SOURCE,
    NotificationFeedService,
    notification_sort_key,
)

from utils.logger import logger


VISIBLE_TASK_STATUSES = ("OPEN", "WAITING")


class DashboardService:
    def __init__(self, notification_feed_service=None):
        self.notification_feed_service = (
            notification_feed_service or NotificationFeedService()
        )

    def get_summary(self):
        session = SessionLocal()

        try:
            missionaries = (
                session.query(Missionary)
                .filter_by(status="ACTIVE")
                .all()
            )

            total = len(missionaries)

            # ======================================
            # Stage counts
            # ======================================

            stage_counts = {
                stage: 0
                for stage in WORKFLOW_STAGES
            }

            for missionary in missionaries:
                stage = missionary.current_stage

                if stage in stage_counts:
                    stage_counts[stage] += 1

            today = date.today()
            expiring = self.notification_feed_service.expiring_documents(
                today=today
            )
            missing_docs = self.notification_feed_service.missing_documents()
            attention_items = self.notification_feed_service.build_feed(
                today=today
            )
            attention_items.sort(key=notification_sort_key)
            recommended_tasks = self._recommended_tasks(session, today)

            return {
                "total": total,
                "stage_counts": stage_counts,
                "expiring": expiring,
                "missing_docs": missing_docs,
                "attention_items": attention_items,
                "recommended_tasks": recommended_tasks,
            }

        except Exception:
            logger.exception(
                "Failed to load dashboard data"
            )

            return {
                "total": 0,
                "stage_counts": {
                    s: 0 for s in WORKFLOW_STAGES
                },
                "expiring": [],
                "missing_docs": [],
                "attention_items": [],
                "recommended_tasks": [],
            }

        finally:
            session.close()

    def _recommended_tasks(self, session, today):
        week_end = today + timedelta(days=6 - today.weekday())
        tasks = (
            session.query(SecretaryTask)
            .filter(
                SecretaryTask.status.in_(VISIBLE_TASK_STATUSES),
                SecretaryTask.automation_source == AUTOMATION_SOURCE,
            )
            .all()
        )

        items = []
        for task in tasks:
            target_date = task.work_date or task.due_date
            if target_date is None:
                continue
            if target_date > week_end:
                continue

            days = (target_date - today).days
            items.append({
                "id": task.id,
                "title": task.title,
                "detail": task.description or self._task_detail(task, days),
                "missionary_id": task.missionary_id,
                "severity": self._severity_for_days(days),
                "days": days,
                "timing": self._timing_label(days),
            })

        return sorted(items, key=notification_sort_key)

    @staticmethod
    def _severity_for_days(days_left):
        if days_left < 0:
            return "critical"
        if days_left == 0:
            return "warning"
        return "info"

    @staticmethod
    def _task_detail(task, days):
        if days < 0:
            timing = f"{abs(days)} day(s) overdue"
        elif days == 0:
            timing = "due today"
        else:
            timing = f"planned in {days} day(s)"
        priority = (task.priority or "NORMAL").title()
        return f"{priority} task {timing}."

    @staticmethod
    def _timing_label(days):
        if days < 0:
            return f"{abs(days)} day(s) overdue"
        if days == 0:
            return "Today"
        return f"In {days} day(s)"
