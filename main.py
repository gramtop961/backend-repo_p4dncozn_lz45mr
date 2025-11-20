import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from database import db, create_document, get_documents

app = FastAPI(title="LevelUp API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------
# Feature Flags / Config
# ----------------------
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"
AI_ENABLED = os.getenv("FEATURE_AI_COACH", "1") == "1"
HEAVY_ANIMATIONS = os.getenv("FEATURE_HEAVY_ANIM", "1") == "1"

# ----------------------
# Helpers
# ----------------------

def xp_for_level(level: int) -> int:
    # Exponential XP requirement
    return round(100 * (1.25 ** level))


def apply_xp_and_level(profile: Dict[str, Any], gained_xp: int) -> Dict[str, Any]:
    profile["xp"] = int(profile.get("xp", 0)) + int(gained_xp)
    leveled_up = False
    while profile["xp"] >= xp_for_level(profile.get("level", 1)):
        profile["xp"] -= xp_for_level(profile.get("level", 1))
        profile["level"] = int(profile.get("level", 1)) + 1
        leveled_up = True
    if leveled_up:
        profile["coins"] = int(profile.get("coins", 0)) + 5
    return {"profile": profile, "leveled_up": leveled_up}


def get_user_from_token(x_token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not x_token:
        return None
    users = list(db.user.find({"_id": {"$exists": True}})) if db else []
    # In demo mode, token is user_id string
    try:
        from bson import ObjectId
        user = db.user.find_one({"_id": ObjectId(x_token)}) if db else None
        return user
    except Exception:
        return None


# ----------------------
# Auth Models
# ----------------------
class SignupBody(BaseModel):
    name: str
    email: EmailStr


class LoginBody(BaseModel):
    email: EmailStr


class TaskCreateBody(BaseModel):
    type: str
    title: str
    notes: Optional[str] = None
    est_minutes: int = 15
    category: Optional[str] = None
    xp_value: int = 10


class TaskCompleteBody(BaseModel):
    success: bool = True
    difficulty: Optional[str] = "normal"


class CoachQueryBody(BaseModel):
    prompt: str
    goals: Optional[str] = None
    available_time_per_day: Optional[str] = None
    strengths: Optional[str] = None
    weaknesses: Optional[str] = None
    preferred_learning_style: Optional[str] = None


# ----------------------
# Routes
# ----------------------
@app.get("/")
def root():
    return {"service": "LevelUp API", "demo_mode": DEMO_MODE, "ai_enabled": AI_ENABLED}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected & Working"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()[:10]
    except Exception as e:
        response["database"] = f"⚠️ Connected but error: {str(e)[:80]}"
    return response


# ---------- AUTH ----------
@app.post("/api/auth/signup")
def signup(body: SignupBody):
    if db is None:
        raise HTTPException(500, "Database not configured")
    existing = db.user.find_one({"email": body.email})
    if existing:
        raise HTTPException(400, "Email already registered")
    user_id = db.user.insert_one({
        "name": body.name,
        "email": body.email,
        "handle": body.email.split("@")[0],
        "avatar": None,
        "settings": {},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }).inserted_id
    # Create profile
    db.profile.insert_one({
        "user_id": str(user_id),
        "college": None,
        "year": None,
        "skills_progress": {},
        "coins": 0,
        "xp": 0,
        "level": 1,
        "streaks": {"current": 0, "best": 0, "grace_tokens": 2},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    return {"token": str(user_id)}


@app.post("/api/auth/login")
def login(body: LoginBody):
    if db is None:
        raise HTTPException(500, "Database not configured")
    user = db.user.find_one({"email": body.email})
    if not user:
        raise HTTPException(401, "Invalid credentials")
    return {"token": str(user["_id"])}


@app.get("/api/user/me")
def me(x_token: Optional[str] = Header(None)):
    if db is None:
        raise HTTPException(500, "Database not configured")
    user = get_user_from_token(x_token)
    if not user:
        raise HTTPException(401, "Unauthorized")
    profile = db.profile.find_one({"user_id": str(user["_id"])})
    return {"user": {"id": str(user["_id"]), "name": user["name"], "email": user["email"], "handle": user.get("handle")}, "profile": profile}


# ---------- TASKS ----------
@app.post("/api/tasks")
def create_task(body: TaskCreateBody, x_token: Optional[str] = Header(None)):
    user = get_user_from_token(x_token)
    if not user:
        raise HTTPException(401, "Unauthorized")
    task = {
        "owner_id": str(user["_id"]),
        "type": body.type,
        "title": body.title,
        "notes": body.notes,
        "est_minutes": body.est_minutes,
        "category": body.category,
        "status": "pending",
        "xp_value": body.xp_value,
        "created_at": datetime.now(timezone.utc),
        "due_at": None
    }
    tid = db.task.insert_one(task).inserted_id
    task["id"] = str(tid)
    return task


@app.get("/api/tasks")
def list_tasks(x_token: Optional[str] = Header(None)):
    user = get_user_from_token(x_token)
    if not user:
        raise HTTPException(401, "Unauthorized")
    items = list(db.task.find({"owner_id": str(user["_id"]) }).sort("created_at", -1))
    for it in items:
        it["id"] = str(it.pop("_id"))
    return {"items": items}


@app.patch("/api/tasks/{task_id}/complete")
def complete_task(task_id: str, body: TaskCompleteBody, x_token: Optional[str] = Header(None)):
    user = get_user_from_token(x_token)
    if not user:
        raise HTTPException(401, "Unauthorized")
    from bson import ObjectId
    task = db.task.find_one({"_id": ObjectId(task_id), "owner_id": str(user["_id"])})
    if not task:
        raise HTTPException(404, "Task not found")

    db.task.update_one({"_id": task["_id"]}, {"$set": {"status": "completed", "updated_at": datetime.now(timezone.utc)}})

    # XP calculation
    difficulty_multiplier = {"easy": 0.8, "normal": 1.0, "hard": 1.3}.get(body.difficulty or "normal", 1.0)
    base_xp = int(task.get("est_minutes", 15) * difficulty_multiplier)
    bonus_xp = 10  # first completion bonus (simplified)
    gained = int(task.get("xp_value", 10)) + base_xp + bonus_xp

    profile = db.profile.find_one({"user_id": str(user["_id"])}) or {"xp": 0, "level": 1, "coins": 0}
    result = apply_xp_and_level(profile, gained)
    db.profile.update_one({"user_id": str(user["_id"])}, {"$set": result["profile"]}, upsert=True)

    payload = {
        "gained_xp": gained,
        "new_level": result["profile"]["level"],
        "leveled_up": result["leveled_up"],
        "coins": result["profile"]["coins"],
        "animation": "level_up" if result["leveled_up"] else "confetti",
        "story_snippet": "A new chapter unfolds..." if result["leveled_up"] else None,
    }
    return payload


# ---------- SKILL TREE / MODULES ----------
@app.get("/api/skill-tree")
def get_skill_tree():
    tree = {
        "categories": [
            {"id": "communication", "name": "Communication", "nodes": ["Active Listening", "STAR Answers", "Elevator Pitch"]},
            {"id": "tools", "name": "Tools", "nodes": ["Excel Basics", "Excel Pivot", "SQL Selects"]},
            {"id": "design", "name": "Design Thinking", "nodes": ["Empathize", "Define", "Ideate"]},
            {"id": "ai", "name": "AI", "nodes": ["Prompt Basics", "RAG", "Automation"]},
        ]
    }
    return tree


@app.get("/api/modules/{module_id}/start")
def start_module(module_id: str, x_token: Optional[str] = Header(None)):
    user = get_user_from_token(x_token)
    if not user:
        raise HTTPException(401, "Unauthorized")
    # Minimal: record a start event
    db.analytics.insert_one({
        "type": "module_start", "user_id": str(user["_id"]), "module_id": module_id, "ts": datetime.now(timezone.utc)
    })
    return {"ok": True, "module_id": module_id, "launch_url": f"https://example.com/modules/{module_id}"}


# ---------- AI COACH ----------
@app.post("/api/coach/query")
def coach_query(body: CoachQueryBody):
    if not AI_ENABLED:
        return {"enabled": False, "plan": []}

    # Demo deterministic plan (no external calls)
    days = []
    topics = [
        "Focus Sprint + Quick Win",
        "Excel Challenge: VLOOKUP to XLOOKUP",
        "Behavioral Qs: 3 STAR answers",
        "Portfolio Tidy-Up",
        "SQL mini-quiz",
        "Mock Interview 10-min",
        "Review & Celebrate"
    ]
    for i in range(7):
        days.append({
            "day": i + 1,
            "task": topics[i % len(topics)],
            "minutes": 15,
            "links": [
                "https://www.youtube.com/results?search_query=excel+interview+practice",
                "https://roadmap.sh/"
            ],
            "challenge": "Complete in one focused block; share one learning in notes"
        })
    return {
        "enabled": True,
        "plan": days,
        "motivation": "Small wins compound. You’ve got this!"
    }


# ---------- ANALYTICS ----------
class AnalyticsEvent(BaseModel):
    name: str
    props: Dict[str, Any] = {}


@app.post("/api/analytics/event")
def analytics_event(event: AnalyticsEvent, x_token: Optional[str] = Header(None)):
    uid = None
    user = get_user_from_token(x_token)
    if user:
        uid = str(user["_id"])
    db.analytics.insert_one({
        "name": event.name,
        "props": event.props,
        "user_id": uid,
        "ts": datetime.now(timezone.utc)
    })
    return {"ok": True}


# ---------- PAYMENTS (placeholder) ----------
class CheckoutBody(BaseModel):
    price_id: str
    metadata: Dict[str, Any] = {}


@app.post("/api/payments/checkout")
def checkout(body: CheckoutBody, x_token: Optional[str] = Header(None)):
    user = get_user_from_token(x_token)
    if not user:
        raise HTTPException(401, "Unauthorized")
    # Demo: record intent and return a fake URL
    db.transactions.insert_one({
        "user_id": str(user["_id"]),
        "type": "checkout",
        "amount": 299,
        "metadata": body.metadata,
        "created_at": datetime.now(timezone.utc)
    })
    return {"checkout_url": "https://payments.example/checkout/session-demo"}


# ---------- LEADERBOARD ----------
@app.get("/api/leaderboard")
def leaderboard(scope: str = "global"):
    top = list(db.profile.find({}, {"user_id": 1, "level": 1, "xp": 1, "coins": 1}).sort([("level", -1), ("xp", -1)]).limit(20))
    # Join basic user fields
    items = []
    for row in top:
        user = db.user.find_one({"_id": row.get("user_id")}) if isinstance(row.get("user_id"), dict) else db.user.find_one({"_id": __import__('bson').ObjectId(row.get("user_id"))})
        items.append({
            "user_id": row.get("user_id"),
            "name": (user or {}).get("name", "Player"),
            "level": row.get("level", 1),
            "xp": row.get("xp", 0),
            "coins": row.get("coins", 0)
        })
    return {"scope": scope, "items": items}


# ---------- DEMO SEED ----------
@app.post("/api/demo/seed")
def demo_seed():
    if not DEMO_MODE:
        raise HTTPException(403, "Not allowed in production")
    import random
    names = ["Alex", "Sam", "Jordan", "Taylor", "Riya", "Kunal", "Priya", "Aarav", "Isha", "Dev"]
    for n in names:
        exist = db.user.find_one({"email": f"{n.lower()}@demo.local"})
        if exist:
            continue
        uid = db.user.insert_one({
            "name": n,
            "email": f"{n.lower()}@demo.local",
            "handle": n.lower(),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }).inserted_id
        db.profile.insert_one({
            "user_id": str(uid),
            "coins": random.randint(0, 200),
            "xp": random.randint(0, 120),
            "level": random.randint(1, 6),
            "streaks": {"current": random.randint(0, 10), "best": random.randint(5, 30), "grace_tokens": 2},
            "skills_progress": {},
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
    # Modules
    if db.module.count_documents({}) == 0:
        modules = [
            {"title": "Excel Basics", "duration_minutes": 15, "type": "micro", "content_url": "https://youtu.be/dQw4w9WgXcQ", "xp_reward": 25},
            {"title": "SQL 101", "duration_minutes": 15, "type": "micro", "content_url": "https://sqlbolt.com", "xp_reward": 25},
            {"title": "STAR Answers", "duration_minutes": 10, "type": "micro", "content_url": "https://interviewing.io/blog/star-method", "xp_reward": 20},
            {"title": "Prompt Engineering", "duration_minutes": 15, "type": "micro", "content_url": "https://promptingguide.ai/", "xp_reward": 25},
            {"title": "Design Thinking", "duration_minutes": 15, "type": "micro", "content_url": "https://www.interaction-design.org/", "xp_reward": 25},
        ]
        for m in modules:
            db.module.insert_one({**m, "created_at": datetime.now(timezone.utc)})
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
