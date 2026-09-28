from typing import List, Dict, Any, Tuple
from .config import settings
from .models import CandidateResult, CandidateScoreBreakdown

SENIORITY_RANKS = {
    "Junior": 1,
    "Mid": 2,
    "Senior": 3,
    "Lead": 4
}

def calculate_seniority_fit(candidate_seniority: str, requested_seniority: str = "Senior") -> float:
    c_rank = SENIORITY_RANKS.get(candidate_seniority, 2)
    r_rank = SENIORITY_RANKS.get(requested_seniority, 3)
    diff = abs(c_rank - r_rank)
    if diff == 0:
        return 1.0
    elif diff == 1:
        return 0.8
    elif diff == 2:
        return 0.6
    else:
        return 0.4

def rank_candidates(
    candidates_with_scores: List[Dict[str, Any]],
    requested_seniority: str = "Senior",
    user_role: str = "manager"
) -> Tuple[List[CandidateResult], bool, bool]:
    """
    Ranks candidates using:
    final_score = w1*skill_score_norm + w2*availability_fit + w3*(1 - burnout_prob) + w4*seniority_fit - w5*cost_penalty

    Applies Low-Confidence Rules:
    - is_low_confidence if skill_confidence < MIN_CONFIDENCE or burnout_confidence < MIN_CONFIDENCE
    - is_tie if top-2 difference < TIE_MARGIN
    - all_top3_low_confidence if top 3 are all low confidence
    - workload_risk if burnout_prob >= HIGH_BURNOUT_PROB
    - needs_pm_review flag
    - Field-level masking of hourly_cost for non-managers

    Returns:
        (ranked_candidates, is_group_tie, all_top3_low_confidence)
    """
    w1 = settings.weight_skill
    w2 = settings.weight_availability
    w3 = settings.weight_burnout
    w4 = settings.weight_seniority
    w5 = settings.weight_cost

    min_confidence = settings.min_confidence
    tie_margin = settings.tie_margin
    high_burnout_prob = settings.high_burnout_prob

    # Pre-calculate cost bounds for normalization
    costs = [float(c.get("hourly_cost", 100.0)) for c in candidates_with_scores]
    min_cost = min(costs) if costs else 45.0
    max_cost = max(costs) if costs else 240.0
    cost_span = max(1.0, max_cost - min_cost)

    processed: List[CandidateResult] = []

    for c in candidates_with_scores:
        # Components
        raw_skill_score = float(c.get("skill_score", 2.0))
        skill_score_norm = min(1.0, max(0.0, raw_skill_score / 4.0))

        # Availability fit based on available capacity (0..100 -> 0..1.0)
        avail_capacity = float(c.get("available_capacity", 50.0))
        avail_fit = min(1.0, max(0.0, avail_capacity / 100.0))

        burnout_prob = float(c.get("burnout_prob", 0.20))
        burnout_fit = max(0.0, 1.0 - burnout_prob)

        cand_seniority = c.get("seniority", "Mid")
        seniority_fit = calculate_seniority_fit(cand_seniority, requested_seniority)

        hourly_cost = float(c.get("hourly_cost", 100.0))
        cost_norm = max(0.0, min(1.0, (hourly_cost - min_cost) / cost_span))

        # Breakdown components
        c_w1 = round(w1 * skill_score_norm, 4)
        c_w2 = round(w2 * avail_fit, 4)
        c_w3 = round(w3 * burnout_fit, 4)
        c_w4 = round(w4 * seniority_fit, 4)
        c_w5 = round(w5 * cost_norm, 4)

        final_score = round(c_w1 + c_w2 + c_w3 + c_w4 - c_w5, 4)
        final_score = max(0.0, min(1.0, final_score))

        skill_conf = float(c.get("skill_confidence", 0.70))
        burnout_conf = float(c.get("burnout_confidence", 0.70))

        # Low confidence check
        is_low_conf = (skill_conf < min_confidence) or (burnout_conf < min_confidence)

        if skill_conf >= 0.75 and burnout_conf >= 0.75:
            conf_level = "HIGH"
        elif not is_low_conf:
            conf_level = "MODERATE"
        else:
            conf_level = "LOW"

        # Workload risk
        has_workload_risk = burnout_prob >= high_burnout_prob

        # Field-level permission: hide hourly_cost if not manager
        display_cost = hourly_cost if user_role.lower() == "manager" else None

        res = CandidateResult(
            resource_id=c["resource_id"],
            full_name=c["full_name"],
            email=c["email"],
            role=c["role"],
            seniority=cand_seniority,
            years_experience=float(c.get("years_experience", 0.0)),
            location=c["location"],
            timezone=c["timezone"],
            primary_domain=c["primary_domain"],
            hourly_cost=display_cost,
            max_allocation_pct=float(c.get("max_allocation_pct", 100.0)),
            current_allocation_pct=float(c.get("current_allocation_pct", 0.0)),
            concurrent_projects_count=int(c.get("concurrent_projects_count", 0)),
            hours_last_4_weeks=float(c.get("hours_last_4_weeks", 0.0)),
            recent_overtime_hours=float(c.get("recent_overtime_hours", 0.0)),
            skill_score=raw_skill_score,
            skill_confidence=skill_conf,
            burnout_prob=burnout_prob,
            burnout_confidence=burnout_conf,
            final_score=final_score,
            confidence_level=conf_level,
            is_low_confidence=is_low_conf,
            is_tie=False,  # Evaluated after sorting
            workload_risk=has_workload_risk,
            needs_pm_review=is_low_conf or has_workload_risk,
            explanation=c.get("explanation", ""),
            score_breakdown=CandidateScoreBreakdown(
                w1_skill=c_w1,
                w2_availability=c_w2,
                w3_burnout=c_w3,
                w4_seniority=c_w4,
                w5_cost_penalty=c_w5
            ),
            skills=c.get("skills", [])
        )
        processed.append(res)

    # Sort descending by final_score
    processed.sort(key=lambda x: x.final_score, reverse=True)

    # Check for Tie condition on top-2
    is_group_tie = False
    if len(processed) >= 2:
        diff = abs(processed[0].final_score - processed[1].final_score)
        if diff < tie_margin:
            is_group_tie = True
            processed[0].is_tie = True
            processed[1].is_tie = True
            processed[0].needs_pm_review = True
            processed[1].needs_pm_review = True

    # Check if ALL top 3 are low confidence
    all_top3_low = False
    if len(processed) >= 3:
        if processed[0].is_low_confidence and processed[1].is_low_confidence and processed[2].is_low_confidence:
            all_top3_low = True

    return processed, is_group_tie, all_top3_low
