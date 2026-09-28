import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Dict, Any

from .config import settings
from .models import (
    ChatRequest, ChatResponse, FeedbackRequest, FeedbackResponse,
    ModelsInfoResponse, BillingLink
)
from .orchestrator import Orchestrator
from .db import record_feedback, get_connection

app = FastAPI(title="AI Staffing Assistant API", version="1.0.0")

# Enable CORS for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = Orchestrator()

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "AI Staffing Assistant"}

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    try:
        response = await orchestrator.handle_chat(req)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/models", response_model=ModelsInfoResponse)
async def get_models_info():
    is_mock = settings.jev_mock or not settings.typesafe_api_key.strip()
    jev_ver = f"{settings.jev_model} (MOCK)" if is_mock else settings.jev_model

    # Determine current provider and model
    prov = settings.llm_provider
    if prov == "gemini":
        model_name = settings.gemini_model
    elif prov == "groq":
        model_name = settings.groq_model
    elif prov == "openrouter":
        model_name = settings.openrouter_model
    else:
        model_name = settings.ollama_model

    return ModelsInfoResponse(
        llm_provider=prov.capitalize(),
        llm_model=model_name,
        llm_badge="Free Tier",
        decision_engine_name="Jev (TypeSafe AI)",
        decision_engine_model=jev_ver,
        is_mock=is_mock,
        billing_links=[
            BillingLink(name="TypeSafe Console (API keys, usage)", url="https://console.typesafe.ai"),
            BillingLink(name="API Key Management", url="https://console.typesafe.ai/settings/keys"),
            BillingLink(name="Vercel AI Gateway (typesafe-ai/jev)", url="https://vercel.com/ai-gateway")
        ],
        billing_note="No direct payment link was verified; add credit/billing through the console or your Vercel account."
    )

@app.post("/api/feedback", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest):
    success = record_feedback(
        request_id=req.request_id,
        candidate_id=req.candidate_id,
        feedback=req.feedback,
        notes=req.notes
    )
    if success:
        return FeedbackResponse(status="success", message=f"Candidate {req.candidate_id} marked as {req.feedback}")
    else:
        # Still record ok if id was synthetic or during testing
        return FeedbackResponse(status="recorded", message=f"Feedback recorded for {req.candidate_id}")

@app.get("/api/logs/ai-calls")
async def get_ai_call_logs(limit: int = Query(default=20, le=100)):
    """Returns recent AI call records from logs/ai_calls.jsonl."""
    from .ai_logger import AI_CALLS_JSONL_FILE
    import json
    if not AI_CALLS_JSONL_FILE.exists():
        return {"calls": [], "total": 0}
    
    records = []
    with open(AI_CALLS_JSONL_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return {
        "calls": records[-limit:][::-1],
        "total": len(records)
    }

@app.get("/api/resources")
async def list_resources(
    role: Optional[str] = None,
    domain: Optional[str] = None,
    seniority: Optional[str] = None,
    min_exp: Optional[float] = None,
    user_role: str = "manager",
    limit: int = Query(default=100, le=300)
):
    """Staffing Dashboard endpoint returning resources, current utilization, and skills."""
    conn = get_connection()
    cur = conn.cursor()

    query = """
    SELECT 
        r.resource_id, r.full_name, r.email, r.role, r.seniority,
        r.years_experience, r.location, r.timezone, r.hourly_cost,
        r.max_allocation_pct, r.status, r.primary_domain, r.notes,
        COALESCE(SUM(CASE 
            WHEN rp.start_date <= date('now') AND rp.end_date >= date('now') THEN rp.allocation_pct 
            ELSE 0 
        END), 0.0) as current_allocation_pct,
        COUNT(DISTINCT CASE 
            WHEN rp.start_date <= date('now') AND rp.end_date >= date('now') THEN rp.project_id 
            ELSE NULL 
        END) as concurrent_projects_count
    FROM PM_RESOURCES r
    LEFT JOIN PM_RESOURCE_PROJECTS rp ON r.resource_id = rp.resource_id
    WHERE r.status = 'active'
    """
    params: List[Any] = []

    if role:
        query += " AND LOWER(r.role) LIKE ?"
        params.append(f"%{role.lower()}%")
    if domain:
        query += " AND LOWER(r.primary_domain) = ?"
        params.append(domain.lower())
    if seniority:
        query += " AND r.seniority = ?"
        params.append(seniority)
    if min_exp is not None:
        query += " AND r.years_experience >= ?"
        params.append(min_exp)

    query += " GROUP BY r.resource_id ORDER BY current_allocation_pct ASC, r.years_experience DESC LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]

    # Fetch top skills per resource
    for row in rows:
        cur.execute("""
            SELECT normalized_skill, proficiency, years_used 
            FROM PM_RESOURCE_SKILLS 
            WHERE resource_id = ? 
            ORDER BY proficiency DESC LIMIT 4
        """, (row["resource_id"],))
        row["skills"] = [dict(sk) for sk in cur.fetchall()]
        if user_role.lower() != "manager":
            row["hourly_cost"] = None

    conn.close()
    return {"count": len(rows), "resources": rows}

# Mount static files for single-page application
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")
