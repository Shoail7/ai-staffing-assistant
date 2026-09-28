from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class MatchStaffParams(BaseModel):
    role: Optional[str] = Field(None, description="Target job role, e.g., 'Backend Dev', 'Python Developer'")
    skills: List[str] = Field(default_factory=list, description="Required skill keywords, e.g. ['Python', 'SQL']")
    min_experience_years: Optional[float] = Field(None, description="Minimum years of experience")
    start_date: Optional[str] = Field(None, description="Target start date in YYYY-MM-DD or readable format")
    duration_weeks: Optional[int] = Field(None, description="Estimated duration in weeks")
    domain: Optional[str] = Field(None, description="Target business domain, e.g. 'fintech', 'healthcare'")
    max_results: int = Field(default=10, description="Max candidates to return")

class CandidateScoreBreakdown(BaseModel):
    w1_skill: float = Field(..., description="Normalized skill contribution (0..w1)")
    w2_availability: float = Field(..., description="Availability fit contribution (0..w2)")
    w3_burnout: float = Field(..., description="Burnout safety contribution (0..w3)")
    w4_seniority: float = Field(..., description="Seniority fit contribution (0..w4)")
    w5_cost_penalty: float = Field(..., description="Cost penalty deduction (-w5..0)")

class CandidateResult(BaseModel):
    resource_id: str
    full_name: str
    email: str
    role: str
    seniority: str
    years_experience: float
    location: str
    timezone: str
    primary_domain: str
    hourly_cost: Optional[float] = None  # None when masked for non-manager
    max_allocation_pct: float
    current_allocation_pct: float
    concurrent_projects_count: int
    hours_last_4_weeks: float
    recent_overtime_hours: float
    skill_score: float  # 0.0 to 4.0 from Jev
    skill_confidence: float  # 0.0 to 1.0 from Jev
    burnout_prob: float  # 0.0 to 1.0 from Jev Noul
    burnout_confidence: float  # 0.0 to 1.0
    final_score: float  # 0.0 to 1.0
    confidence_level: str  # "HIGH", "MODERATE", "LOW"
    is_low_confidence: bool
    is_tie: bool
    workload_risk: bool
    needs_pm_review: bool
    explanation: str
    score_breakdown: CandidateScoreBreakdown
    skills: List[Dict[str, Any]] = Field(default_factory=list)

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    user_role: str = "manager"  # "manager" or "recruiter"

class ChatResponse(BaseModel):
    conversation_id: str
    request_id: str
    message: str
    candidates: List[CandidateResult] = Field(default_factory=list)
    is_clarifying_question: bool = False
    clarifying_question: Optional[str] = None
    suggestion_chips: List[str] = Field(default_factory=list)
    latencies: Dict[str, float] = Field(default_factory=dict)
    total_latency_ms: float = 0.0
    jev_tokens: int = 0
    jev_cost_usd: float = 0.0
    jev_model: str = "jev-1.13.0"
    is_mock_jev: bool = True
    is_fallback_scorer: bool = False
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.0-flash"

class FeedbackRequest(BaseModel):
    request_id: str
    candidate_id: str
    feedback: str  # "accepted" or "rejected"
    notes: Optional[str] = None

class FeedbackResponse(BaseModel):
    status: str
    message: str

class BillingLink(BaseModel):
    name: str
    url: str

class ModelsInfoResponse(BaseModel):
    llm_provider: str
    llm_model: str
    llm_badge: str
    decision_engine_name: str
    decision_engine_model: str
    is_mock: bool
    billing_links: List[BillingLink]
    billing_note: str
