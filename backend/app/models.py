import uuid
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func, Boolean
from sqlalchemy.orm import relationship
from core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="user")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    visibility = Column(string(20), default="private")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", backrefs="projects")

class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    context_id = Column(UUID(as_uuid=True), ForeignKey("contexts.id", ondelete="SET NULL"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    status = Column(String(30), default="success")
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", backref="sync_logs")
    user = relationship("User")
    context = relationship("Context")

class Context(Base):
    __tablename__ = "contexts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    version_tag = Column(String(50), index=True)
    mesh_data = Column(JSONB, nullable=False)
    checksum = Column(String(64))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    project = relationship("Project", backref="contexts")

class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    context_id = Column(UUID(as_uuid=True), ForeignKey("contexts.id", ondelete="CASCADE"))
    vector = Column(ARRAY(Float))
    model = Column(String(100))
    created_at = Column(DateTime(timezone=True), default=func.now())

    context = relationship("Context", backref="embeddings")
