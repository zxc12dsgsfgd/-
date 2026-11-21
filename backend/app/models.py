from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import BIGINT, BINARY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), "mysql").with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320))
    email_norm: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[object] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[object] = mapped_column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class LoginSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), "mysql").with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32).with_variant(BINARY(32), "mysql"), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), "mysql").with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    authors: Mapped[list] = mapped_column(JSON)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(512), nullable=True)
    venue: Mapped[str | None] = mapped_column(String(500), nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    bibtex: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="unread")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class PaperFile(Base):
    __tablename__ = "paper_files"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), "mysql").with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class PdfImportBatch(Base):
    __tablename__ = 'pdf_import_batches'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    archive_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class PdfImportItem(Base):
    __tablename__ = 'pdf_import_items'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey('pdf_import_batches.id'), index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey('papers.id'), index=True)
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))


class PaperNote(Base):
    __tablename__ = 'paper_notes'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey('papers.id'), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class ReadingTemplate(Base):
    __tablename__ = 'reading_templates'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True),'mysql').with_variant(Integer,'sqlite'),primary_key=True,autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    name: Mapped[str] = mapped_column(String(200))
    fields: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp(),onupdate=func.current_timestamp())


class StructuredNote(Base):
    __tablename__ = 'structured_notes'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True),'mysql').with_variant(Integer,'sqlite'),primary_key=True,autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey('papers.id'),index=True)
    template_name: Mapped[str] = mapped_column(String(200))
    fields: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp(),onupdate=func.current_timestamp())


class Card(Base):
    __tablename__ = 'cards'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    paper_id: Mapped[int | None] = mapped_column(ForeignKey('papers.id'), nullable=True, index=True)
    source_title_snapshot: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    type: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    content_kind: Mapped[str] = mapped_column(String(20), default='unspecified', server_default='unspecified')
    verification_status: Mapped[str] = mapped_column(String(20), default='pending', server_default='pending')
    source_state: Mapped[str] = mapped_column(String(20), default='none', server_default='none')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class CardVersion(Base):
    __tablename__ = 'card_versions'
    __table_args__ = (UniqueConstraint('card_id', 'version', name='uq_card_version'),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey('cards.id'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class Tag(Base):
    __tablename__ = 'tags'
    __table_args__ = (UniqueConstraint('owner_id', 'name_norm', name='uq_tag_owner_name'),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    name_norm: Mapped[str] = mapped_column(String(300))


class PaperTag(Base):
    __tablename__ = 'paper_tags'
    paper_id: Mapped[int] = mapped_column(ForeignKey('papers.id'), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey('tags.id'), primary_key=True)


class CardTag(Base):
    __tablename__ = 'card_tags'
    card_id: Mapped[int] = mapped_column(ForeignKey('cards.id'), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey('tags.id'), primary_key=True)


class CardRelation(Base):
    __tablename__ = 'card_relations'
    __table_args__ = (UniqueConstraint('owner_id','source_card_id','target_card_id','relation_type',name='uq_card_relation'),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    source_card_id: Mapped[int] = mapped_column(ForeignKey('cards.id'), index=True)
    target_card_id: Mapped[int] = mapped_column(ForeignKey('cards.id'), index=True)
    relation_type: Mapped[str] = mapped_column(String(20))


class Workflow(Base):
    __tablename__='workflows'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True),'mysql').with_variant(Integer,'sqlite'),primary_key=True,autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean,default=True)
    trigger: Mapped[str] = mapped_column(String(40))
    filter_value: Mapped[str | None] = mapped_column(String(40),nullable=True)
    message: Mapped[str] = mapped_column(String(1000))
    action_type: Mapped[str] = mapped_column(String(30),default='notify')
    action_value: Mapped[str | None] = mapped_column(String(100),nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp(),onupdate=func.current_timestamp())


class WorkflowEvent(Base):
    __tablename__='workflow_events'
    id: Mapped[str] = mapped_column(String(36),primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    trigger: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp())


class WorkflowRun(Base):
    __tablename__='workflow_runs'
    __table_args__=(UniqueConstraint('workflow_id','event_id',name='uq_workflow_event'),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True),'mysql').with_variant(Integer,'sqlite'),primary_key=True,autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    workflow_id: Mapped[int | None] = mapped_column(ForeignKey('workflows.id',ondelete='SET NULL'),nullable=True,index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey('workflow_events.id'),index=True)
    workflow_name: Mapped[str] = mapped_column(String(200))
    result: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp())


class Notification(Base):
    __tablename__='notifications'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True),'mysql').with_variant(Integer,'sqlite'),primary_key=True,autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('workflow_runs.id'),unique=True)
    message: Mapped[str] = mapped_column(String(1000))
    read_at: Mapped[datetime | None] = mapped_column(DateTime,nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp())


class ReadingPlan(Base):
    __tablename__='reading_plans'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True),'mysql').with_variant(Integer,'sqlite'),primary_key=True,autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    name: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date,nullable=True)
    target_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp(),onupdate=func.current_timestamp())


class ReadingPlanItem(Base):
    __tablename__='reading_plan_items'
    plan_id: Mapped[int] = mapped_column(ForeignKey('reading_plans.id'),primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey('papers.id'),primary_key=True)


class ResearchProject(Base):
    __tablename__ = 'research_projects'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default='')
    objective: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='active')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class ProjectPaper(Base):
    __tablename__ = 'project_papers'
    project_id: Mapped[int] = mapped_column(ForeignKey('research_projects.id', ondelete='CASCADE'), primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey('papers.id', ondelete='CASCADE'), primary_key=True)


class ProjectCard(Base):
    __tablename__ = 'project_cards'
    project_id: Mapped[int] = mapped_column(ForeignKey('research_projects.id', ondelete='CASCADE'), primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey('cards.id', ondelete='CASCADE'), primary_key=True)


class ProjectPlan(Base):
    __tablename__ = 'project_plans'
    project_id: Mapped[int] = mapped_column(ForeignKey('research_projects.id', ondelete='CASCADE'), primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey('reading_plans.id', ondelete='CASCADE'), primary_key=True)


class ProjectDraft(Base):
    __tablename__ = 'project_drafts'
    project_id: Mapped[int] = mapped_column(ForeignKey('research_projects.id', ondelete='CASCADE'), primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey('drafts.id', ondelete='CASCADE'), primary_key=True)


class PaperStatusEvent(Base):
    __tablename__='paper_status_events'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True),'mysql').with_variant(Integer,'sqlite'),primary_key=True,autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey('papers.id'),index=True)
    to_status: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(DateTime,index=True)


class SchedulerFailure(Base):
    __tablename__='scheduler_failures'
    event_id: Mapped[str] = mapped_column(String(36),primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    workflow_id: Mapped[int | None] = mapped_column(ForeignKey('workflows.id',ondelete='SET NULL'),nullable=True)
    workflow_name: Mapped[str] = mapped_column(String(200))
    object_id: Mapped[int] = mapped_column(BigInteger)
    error_code: Mapped[str] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer)
    next_retry_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime,nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class WorkflowSyncFailure(Base):
    __tablename__ = 'workflow_sync_failures'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    workflow_name: Mapped[str] = mapped_column(String(200))
    trigger: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_code: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class AIConfig(Base):
    __tablename__='ai_configs'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True),'mysql').with_variant(Integer,'sqlite'),primary_key=True,autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),unique=True)
    base_url: Mapped[str] = mapped_column(String(2048))
    model_name: Mapped[str] = mapped_column(String(255))
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    key_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)


class Draft(Base):
    __tablename__='drafts'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True),'mysql').with_variant(Integer,'sqlite'),primary_key=True,autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    task_type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20),default='draft')
    created_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp(),onupdate=func.current_timestamp())


class EvidenceLink(Base):
    __tablename__ = 'evidence_links'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    card_id: Mapped[int | None] = mapped_column(ForeignKey('cards.id', ondelete='CASCADE'), nullable=True, index=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey('drafts.id', ondelete='CASCADE'), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_snapshot: Mapped[dict] = mapped_column(JSON)
    location: Mapped[str] = mapped_column(String(200), default='')
    excerpt: Mapped[str] = mapped_column(Text, default='')
    note: Mapped[str] = mapped_column(Text, default='')
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class EvidenceChange(Base):
    __tablename__ = 'evidence_changes'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    link_id: Mapped[int] = mapped_column(ForeignKey('evidence_links.id', ondelete='CASCADE'), index=True)
    action: Mapped[str] = mapped_column(String(20))
    detail: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class AIJob(Base):
    __tablename__='ai_jobs'
    __table_args__=(Index('ix_ai_jobs_owner_created','owner_id','created_at'),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True),'mysql').with_variant(Integer,'sqlite'),primary_key=True,autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    task_type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    base_url: Mapped[str] = mapped_column(String(2048))
    model_name: Mapped[str] = mapped_column(String(255))
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    key_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(20),default='pending',index=True)
    error_code: Mapped[str | None] = mapped_column(String(50),nullable=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey('drafts.id',ondelete='SET NULL'),nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime,nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.current_timestamp())


class Share(Base):
    __tablename__ = 'shares'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32).with_variant(BINARY(32), 'mysql'), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    allow_comments: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class ShareItem(Base):
    __tablename__ = 'share_items'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    share_id: Mapped[int] = mapped_column(ForeignKey('shares.id'), index=True)
    item_type: Mapped[str] = mapped_column(String(20))
    snapshot: Mapped[dict] = mapped_column(JSON)


class ShareComment(Base):
    __tablename__ = 'share_comments'
    id: Mapped[int] = mapped_column(BigInteger().with_variant(BIGINT(unsigned=True), 'mysql').with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    share_id: Mapped[int] = mapped_column(ForeignKey('shares.id'), index=True)
    share_item_id: Mapped[int] = mapped_column(ForeignKey('share_items.id'))
    author_name: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
