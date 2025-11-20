"""
LevelUp App Schemas (MongoDB via Pydantic)

Each Pydantic model below corresponds to a collection. Collection name is the lowercase
of the class name (e.g., User -> "user").
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime


class User(BaseModel):
    name: str
    email: EmailStr
    handle: Optional[str] = None
    avatar: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)


class Profile(BaseModel):
    user_id: str
    college: Optional[str] = None
    year: Optional[str] = None
    skills_progress: Dict[str, Any] = Field(default_factory=dict)
    coins: int = 0
    xp: int = 0
    level: int = 1
    streaks: Dict[str, Any] = Field(default_factory=lambda: {"current": 0, "best": 0, "grace_tokens": 2})


TaskType = Literal["daily", "todo", "habit"]
TaskStatus = Literal["pending", "in_progress", "completed", "archived"]


class Task(BaseModel):
    owner_id: str
    type: TaskType
    title: str
    notes: Optional[str] = None
    est_minutes: Literal[5, 15, 30] = 15
    category: Optional[str] = None
    attachments: List[str] = Field(default_factory=list)
    status: TaskStatus = "pending"
    recurrence: Optional[str] = None
    xp_value: int = 10
    due_at: Optional[datetime] = None


class Module(BaseModel):
    title: str
    duration_minutes: Literal[5, 10, 15, 20, 30] = 15
    type: str = "micro"
    content_url: str
    xp_reward: int = 25
    certificate_id: Optional[str] = None


class Story(BaseModel):
    chapter: int
    content: str
    unlock_condition: Dict[str, Any] = Field(default_factory=dict)


class Club(BaseModel):
    name: str
    members: List[str] = Field(default_factory=list)
    privacy: Literal["private", "college", "public"] = "private"
    leaderboard: List[Dict[str, Any]] = Field(default_factory=list)


class Transaction(BaseModel):
    user_id: str
    type: str
    amount: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CoachSession(BaseModel):
    user_id: str
    prompt: str
    response: Dict[str, Any]
    timestamp: datetime
