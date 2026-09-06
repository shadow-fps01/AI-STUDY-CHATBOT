import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

DB_PATH = Path(__file__).parent / "study_app.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        pass
    return conn


def init_db():
    """Initializes the SQLite database schema with users, profiles, chat, and subscriptions."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL COLLATE NOCASE,
                username TEXT NOT NULL,
                hashed_password TEXT NOT NULL,
                salt TEXT NOT NULL,
                tier TEXT DEFAULT 'free',
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                education_level TEXT DEFAULT 'Undergraduate',
                field_of_study TEXT DEFAULT 'General Studies',
                subjects TEXT DEFAULT '[]',
                target_exams TEXT DEFAULT 'Academic Excellence',
                target_score TEXT DEFAULT 'Top Marks',
                learning_style TEXT DEFAULT 'Adaptive & Step-by-Step',
                daily_study_hours REAL DEFAULT 3.0,
                custom_directives TEXT DEFAULT '',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                ai_name TEXT DEFAULT 'StudyMaster AI',
                timestamp TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_id TEXT UNIQUE NOT NULL,
                plan_name TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                currency TEXT DEFAULT 'usd',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        conn.commit()


def create_user(email: str, username: str, hashed_pw: str, salt: str) -> Dict[str, Any]:
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (email, username, hashed_password, salt, tier, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'free', ?, ?)
        """,
            (email.strip().lower(), username.strip(), hashed_pw, salt, now, now),
        )
        new_id = cursor.lastrowid
        default_subjects = json.dumps(["Mathematics", "Physics", "Computer Science"])
        cursor.execute(
            """
            INSERT INTO profiles (user_id, education_level, field_of_study, subjects, target_exams, target_score, learning_style, daily_study_hours, custom_directives, updated_at)
            VALUES (?, 'Undergraduate', 'Computer Science & STEM', ?, 'Final Exams & Certifications', 'A Grade / Top 5%', 'Feynman Technique & Step-by-Step Problem Solving', 3.0, '', ?)
        """,
            (new_id, default_subjects, now),
        )
        conn.commit()
    return get_user_by_id(new_id)


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not email:
        return None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email.strip().lower(),)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (int(user_id),))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_user_tier(user_id: int, tier: str, stripe_sub_id: Optional[str] = None):
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        if stripe_sub_id:
            cursor.execute(
                """
                UPDATE users SET tier = ?, stripe_subscription_id = ?, updated_at = ? WHERE id = ?
            """,
                (tier, stripe_sub_id, now, user_id),
            )
        else:
            cursor.execute(
                """
                UPDATE users SET tier = ?, updated_at = ? WHERE id = ?
            """,
                (tier, now, user_id),
            )
        conn.commit()


def get_profile_by_user_id(user_id: int) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM profiles WHERE user_id = ?", (int(user_id),))
        row = cursor.fetchone()
        if not row:
            return None
        profile = dict(row)
        try:
            profile["subjects"] = json.loads(profile.get("subjects", "[]"))
        except Exception:
            profile["subjects"] = []
        return profile


def upsert_profile(
    user_id: int,
    education_level: str,
    field_of_study: str,
    subjects: List[str],
    target_exams: str,
    target_score: str,
    learning_style: str,
    daily_study_hours: float,
    custom_directives: str,
) -> Optional[Dict[str, Any]]:
    now = datetime.now().isoformat()
    subjects_json = json.dumps(subjects) if isinstance(subjects, list) else subjects
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO profiles (user_id, education_level, field_of_study, subjects, target_exams, target_score, learning_style, daily_study_hours, custom_directives, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                education_level = excluded.education_level,
                field_of_study = excluded.field_of_study,
                subjects = excluded.subjects,
                target_exams = excluded.target_exams,
                target_score = excluded.target_score,
                learning_style = excluded.learning_style,
                daily_study_hours = excluded.daily_study_hours,
                custom_directives = excluded.custom_directives,
                updated_at = excluded.updated_at
        """,
            (
                user_id,
                education_level,
                field_of_study,
                subjects_json,
                target_exams,
                target_score,
                learning_style,
                daily_study_hours,
                custom_directives,
                now,
            ),
        )
        conn.commit()
    return get_profile_by_user_id(user_id)


def add_chat_message(user_id: int, role: str, content: str, ai_name: str = "StudyMaster AI") -> Dict[str, Any]:
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_messages (user_id, role, content, ai_name, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """,
            (user_id, role, content, ai_name, now),
        )
        conn.commit()
        new_id = cursor.lastrowid
    return {
        "id": new_id,
        "user_id": user_id,
        "role": role,
        "content": content,
        "ai_name": ai_name,
        "timestamp": now,
    }


def get_user_chat_history(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    if not user_id:
        return []
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, content, ai_name, timestamp 
            FROM chat_messages 
            WHERE user_id = ? 
            ORDER BY id ASC 
            LIMIT ?
        """,
            (user_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


def clear_user_chat_history(user_id: int):
    if not user_id:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
        conn.commit()


def record_subscription_session(
    user_id: Optional[int],
    session_id: str,
    plan_name: str,
    amount_cents: int,
    currency: str = "ngn",
    status: str = "pending",
):
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO subscriptions (user_id, session_id, plan_name, amount_cents, currency, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
        """,
            (user_id, session_id, plan_name, amount_cents, currency, status, now, now),
        )
        conn.commit()


def get_subscription_by_session(session_id: str) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def mark_subscription_active(session_id: str, user_id: Optional[int] = None) -> Optional[int]:
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE subscriptions SET status = 'active', updated_at = ? WHERE session_id = ?
        """,
            (now, session_id),
        )
        cursor.execute(
            "SELECT user_id FROM subscriptions WHERE session_id = ?", (session_id,)
        )
        row = cursor.fetchone()
        target_user_id = user_id or (row["user_id"] if row and row["user_id"] else None)
        if target_user_id:
            cursor.execute(
                "UPDATE users SET tier = 'pro', updated_at = ? WHERE id = ?",
                (now, target_user_id),
            )
        conn.commit()
        return target_user_id