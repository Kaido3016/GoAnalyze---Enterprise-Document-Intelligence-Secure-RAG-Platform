"""Repository layer mediating between the domain/API layer and the ORM.

Each repository takes an ``AsyncSession`` (request-scoped, injected via
FastAPI's ``Depends(get_session)``) and exposes coroutine methods that
return/accept the Pydantic domain models defined in ``gov_platform.models``,
keeping ORM details out of the API layer.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditEvent, ClassificationLevel, DocumentRecord
from .models import AuditChainStateORM, AuditEventORM, CaseAssignmentORM, DocumentORM, UserORM


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, record: DocumentRecord) -> DocumentRecord:
        orm = DocumentORM(
            id=record.id,
            tenant_id=record.tenant_id,
            case_id=record.case_id,
            filename=record.filename,
            content_type=record.content_type,
            classification=record.classification.value,
            sha256=record.sha256,
            object_uri=record.object_uri,
            doc_metadata=record.metadata,
            version=record.version,
            lineage_id=record.lineage_id,
            created_at=record.created_at,
        )
        self._session.add(orm)
        await self._session.commit()
        return record

    async def get(self, document_id: UUID) -> DocumentRecord | None:
        orm = await self._session.get(DocumentORM, document_id)
        if orm is None:
            return None
        return self._to_domain(orm)

    async def get_many(self, document_ids: list[UUID]) -> dict[UUID, DocumentRecord]:
        if not document_ids:
            return {}
        result = await self._session.execute(select(DocumentORM).where(DocumentORM.id.in_(document_ids)))
        return {orm.id: self._to_domain(orm) for orm in result.scalars().all()}

    async def list_for_tenant(
        self,
        tenant_id: str,
        page: int,
        page_size: int,
        classification: str | None = None,
        content_type: str | None = None,
        case_id: UUID | None = None,
        exclude_protected_b: bool = False,
    ) -> tuple[list[DocumentRecord], int]:
        """List documents with server-enforced tenant and access filters."""
        conditions = [DocumentORM.tenant_id == tenant_id]
        if classification:
            conditions.append(DocumentORM.classification == classification)
        if content_type:
            conditions.append(DocumentORM.content_type == content_type)
        if case_id:
            conditions.append(DocumentORM.case_id == case_id)
        if exclude_protected_b:
            conditions.append(DocumentORM.classification != ClassificationLevel.protected_b.value)

        count_result = await self._session.execute(
            select(func.count()).select_from(DocumentORM).where(*conditions)
        )
        total = count_result.scalar_one()
        result = await self._session.execute(
            select(DocumentORM)
            .where(*conditions)
            .order_by(DocumentORM.created_at.desc(), DocumentORM.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_domain(orm) for orm in result.scalars().all()], total

    async def search(
        self,
        tenant_id: str,
        query: str,
        page: int,
        page_size: int,
        classification: str | None = None,
        content_type: str | None = None,
    ) -> tuple[list[DocumentRecord], int]:
        """DB-backed fallback search (ILIKE on filename), always scoped to
        ``tenant_id`` server-side so a caller can never search across
        tenants regardless of what filters they pass."""
        conditions = [DocumentORM.tenant_id == tenant_id]
        if query:
            conditions.append(DocumentORM.filename.ilike(f"%{query}%"))
        if classification:
            conditions.append(DocumentORM.classification == classification)
        if content_type:
            conditions.append(DocumentORM.content_type == content_type)

        count_result = await self._session.execute(
            select(func.count()).select_from(DocumentORM).where(*conditions)
        )
        total = count_result.scalar_one()

        result = await self._session.execute(
            select(DocumentORM)
            .where(*conditions)
            .order_by(DocumentORM.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        records = [self._to_domain(orm) for orm in result.scalars().all()]
        return records, total

    @staticmethod
    def _to_domain(orm: DocumentORM) -> DocumentRecord:
        return DocumentRecord(
            id=orm.id,
            tenant_id=orm.tenant_id,
            case_id=orm.case_id,
            filename=orm.filename,
            content_type=orm.content_type,
            classification=ClassificationLevel(orm.classification),
            sha256=orm.sha256,
            object_uri=orm.object_uri,
            metadata=orm.doc_metadata,
            version=orm.version,
            lineage_id=orm.lineage_id,
            created_at=orm.created_at,
        )


class CaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_assignment(
        self,
        case_id: UUID,
        tenant_id: str,
        assignee: str,
        queue: str,
        status: str,
        due_at: datetime,
        escalation_at: datetime,
    ) -> CaseAssignmentORM:
        orm = CaseAssignmentORM(
            case_id=case_id,
            tenant_id=tenant_id,
            assignee=assignee,
            queue=queue,
            status=status,
            due_at=due_at,
            escalation_at=escalation_at,
        )
        self._session.add(orm)
        await self._session.commit()
        return orm


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_from_token(
        self, subject: str, tenant_id: str, ministry: str, email: str | None, roles: list[str]
    ) -> UserORM:
        result = await self._session.execute(select(UserORM).where(UserORM.subject == subject))
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = UserORM(subject=subject, tenant_id=tenant_id, ministry=ministry, email=email, roles=roles)
            self._session.add(orm)
        else:
            orm.tenant_id = tenant_id
            orm.ministry = ministry
            orm.email = email
            orm.roles = roles
        await self._session.commit()
        return orm


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_with_chain_lock(self, event: AuditEvent, compute_hash) -> AuditEvent:
        """Atomically read the current chain head, hash the event against
        it, insert the event, and advance the head -- all under a
        ``SELECT ... FOR UPDATE`` row lock on this tenant's single
        ``audit_chain_state`` row, within one transaction.

        This is what actually prevents two concurrent appends for the same
        tenant from both reading the same "latest" event and forking the
        chain: the second writer blocks on the row lock until the first
        commits, then sees the first writer's update. Different tenants
        never block each other (each has its own row).

        On non-Postgres dialects (SQLite, used only in the test suite,
        which never exercises true multi-connection concurrency against
        it), falls back to a plain read with no lock -- there are no
        concurrent writers to protect against there in practice.
        """
        dialect = self._session.bind.dialect.name if self._session.bind is not None else None

        if dialect == "postgresql":
            # Ensure the chain-state row exists before locking it.
            # ON CONFLICT DO NOTHING avoids a duplicate-key race if two
            # tenants' first-ever events happen to arrive concurrently.
            await self._session.execute(
                pg_insert(AuditChainStateORM)
                .values(tenant_id=event.tenant_id, latest_event_hash=None)
                .on_conflict_do_nothing(index_elements=["tenant_id"])
            )
            result = await self._session.execute(
                select(AuditChainStateORM).where(AuditChainStateORM.tenant_id == event.tenant_id).with_for_update()
            )
            chain_state = result.scalar_one()
            previous_hash = chain_state.latest_event_hash
        else:
            chain_state = None
            latest = await self.latest_for_tenant(event.tenant_id)
            previous_hash = latest.event_hash if latest else None

        event.previous_hash = previous_hash
        event.event_hash = compute_hash(event)

        self._session.add(self._to_orm(event))
        if chain_state is not None:
            chain_state.latest_event_hash = event.event_hash
        await self._session.commit()
        return event

    @staticmethod
    def _to_orm(event: AuditEvent) -> AuditEventORM:
        return AuditEventORM(
            id=event.id,
            tenant_id=event.tenant_id,
            actor=event.actor,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            purpose=event.purpose,
            trace_id=event.trace_id,
            timestamp=event.timestamp,
            details=event.details,
            previous_hash=event.previous_hash,
            event_hash=event.event_hash,
        )

    async def list_for_tenant(self, tenant_id: str) -> list[AuditEvent]:
        """Unbounded fetch -- kept only for internal callers (e.g. the audit
        hash-chain verification tooling) that genuinely need every event.
        The public API route uses ``list_for_tenant_paginated`` instead."""
        result = await self._session.execute(
            select(AuditEventORM).where(AuditEventORM.tenant_id == tenant_id).order_by(AuditEventORM.timestamp)
        )
        return [self._orm_to_domain(orm) for orm in result.scalars().all()]

    async def list_for_tenant_paginated(
        self, tenant_id: str, page: int, page_size: int
    ) -> tuple[list[AuditEvent], int]:
        """Server-side paginated audit query.

        Uses a separate ``COUNT(*)`` for the total (no rows loaded for the
        count) and ``LIMIT``/``OFFSET`` for the page itself, ordered by
        ``(timestamp, id)`` -- the id tiebreaker keeps ordering fully
        deterministic even when two events share a timestamp, which a
        timestamp-only order would not guarantee across pages. Tenant
        isolation is enforced by the same ``tenant_id`` filter used
        everywhere else in this repository -- unchanged from before.
        """
        condition = AuditEventORM.tenant_id == tenant_id

        count_result = await self._session.execute(
            select(func.count()).select_from(AuditEventORM).where(condition)
        )
        total = count_result.scalar_one()

        result = await self._session.execute(
            select(AuditEventORM)
            .where(condition)
            .order_by(AuditEventORM.timestamp, AuditEventORM.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [self._orm_to_domain(orm) for orm in result.scalars().all()]
        return items, total

    async def latest_for_tenant(self, tenant_id: str) -> AuditEvent | None:
        result = await self._session.execute(
            select(AuditEventORM)
            .where(AuditEventORM.tenant_id == tenant_id)
            .order_by(AuditEventORM.timestamp.desc())
            .limit(1)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._orm_to_domain(orm)

    @staticmethod
    def _orm_to_domain(orm: AuditEventORM) -> AuditEvent:
        return AuditEvent(
            id=orm.id,
            tenant_id=orm.tenant_id,
            actor=orm.actor,
            action=orm.action,
            resource_type=orm.resource_type,
            resource_id=orm.resource_id,
            purpose=orm.purpose,
            trace_id=orm.trace_id,
            timestamp=orm.timestamp,
            details=orm.details,
            previous_hash=orm.previous_hash,
            event_hash=orm.event_hash,
        )
