import json
import logging
import math
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple, Optional
import httpx
import time
from .config import settings
from .ai_logger import log_ai_call

logger = logging.getLogger("ai_staffing")

RUBRIC_LEVELS = [
    "0 = No relevant experience in required skills or domain",
    "1 = Basic conceptual knowledge of 1 skill, no domain experience",
    "2 = Applied skills in required technologies with adjacent domain experience",
    "3 = Solid depth across required skills and direct domain experience",
    "4 = Senior/Lead domain authority with mastery of required skills"
]

class DecisionEngine(ABC):
    """Abstract interface for candidate scoring decision engines."""
    
    @abstractmethod
    async def score_candidates(
        self,
        project_spec: Dict[str, Any],
        candidates: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, Dict[str, Any]], int, str, bool, bool]:
        """
        Scores a list of candidates against project specifications.
        Returns:
            - candidate_scores: map of resource_id -> {
                skill_score: float,
                skill_confidence: float,
                skill_probabilities: dict,
                burnout_prob: float,
                burnout_confidence: float
              }
            - input_tokens: int
            - model_name: str
            - is_mock: bool
            - is_fallback: bool
        """
        pass

class JevDecisionEngine(DecisionEngine):
    """
    Connects to TypeSafe AI's System One API endpoint.
    Endpoint: POST https://api.typesafe.ai/v1/systemone
    """
    def __init__(self, api_key: str, model: str = "jev-1.13.0", base_url: str = ""):
        self.api_key = api_key
        self.model = model
        if base_url:
            self.url = base_url
        elif api_key.strip().startswith("vck_"):
            # Vercel AI Gateway key
            self.url = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
        else:
            self.url = "https://api.typesafe.ai/v1/systemone"

    async def score_candidates(
        self,
        project_spec: Dict[str, Any],
        candidates: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, Dict[str, Any]], int, str, bool, bool]:
        if not candidates:
            return {}, 0, self.model, False, False

        # Batch candidates in groups of 10 to keep within optimal latency & context
        batch_size = 10
        total_tokens = 0
        candidate_scores: Dict[str, Dict[str, Any]] = {}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            for i in range(0, len(candidates), batch_size):
                batch = candidates[i:i + batch_size]
                state_text = self._build_state(project_spec, batch)
                questions = self._build_questions(batch)
                payload = {
                    "state": state_text,
                    "model": self.model,
                    "questions": questions
                }

                # Retry logic with backoff
                max_retries = 2
                success = False
                provider_name = "Vercel AI Gateway" if "vercel" in self.url else "TypeSafe AI"
                for attempt in range(max_retries + 1):
                    t0 = time.perf_counter()
                    try:
                        resp = await client.post(self.url, headers=headers, json=payload)
                        lat_ms = (time.perf_counter() - t0) * 1000
                        if resp.status_code == 200:
                            data = resp.json()
                            resolved_model = data.get("model", self.model)
                            usage = data.get("usage", {})
                            tokens_batch = usage.get("input_tokens", len(state_text) // 4)
                            total_tokens += tokens_batch
                            answers = data.get("answers", {})

                            for cand in batch:
                                cid = cand["resource_id"]
                                score_key = f"cand_{cid}_score"
                                burnout_key = f"cand_{cid}_burnout"

                                s_ans = answers.get(score_key, {})
                                b_ans = answers.get(burnout_key, {})

                                skill_score = float(s_ans.get("score", 2.0))
                                skill_conf = float(s_ans.get("confidence", 0.70))
                                skill_probs = s_ans.get("probabilities", {})

                                burnout_prob = float(b_ans.get("noul", 0.30))
                                # Noul certainty is distance from 0.5
                                burnout_conf = round(abs(burnout_prob - 0.5) * 2.0, 2)

                                candidate_scores[cid] = {
                                    "skill_score": skill_score,
                                    "skill_confidence": skill_conf,
                                    "skill_probabilities": skill_probs,
                                    "burnout_prob": burnout_prob,
                                    "burnout_confidence": burnout_conf
                                }
                            success = True
                            cost_batch = (tokens_batch / 1_000_000) * settings.jev_cost_per_million_tokens
                            log_ai_call(
                                call_type="JEV_DECISION_ENGINE_BATCH",
                                provider=provider_name,
                                model=resolved_model,
                                endpoint=self.url,
                                request_data={
                                    "batch_size": len(batch),
                                    "candidate_ids": [c["resource_id"] for c in batch],
                                    "project_spec": project_spec,
                                    "payload": payload
                                },
                                response_data=data,
                                latency_ms=lat_ms,
                                status="SUCCESS",
                                tokens={"input_tokens": tokens_batch, "output_tokens": 0, "total_tokens": tokens_batch},
                                cost_usd=cost_batch
                            )
                            break
                        elif resp.status_code in (429, 529):
                            # Rate limit or overload
                            logger.warning(f"TypeSafe rate limited (status {resp.status_code}), retrying...")
                            log_ai_call(
                                call_type="JEV_DECISION_ENGINE_BATCH",
                                provider=provider_name,
                                model=self.model,
                                endpoint=self.url,
                                request_data={
                                    "batch_size": len(batch),
                                    "candidate_ids": [c["resource_id"] for c in batch],
                                    "attempt": attempt + 1
                                },
                                response_data={"status_code": resp.status_code, "text": resp.text},
                                latency_ms=lat_ms,
                                status="RATE_LIMITED",
                                error=f"Rate limited (status {resp.status_code})"
                            )
                            await httpx.AsyncClient().sleep(0.5 * (attempt + 1))
                        else:
                            logger.error(f"TypeSafe returned status {resp.status_code}: {resp.text}")
                            log_ai_call(
                                call_type="JEV_DECISION_ENGINE_BATCH",
                                provider=provider_name,
                                model=self.model,
                                endpoint=self.url,
                                request_data={
                                    "batch_size": len(batch),
                                    "candidate_ids": [c["resource_id"] for c in batch],
                                    "attempt": attempt + 1
                                },
                                response_data={"status_code": resp.status_code, "text": resp.text},
                                latency_ms=lat_ms,
                                status="ERROR",
                                error=f"HTTP {resp.status_code}: {resp.text}"
                            )
                            break
                    except Exception as e:
                        lat_ms = (time.perf_counter() - t0) * 1000
                        logger.warning(f"Error calling TypeSafe API (attempt {attempt + 1}): {e}")
                        log_ai_call(
                            call_type="JEV_DECISION_ENGINE_BATCH",
                            provider=provider_name,
                            model=self.model,
                            endpoint=self.url,
                            request_data={
                                "batch_size": len(batch),
                                "candidate_ids": [c["resource_id"] for c in batch],
                                "attempt": attempt + 1
                            },
                            response_data=None,
                            latency_ms=lat_ms,
                            status="ERROR",
                            error=str(e)
                        )
                        if attempt < max_retries:
                            await httpx.AsyncClient().sleep(0.5 * (attempt + 1))

                if not success:
                    logger.error("Jev API call failed after retries. Falling back to Rule-Based Scorer.")
                    log_ai_call(
                        call_type="JEV_FALLBACK_TRIGGERED",
                        provider=provider_name,
                        model=self.model,
                        endpoint=self.url,
                        request_data={"project_spec": project_spec, "candidate_count": len(candidates)},
                        response_data={"action": "Switching to RuleBasedDecisionEngine fallback"},
                        latency_ms=0,
                        status="FALLBACK",
                        error="All API retries failed or unauthorized"
                    )
                    fallback_engine = RuleBasedDecisionEngine()
                    return await fallback_engine.score_candidates(project_spec, candidates)

        return candidate_scores, total_tokens, self.model, False, False

    def _build_state(self, project_spec: Dict[str, Any], candidates: List[Dict[str, Any]]) -> str:
        lines = [
            "### TARGET PROJECT SPECIFICATION",
            f"Role: {project_spec.get('role', 'Any')}",
            f"Required Skills: {', '.join(project_spec.get('skills', [])) or 'General'}",
            f"Domain: {project_spec.get('domain', 'General')}",
            f"Start Date: {project_spec.get('start_date', 'Immediate')}",
            f"Duration: {project_spec.get('duration_weeks', 12)} weeks",
            f"Min Experience: {project_spec.get('min_experience_years', 0)} years",
            "",
            "### CANDIDATE SUMMARIES"
        ]
        for c in candidates:
            lines.extend([
                f"Candidate [{c['resource_id']}]:",
                f"- Name: {c['full_name']} | Role: {c['role']} | Seniority: {c['seniority']} | Exp: {c['years_experience']} yrs",
                f"- Primary Domain: {c['primary_domain']} | Location: {c['location']} ({c['timezone']})",
                f"- Skills: {c.get('skills_summary', 'N/A')}",
                f"- Workload Facts: Current Alloc: {c['current_allocation_pct']}%, Window Alloc: {c['window_allocation_pct']}%, Active Projects: {c['concurrent_projects_count']}, Last 4w Hours: {c['hours_last_4_weeks']}h, Overtime: {c['recent_overtime_hours']}h",
                ""
            ])
        return "\n".join(lines)

    def _build_questions(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        questions: Dict[str, Any] = {}
        for c in candidates:
            cid = c["resource_id"]
            questions[f"cand_{cid}_score"] = {
                "type": "score",
                "instructions": f"How well does candidate {cid}'s domain and skill experience match the project requirements?",
                "criteria": RUBRIC_LEVELS
            }
            questions[f"cand_{cid}_burnout"] = {
                "type": "noul",
                "instructions": f"Is candidate {cid} at risk of burnout from context-switching or high utilization if added to this project?",
                "criteria": {
                    "true": "Current allocation >= 100%, 3+ active projects, or heavy overtime (>160h)",
                    "false": "Sustainable workload with capacity to onboard"
                }
            }
        return questions

class MockDecisionEngine(DecisionEngine):
    """
    Deterministic local scorer returning the exact same JSON shape as TypeSafe Jev.
    Used when JEV_MOCK=true or no API key is provided.
    """
    def __init__(self, model_version: str = "jev-1.13.0"):
        self.model = f"{model_version} (MOCK)"

    async def score_candidates(
        self,
        project_spec: Dict[str, Any],
        candidates: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, Dict[str, Any]], int, str, bool, bool]:
        t0 = time.perf_counter()
        candidate_scores: Dict[str, Dict[str, Any]] = {}
        target_domain = (project_spec.get("domain") or "").strip().lower()
        req_skills = [s.strip().lower() for s in project_spec.get("skills", []) if s]
        min_exp = project_spec.get("min_experience_years") or 0.0

        for cand in candidates:
            cid = cand["resource_id"]
            cand_domain = cand.get("primary_domain", "").strip().lower()
            cand_exp = float(cand.get("years_experience", 0.0))
            matched_skills_count = int(cand.get("matched_skills_count", 0))
            avg_prof = float(cand.get("avg_proficiency", 3.0))

            # 1. Deterministic Skill & Domain Score (0.0 to 4.0)
            score_val = 1.0  # Base
            # Skill matching contribution (up to 2.0)
            if req_skills:
                skill_ratio = min(1.0, matched_skills_count / max(1, len(req_skills)))
                score_val += skill_ratio * 1.5 + (avg_prof / 5.0) * 0.5
            else:
                score_val += (avg_prof / 5.0) * 1.5

            # Domain match contribution (up to 0.8)
            domain_matched = bool(target_domain and target_domain == cand_domain)
            if domain_matched:
                score_val += 0.8
            elif target_domain and target_domain != cand_domain:
                score_val -= 0.3

            # Seniority / experience bonus (up to 0.5)
            if cand_exp >= min_exp:
                score_val += min(0.5, (cand_exp - min_exp) * 0.1)

            # Clamp score to [0.0, 4.0]
            score_val = round(max(0.0, min(4.0, score_val)), 2)

            # Skill confidence (0.0 to 1.0)
            # Low confidence triggered when:
            # - No domain match while domain was requested, OR
            # - Few matched skills, OR
            # - Ambiguous experience levels
            if target_domain and not domain_matched and matched_skills_count <= 1:
                skill_conf = round(0.48 + 0.08 * (avg_prof / 5.0), 2)  # < 0.60
            elif not req_skills and not target_domain:
                skill_conf = 0.55  # Underspecified request -> low confidence
            else:
                skill_conf = round(0.68 + 0.25 * (matched_skills_count / max(1, len(req_skills) or 1)), 2)
                skill_conf = min(0.96, skill_conf)

            # Probabilities distribution across levels 0..4
            center_level = int(round(score_val))
            probs = {}
            for lvl in range(5):
                dist = abs(lvl - score_val)
                probs[str(lvl)] = round(math.exp(-1.5 * dist), 3)
            prob_sum = sum(probs.values()) or 1.0
            probs = {k: round(v / prob_sum, 3) for k, v in probs.items()}

            # 2. Burnout Probability (0.0 to 1.0)
            curr_alloc = float(cand.get("current_allocation_pct", 0.0))
            num_projects = int(cand.get("concurrent_projects_count", 0))
            overtime_hours = float(cand.get("recent_overtime_hours", 0.0))

            burnout_prob = 0.10
            if curr_alloc >= 100.0:
                burnout_prob += 0.45
            elif curr_alloc >= 80.0:
                burnout_prob += 0.25

            if num_projects >= 4:
                burnout_prob += 0.35
            elif num_projects >= 3:
                burnout_prob += 0.20

            if overtime_hours > 20:
                burnout_prob += 0.25
            elif overtime_hours > 0:
                burnout_prob += 0.10

            burnout_prob = round(max(0.05, min(0.98, burnout_prob)), 2)
            burnout_conf = round(abs(burnout_prob - 0.5) * 2.0, 2)
            # Guarantee baseline confidence unless strictly near 0.5
            if burnout_conf < 0.40 and (curr_alloc > 90 or curr_alloc < 40):
                burnout_conf = 0.75

            candidate_scores[cid] = {
                "skill_score": score_val,
                "skill_confidence": skill_conf,
                "skill_probabilities": probs,
                "burnout_prob": burnout_prob,
                "burnout_confidence": burnout_conf
            }

        # Simulated token count
        input_tokens = len(candidates) * 240 + 150
        cost = (input_tokens / 1_000_000) * settings.jev_cost_per_million_tokens
        lat_ms = (time.perf_counter() - t0) * 1000
        log_ai_call(
            call_type="JEV_MOCK_DECISION_ENGINE",
            provider="MockEngine",
            model=self.model,
            endpoint="local",
            request_data={
                "project_spec": project_spec,
                "candidate_count": len(candidates),
                "candidate_ids": [c["resource_id"] for c in candidates]
            },
            response_data={
                "total_candidates_scored": len(candidate_scores),
                "scores_preview": {k: candidate_scores[k] for k in list(candidate_scores.keys())[:3]}
            },
            latency_ms=lat_ms,
            status="SUCCESS",
            tokens={"input_tokens": input_tokens, "output_tokens": 0, "total_tokens": input_tokens},
            cost_usd=cost
        )
        return candidate_scores, input_tokens, self.model, True, False

class RuleBasedDecisionEngine(DecisionEngine):
    """
    Fallback scorer used if Jev API is unreachable.
    Marks confidence as lowered so human PM review is properly triggered.
    """
    def __init__(self):
        self.model = "Fallback-RuleBased"

    async def score_candidates(
        self,
        project_spec: Dict[str, Any],
        candidates: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, Dict[str, Any]], int, str, bool, bool]:
        t0 = time.perf_counter()
        mock = MockDecisionEngine("fallback")
        scores, tokens, _, _, _ = await mock.score_candidates(project_spec, candidates)
        # Downgrade confidence on all candidates due to decision engine outage
        for cid, res in scores.items():
            res["skill_confidence"] = min(0.55, res["skill_confidence"])
            res["burnout_confidence"] = min(0.55, res["burnout_confidence"])
        lat_ms = (time.perf_counter() - t0) * 1000
        log_ai_call(
            call_type="FALLBACK_RULE_BASED_ENGINE",
            provider="RuleBasedScorer",
            model=self.model,
            endpoint="local",
            request_data={
                "project_spec": project_spec,
                "candidate_count": len(candidates),
                "candidate_ids": [c["resource_id"] for c in candidates]
            },
            response_data={
                "total_scored": len(scores),
                "scores_preview": {k: scores[k] for k in list(scores.keys())[:3]}
            },
            latency_ms=lat_ms,
            status="FALLBACK"
        )
        return scores, 0, self.model, True, True

def get_decision_engine() -> DecisionEngine:
    """Factory creating configured decision engine instance."""
    if settings.jev_mock or not settings.typesafe_api_key.strip():
        logger.info("Using deterministic MockDecisionEngine (JEV_MOCK=true or no key set)")
        return MockDecisionEngine(settings.jev_model)
    else:
        logger.info(f"Using live JevDecisionEngine with model {settings.jev_model}")
        return JevDecisionEngine(settings.typesafe_api_key, settings.jev_model, settings.jev_base_url)
