import sqlite3
import json
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from .config import settings

def get_db_path() -> str:
    return str(settings.db_path)

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def init_db():
    """Initializes tables and indexes in SQLite."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS PM_RESOURCES (
        resource_id TEXT PRIMARY KEY,
        full_name TEXT NOT NULL,
        email TEXT NOT NULL,
        role TEXT NOT NULL,
        seniority TEXT NOT NULL,
        years_experience REAL NOT NULL,
        location TEXT NOT NULL,
        timezone TEXT NOT NULL,
        hourly_cost REAL NOT NULL,
        max_allocation_pct REAL NOT NULL DEFAULT 100.0,
        status TEXT NOT NULL DEFAULT 'active',
        primary_domain TEXT NOT NULL,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS PM_PROJECTS (
        project_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        domain TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        status TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS PM_RESOURCE_PROJECTS (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        resource_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        allocation_pct REAL NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        weekly_hours REAL NOT NULL,
        role_on_project TEXT NOT NULL,
        FOREIGN KEY (resource_id) REFERENCES PM_RESOURCES (resource_id),
        FOREIGN KEY (project_id) REFERENCES PM_PROJECTS (project_id)
    );

    CREATE TABLE IF NOT EXISTS PM_SKILL_ALIASES (
        alias TEXT PRIMARY KEY,
        normalized_skill TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS PM_RESOURCE_SKILLS (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        resource_id TEXT NOT NULL,
        skill_name TEXT NOT NULL,
        normalized_skill TEXT NOT NULL,
        proficiency INTEGER NOT NULL, -- 1 to 5
        years_used REAL NOT NULL,
        last_used_date TEXT NOT NULL,
        FOREIGN KEY (resource_id) REFERENCES PM_RESOURCES (resource_id)
    );

    CREATE TABLE IF NOT EXISTS CONVERSATIONS (
        conversation_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_criteria TEXT,
        last_candidate_ids TEXT
    );

    CREATE TABLE IF NOT EXISTS MESSAGES (
        message_id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        sender TEXT NOT NULL,
        content TEXT NOT NULL,
        tool_calls TEXT,
        results_summary TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (conversation_id) REFERENCES CONVERSATIONS (conversation_id)
    );

    CREATE TABLE IF NOT EXISTS DECISION_LOG (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL,
        conversation_id TEXT,
        candidate_id TEXT NOT NULL,
        input_state TEXT,
        questions TEXT,
        jev_answers TEXT,
        confidence REAL,
        final_rank INTEGER,
        pm_feedback TEXT, -- 'accepted', 'rejected', or NULL
        feedback_notes TEXT,
        created_at TEXT NOT NULL
    );

    -- Indexes for fast filtering
    CREATE INDEX IF NOT EXISTS idx_resources_filter ON PM_RESOURCES (status, role, seniority, primary_domain);
    CREATE INDEX IF NOT EXISTS idx_skills_resource ON PM_RESOURCE_SKILLS (normalized_skill, resource_id);
    CREATE INDEX IF NOT EXISTS idx_resource_projects ON PM_RESOURCE_PROJECTS (resource_id, start_date, end_date);
    CREATE INDEX IF NOT EXISTS idx_decision_request ON DECISION_LOG (request_id, candidate_id);
    CREATE INDEX IF NOT EXISTS idx_messages_conv ON MESSAGES (conversation_id);
    """)

    conn.commit()
    conn.close()

def normalize_skill(skill_str: str) -> str:
    """Normalize skill name against alias table, falling back to clean lowercase."""
    clean = skill_str.strip().lower()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT normalized_skill FROM PM_SKILL_ALIASES WHERE LOWER(alias) = ?", (clean,))
    row = cur.fetchone()
    conn.close()
    if row:
        return row["normalized_skill"]
    # Common standard title formatting
    return skill_str.strip().title()

def filter_candidates_sql(
    role: Optional[str] = None,
    skills: Optional[List[str]] = None,
    min_experience_years: Optional[float] = None,
    start_date: Optional[str] = None,
    duration_weeks: Optional[int] = None,
    domain: Optional[str] = None,
    max_results: int = 40
) -> List[Dict[str, Any]]:
    """
    Executes Step 4a: HARD constraint filtering in SQL.
    - Status is active.
    - Role constraint (if requested).
    - Experience constraint (if requested).
    - Skill overlap constraint (if skills requested, must possess at least one).
    - Precomputes SQL burnout facts:
      current_allocation_pct, concurrent_projects_count, hours_last_4_weeks, recent_overtime_hours.
    - Checks availability in the requested date window.
    - Pre-ranked in SQL and capped to top 40 candidates.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Parse date window
    if not start_date or start_date.lower() == "immediate":
        start_dt = datetime.now()
    else:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        except Exception:
            start_dt = datetime.now()

    duration = duration_weeks or 12
    end_dt = start_dt + timedelta(weeks=duration)
    start_win_str = start_dt.strftime("%Y-%m-%d")
    end_win_str = end_dt.strftime("%Y-%m-%d")

    # Normalize input skills
    normalized_skills = []
    if skills:
        for s in skills:
            if s and s.strip():
                norm = normalize_skill(s)
                normalized_skills.append(norm)

    # Base query combining PM_RESOURCES with aggregated skills & project workloads
    query = """
    WITH CandidateSkills AS (
        SELECT 
            resource_id,
            COUNT(DISTINCT normalized_skill) as matched_skills_count,
            AVG(proficiency) as avg_proficiency,
            GROUP_CONCAT(normalized_skill || ' (' || proficiency || '/5)', ', ') as skills_summary
        FROM PM_RESOURCE_SKILLS
        WHERE 1=1
    """
    params: List[Any] = []

    if normalized_skills:
        placeholders = ",".join(["?"] * len(normalized_skills))
        query += f" AND normalized_skill IN ({placeholders})"
        params.extend(normalized_skills)
    else:
        query += " AND 1=1"

    query += """
        GROUP BY resource_id
    ),
    CandidateWorkload AS (
        SELECT
            r.resource_id,
            COALESCE(SUM(CASE 
                WHEN rp.start_date <= ? AND rp.end_date >= ? THEN rp.allocation_pct 
                ELSE 0 
            END), 0.0) as window_allocation_pct,
            COALESCE(SUM(CASE 
                WHEN rp.start_date <= date('now') AND rp.end_date >= date('now') THEN rp.allocation_pct 
                ELSE 0 
            END), 0.0) as current_allocation_pct,
            COUNT(DISTINCT CASE 
                WHEN rp.start_date <= ? AND rp.end_date >= ? THEN rp.project_id 
                ELSE NULL 
            END) as concurrent_projects_count,
            COALESCE(SUM(CASE 
                WHEN rp.start_date <= date('now') AND rp.end_date >= date('now') THEN rp.weekly_hours * 4.0 
                ELSE 0 
            END), 0.0) as hours_last_4_weeks
        FROM PM_RESOURCES r
        LEFT JOIN PM_RESOURCE_PROJECTS rp ON r.resource_id = rp.resource_id
        GROUP BY r.resource_id
    )
    SELECT 
        r.resource_id,
        r.full_name,
        r.email,
        r.role,
        r.seniority,
        r.years_experience,
        r.location,
        r.timezone,
        r.hourly_cost,
        r.max_allocation_pct,
        r.status,
        r.primary_domain,
        r.notes,
        COALESCE(cs.matched_skills_count, 0) as matched_skills_count,
        COALESCE(cs.avg_proficiency, 0.0) as avg_proficiency,
        COALESCE(cs.skills_summary, '') as skills_summary,
        cw.window_allocation_pct,
        cw.current_allocation_pct,
        cw.concurrent_projects_count,
        cw.hours_last_4_weeks,
        MAX(0.0, cw.hours_last_4_weeks - 160.0) as recent_overtime_hours,
        MAX(0.0, r.max_allocation_pct - cw.window_allocation_pct) as available_capacity
    FROM PM_RESOURCES r
    LEFT JOIN CandidateSkills cs ON r.resource_id = cs.resource_id
    LEFT JOIN CandidateWorkload cw ON r.resource_id = cw.resource_id
    WHERE r.status = 'active'
    """

    # Add window parameters: CandidateSkills CTE first, then CandidateWorkload CTE
    workload_params = [end_win_str, start_win_str, end_win_str, start_win_str]
    all_params = params + workload_params

    # Filter by role if requested
    if role:
        role_clean = role.strip().lower()
        # Allow flexible match: "python developer" -> role containing dev or backend
        if "python" in role_clean or "backend" in role_clean:
            query += " AND (LOWER(r.role) LIKE '%backend%' OR LOWER(r.role) LIKE '%python%')"
        elif "frontend" in role_clean or "react" in role_clean:
            query += " AND (LOWER(r.role) LIKE '%frontend%' OR LOWER(r.role) LIKE '%web%')"
        elif "data" in role_clean:
            query += " AND LOWER(r.role) LIKE '%data%'"
        elif "ml" in role_clean or "ai" in role_clean:
            query += " AND (LOWER(r.role) LIKE '%ml%' OR LOWER(r.role) LIKE '%ai%')"
        elif "qa" in role_clean or "test" in role_clean:
            query += " AND LOWER(r.role) LIKE '%qa%'"
        elif "devops" in role_clean or "cloud" in role_clean:
            query += " AND LOWER(r.role) LIKE '%devops%'"
        elif "designer" in role_clean or "ui" in role_clean:
            query += " AND LOWER(r.role) LIKE '%designer%'"
        elif "pm" in role_clean or "manager" in role_clean:
            query += " AND (LOWER(r.role) LIKE '%project manager%' OR LOWER(r.role) LIKE '%pm%')"
        else:
            query += " AND LOWER(r.role) LIKE ?"
            all_params.append(f"%{role_clean}%")

    # Min experience hard constraint
    if min_experience_years is not None and min_experience_years > 0:
        query += " AND r.years_experience >= ?"
        all_params.append(float(min_experience_years))

    # Required skills hard constraint: if skills provided, candidate must have at least 1 matching skill
    if normalized_skills:
        query += " AND COALESCE(cs.matched_skills_count, 0) >= 1"

    # Availability hard constraint: Candidate must have some available capacity (not 100% committed)
    query += " AND cw.window_allocation_pct < 100.0"

    # Pre-rank in SQL by:
    # 1. Matched skills count (desc)
    # 2. Average proficiency (desc)
    # 3. Domain match bonus (fintech, etc.)
    # 4. Available capacity in window (desc)
    domain_clause = ""
    if domain:
        domain_clause = f"CASE WHEN LOWER(r.primary_domain) = '{domain.strip().lower()}' THEN 1 ELSE 0 END DESC, "

    query += f"""
    ORDER BY 
        {domain_clause}
        matched_skills_count DESC,
        avg_proficiency DESC,
        available_capacity DESC
    LIMIT ?
    """
    all_params.append(max_results)

    cur.execute(query, all_params)
    rows = cur.fetchall()
    
    candidates = []
    for r in rows:
        d = dict(r)
        # Fetch candidate's top all skills
        skill_cur = conn.cursor()
        skill_cur.execute("""
            SELECT normalized_skill, proficiency, years_used 
            FROM PM_RESOURCE_SKILLS 
            WHERE resource_id = ? 
            ORDER BY proficiency DESC, years_used DESC 
            LIMIT 6
        """, (d["resource_id"],))
        d["skills"] = [dict(sk) for sk in skill_cur.fetchall()]
        candidates.append(d)

    conn.close()
    return candidates

def log_decision(
    request_id: str,
    conversation_id: Optional[str],
    candidate_id: str,
    input_state: str,
    questions: Dict[str, Any],
    jev_answers: Dict[str, Any],
    confidence: float,
    final_rank: int
):
    """Logs the candidate decision into DECISION_LOG table."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO DECISION_LOG (
            request_id, conversation_id, candidate_id, input_state, 
            questions, jev_answers, confidence, final_rank, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        request_id,
        conversation_id,
        candidate_id,
        input_state,
        json.dumps(questions),
        json.dumps(jev_answers),
        confidence,
        final_rank,
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def record_feedback(request_id: str, candidate_id: str, feedback: str, notes: Optional[str] = None) -> bool:
    """Updates PM feedback ('accepted' / 'rejected') in DECISION_LOG."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE DECISION_LOG 
        SET pm_feedback = ?, feedback_notes = ? 
        WHERE request_id = ? AND candidate_id = ?
    """, (feedback, notes, request_id, candidate_id))
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def save_conversation_turn(
    conversation_id: str,
    user_msg: str,
    assistant_msg: str,
    last_criteria: Optional[Dict[str, Any]] = None,
    candidate_ids: Optional[List[str]] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None
):
    """Saves conversation state and message history for multi-turn continuity."""
    conn = get_connection()
    cur = conn.cursor()
    now_str = datetime.now().isoformat()

    # Ensure conversation exists
    cur.execute("""
        INSERT INTO CONVERSATIONS (conversation_id, created_at, updated_at, last_criteria, last_candidate_ids)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(conversation_id) DO UPDATE SET 
            updated_at = excluded.updated_at,
            last_criteria = COALESCE(excluded.last_criteria, CONVERSATIONS.last_criteria),
            last_candidate_ids = COALESCE(excluded.last_candidate_ids, CONVERSATIONS.last_candidate_ids)
    """, (
        conversation_id,
        now_str,
        now_str,
        json.dumps(last_criteria) if last_criteria else None,
        json.dumps(candidate_ids) if candidate_ids else None
    ))

    # Insert user message
    cur.execute("""
        INSERT INTO MESSAGES (message_id, conversation_id, sender, content, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (str(uuid.uuid4())[:8], conversation_id, "user", user_msg, now_str))

    # Insert assistant message
    cur.execute("""
        INSERT INTO MESSAGES (message_id, conversation_id, sender, content, tool_calls, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        str(uuid.uuid4())[:8],
        conversation_id,
        "assistant",
        assistant_msg,
        json.dumps(tool_calls) if tool_calls else None,
        now_str
    ))

    conn.commit()
    conn.close()

def get_conversation_state(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves previous search criteria and candidate IDs for multi-turn follow-ups."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT last_criteria, last_candidate_ids FROM CONVERSATIONS WHERE conversation_id = ?", (conversation_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "last_criteria": json.loads(row["last_criteria"]) if row["last_criteria"] else {},
        "last_candidate_ids": json.loads(row["last_candidate_ids"]) if row["last_candidate_ids"] else []
    }
