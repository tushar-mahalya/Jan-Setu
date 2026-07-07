from uuid import uuid4

import anyio
from sqlalchemy.dialects import postgresql

from jan_setu.repositories.webhook_events import claim_event, fetch_unprocessed_event_ids


def test_claim_event_compiled_sql_updates_lease_fields():
    class Result:
        def one_or_none(self):
            return ({"entry": []}, 2)

    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    session = Session()

    async def run():
        return await claim_event(session, event_id=uuid4(), lease_seconds=30)

    claimed = anyio.run(run)

    compiled = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "locked_until" in compiled
    assert "attempt_count" in compiled
    assert "processed_at" in compiled
    assert claimed == {"payload": {"entry": []}, "attempt_count": 2}


def test_claim_event_returns_none_when_lease_not_won():
    class Result:
        def one_or_none(self):
            return None

    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    session = Session()

    async def run():
        return await claim_event(session, event_id=uuid4(), lease_seconds=30)

    claimed = anyio.run(run)

    assert claimed is None


def test_fetch_unprocessed_event_ids_compiled_sql_orders_by_created_at():
    expected_ids = [uuid4(), uuid4()]

    class ScalarsResult:
        def all(self):
            return expected_ids

    class Result:
        def scalars(self):
            return ScalarsResult()

    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    session = Session()

    async def run():
        return await fetch_unprocessed_event_ids(session, limit=5)

    ids = anyio.run(run)

    compiled = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "processed_at" in compiled
    assert "ORDER BY webhook_events.created_at" in compiled
    assert ids == expected_ids
