import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def make_uuid() -> str:
    return str(uuid.uuid4())

class CEFRLevel(enum.Enum):
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"

class ScheduledSessionStatus(enum.Enum):
    INIT = "INIT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class SessionStatus(enum.Enum):
    WARMUP = "WARMUP"
    DRILL = "DRILL"
    ROLEPLAY = "ROLEPLAY"
    WRAPUP = "WRAPUP"
    PAUSE = "PAUSE"

class Speaker(enum.Enum):
    USER = "USER"
    AI = "AI"

class StrikeSeverity(enum.Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"

class User(Base):
    __tablename__ = "users"

    user_id = Column(String(255), primary_key=True, default=make_uuid)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    push_token = Column(String(255))
    timezone = Column(String(50), default="UTC")

    preferences = relationship("UserPreferences", uselist=False, back_populates="user")
    scheduled_sessions = relationship("ScheduledSession", back_populates="user")
    session_instances = relationship("SessionInstance", back_populates="user")
    strike_logs = relationship("StrikeLog", back_populates="user")
    session_assessments = relationship("SessionAssessment", back_populates="user")

class UserPreferences(Base):
    __tablename__ = "user_preferences"

    user_id = Column(String(255), ForeignKey("users.user_id"), primary_key=True)
    cefr_level = Column(Enum(CEFRLevel), nullable=False)
    preferred_language = Column(String(10), nullable=False)
    timezone = Column(String(50), default="UTC")
    notification_preferences = Column(Text)  # JSON
    auto_record = Column(Boolean, default=False)
    enable_socratic_check = Column(Boolean, default=True)
    enable_drift_check = Column(Boolean, default=True)
    max_strikes = Column(Integer, nullable=False, default=5)
    strike_lockout_duration_ms = Column(Integer, nullable=False, default=3600000)
    srs_interval_pattern = Column(String(100), default="1,3,7,14,30")
    last_updated = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="preferences")

class ScheduledSession(Base):
    __tablename__ = "scheduled_sessions"

    scheduled_session_id = Column(String(255), primary_key=True, default=make_uuid)
    user_id = Column(String(255), ForeignKey("users.user_id"), nullable=False)
    scenario_id = Column(String(255), nullable=False)
    cron_trigger = Column(String(100), nullable=False)
    delivery_mode = Column(String(20), nullable=False, default="PUSH_NOTIFICATION")
    status = Column(Enum(ScheduledSessionStatus), nullable=False, default=ScheduledSessionStatus.INIT)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="scheduled_sessions")
    session_instances = relationship("SessionInstance", back_populates="scheduled_session")
    scenario = relationship("Scenario", back_populates="scheduled_sessions")

class Scenario(Base):
    __tablename__ = "scenarios"

    scenario_id = Column(String(255), primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    cefr_level = Column(Enum(CEFRLevel), nullable=False)
    topic = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    scheduled_sessions = relationship("ScheduledSession", back_populates="scenario")
    weak_lexicon = relationship("WeakLexicon", back_populates="scenario")

class SessionInstance(Base):
    __tablename__ = "session_instances"

    session_id = Column(String(255), primary_key=True, default=make_uuid)
    scheduled_session_id = Column(String(255), ForeignKey("scheduled_sessions.scheduled_session_id"), nullable=False)
    user_id = Column(String(255), ForeignKey("users.user_id"), nullable=False)
    status = Column(Enum(SessionStatus), nullable=False, default=SessionStatus.WARMUP)
    start_time = Column(DateTime, nullable=False, default=utc_now)
    end_time = Column(DateTime)
    duration_ms = Column(Integer)
    transcript_url = Column(String(500))
    assessment_url = Column(String(500))
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    strike_count = Column(Integer, nullable=False, default=0)
    is_locked = Column(Boolean, nullable=False, default=False)
    locked_until = Column(DateTime)

    user = relationship("User", back_populates="session_instances")
    scheduled_session = relationship("ScheduledSession", back_populates="session_instances")
    transcript_chunks = relationship("TranscriptChunk", back_populates="session_instance")
    session_assessment = relationship("SessionAssessment", uselist=False, back_populates="session_instance")
    strike_logs = relationship("StrikeLog", back_populates="session_instance")

class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"

    chunk_id = Column(String(255), primary_key=True, default=make_uuid)
    session_id = Column(String(255), ForeignKey("session_instances.session_id"), nullable=False)
    text = Column(Text, nullable=False)
    speaker = Column(Enum(Speaker), nullable=False)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=utc_now)

    session_instance = relationship("SessionInstance", back_populates="transcript_chunks")

class WeakLexicon(Base):
    __tablename__ = "weak_lexicon"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey("users.user_id"), nullable=False)
    scenario_id = Column(String(255), ForeignKey("scenarios.scenario_id"), nullable=False)
    word = Column(String(255), nullable=False)
    language = Column(String(10), nullable=False)
    error_count = Column(Integer, nullable=False, default=0)
    last_reviewed_at = Column(DateTime)
    next_review_epoch_ms = Column(Integer, nullable=False)
    ease_factor = Column(Float, default=2.5)
    interval_days = Column(Integer, default=1)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User")
    scenario = relationship("Scenario", back_populates="weak_lexicon")

    __table_args__ = (UniqueConstraint('user_id', 'word', 'language', name='_user_word_lang_uc'),)

class StrikeLog(Base):
    __tablename__ = "strike_logs"

    strike_id = Column(String(255), primary_key=True, default=make_uuid)
    user_id = Column(String(255), ForeignKey("users.user_id"), nullable=False)
    session_id = Column(String(255), ForeignKey("session_instances.session_id"), nullable=True)
    severity = Column(Enum(StrikeSeverity), nullable=False)
    drift_type = Column(String(50))
    context = Column(Text)
    resolved = Column(Boolean, default=False)
    resolved_by = Column(String(255))
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="strike_logs")
    session_instance = relationship("SessionInstance", back_populates="strike_logs")

class SessionAssessment(Base):
    __tablename__ = "session_assessments"

    assessment_id = Column(String(255), primary_key=True, default=make_uuid)
    session_id = Column(String(255), ForeignKey("session_instances.session_id"), nullable=False)
    user_id = Column(String(255), ForeignKey("users.user_id"), nullable=False)
    fluency_score = Column(Float)
    accuracy_score = Column(Float)
    coherence_score = Column(Float)
    overall_score = Column(Float)
    feedback = Column(Text)
    created_at = Column(DateTime, default=utc_now)

    session_instance = relationship("SessionInstance", back_populates="session_assessment")
    user = relationship("User", back_populates="session_assessments")
