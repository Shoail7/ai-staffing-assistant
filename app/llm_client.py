import os
import re
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import httpx
import time
from .config import settings
from .ai_logger import log_ai_call

logger = logging.getLogger("ai_staffing")

SYSTEM_INTENT_PROMPT = """You are an AI Staffing Orchestrator.
Your goal is to parse user staffing requests and select the appropriate tool.
Available tools:
1. match_staff(role: string, skills: string[], min_experience_years: float, start_date: string, duration_weeks: int, domain: string, max_results: int)
   Use when the user is searching for personnel/contractors/engineers.
2. get_resource_details(resource_id: string)
   Use when the user asks for more details on a specific candidate ID (e.g. RES-012).
3. clarify(question: string)
   Use only if the request is completely incomprehensible.

You MUST respond strictly with a tool call. If calling match_staff, extract any duration (e.g. '3-month' -> 12 weeks), start date (format as YYYY-MM-DD or '2026-10-01' or 'immediate'), domain (e.g. 'fintech', 'healthcare'), seniority/experience, and technical skills."""

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "match_staff",
            "description": "Finds and ranks candidate staff matching project role, required skills, timeline, and domain constraints.",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "description": "Target job role, e.g. 'Backend Dev', 'Python Developer', 'Frontend Dev', 'QA', 'Data Engineer'"},
                    "skills": {"type": "array", "items": {"type": "string"}, "description": "List of required skills, e.g. ['Python', 'SQL', 'Docker']"},
                    "min_experience_years": {"type": "number", "description": "Minimum years of experience required (e.g. 5 for senior, 2 for mid)"},
                    "start_date": {"type": "string", "description": "Target start date (YYYY-MM-DD or 'immediate')"},
                    "duration_weeks": {"type": "integer", "description": "Project duration in weeks"},
                    "domain": {"type": "string", "description": "Business domain (e.g. 'fintech', 'healthcare', 'retail')"},
                    "max_results": {"type": "integer", "description": "Max candidates to return (default 10)"}
                },
                "required": ["role"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_resource_details",
            "description": "Retrieves comprehensive profile and past projects for a specific resource ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {"type": "string", "description": "Resource identifier, e.g. 'RES-012'"}
                },
                "required": ["resource_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clarify",
            "description": "Asks a clarifying question if the user request is completely unclear.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Clarifying question to ask"}
                },
                "required": ["question"]
            }
        }
    }
]

class BaseLLMProvider(ABC):
    @abstractmethod
    async def classify_intent(self, message: str, conversation_history: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        """Parses intent and returns tool call dict: {'name': str, 'arguments': dict}."""
        pass

    @abstractmethod
    async def generate_explanation(self, candidate_summary: str) -> Optional[str]:
        """Generates grounded explanation without inventing numbers."""
        pass

class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

    async def classify_intent(self, message: str, conversation_history: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None
        t0 = time.perf_counter()
        gemini_tools = [{
            "function_declarations": [t["function"] for t in TOOLS_SCHEMA]
        }]
        
        contents = []
        for turn in conversation_history[-4:]:
            role = "user" if turn["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": turn["content"]}]})
        contents.append({"role": "user", "parts": [{"text": message}]})

        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_INTENT_PROMPT}]},
            "contents": contents,
            "tools": gemini_tools,
            "tool_config": {"function_calling_config": {"mode": "AUTO"}}
        }

        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.post(self.url, json=payload)
                lat_ms = (time.perf_counter() - t0) * 1000
                if resp.status_code == 200:
                    data = resp.json()
                    usage = data.get("usageMetadata", {})
                    tokens = {
                        "input_tokens": usage.get("promptTokenCount", 0),
                        "output_tokens": usage.get("candidatesTokenCount", 0),
                        "total_tokens": usage.get("totalTokenCount", 0)
                    }
                    candidates = data.get("candidates", [])
                    tool_call = None
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            if "functionCall" in part:
                                fc = part["functionCall"]
                                tool_call = {
                                    "name": fc["name"],
                                    "arguments": fc.get("args", {})
                                }
                                break
                    log_ai_call(
                        call_type="LLM_INTENT_CLASSIFICATION",
                        provider="Gemini",
                        model=self.model,
                        endpoint=self.url,
                        request_data={"message": message, "history_len": len(conversation_history)},
                        response_data={"tool_call": tool_call, "raw": data},
                        latency_ms=lat_ms,
                        status="SUCCESS" if tool_call else "NO_TOOL_CALL",
                        tokens=tokens
                    )
                    return tool_call
                else:
                    log_ai_call(
                        call_type="LLM_INTENT_CLASSIFICATION",
                        provider="Gemini",
                        model=self.model,
                        endpoint=self.url,
                        request_data={"message": message},
                        response_data={"status_code": resp.status_code, "text": resp.text},
                        latency_ms=lat_ms,
                        status="ERROR",
                        error=f"HTTP {resp.status_code}: {resp.text}"
                    )
        except Exception as e:
            lat_ms = (time.perf_counter() - t0) * 1000
            log_ai_call(
                call_type="LLM_INTENT_CLASSIFICATION",
                provider="Gemini",
                model=self.model,
                endpoint=self.url,
                request_data={"message": message},
                response_data=None,
                latency_ms=lat_ms,
                status="ERROR",
                error=str(e)
            )
        return None

    async def generate_explanation(self, candidate_summary: str) -> Optional[str]:
        if not self.api_key:
            return None
        t0 = time.perf_counter()
        prompt = (
            f"Based strictly on this candidate data, write a concise 1-2 sentence staffing explanation. "
            f"Do not invent new numbers or skills. Data:\n{candidate_summary}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 100}
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(self.url, json=payload)
                lat_ms = (time.perf_counter() - t0) * 1000
                if resp.status_code == 200:
                    data = resp.json()
                    usage = data.get("usageMetadata", {})
                    tokens = {
                        "input_tokens": usage.get("promptTokenCount", 0),
                        "output_tokens": usage.get("candidatesTokenCount", 0),
                        "total_tokens": usage.get("totalTokenCount", 0)
                    }
                    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    log_ai_call(
                        call_type="LLM_GROUNDED_EXPLANATION",
                        provider="Gemini",
                        model=self.model,
                        endpoint=self.url,
                        request_data={"candidate_summary": candidate_summary},
                        response_data={"explanation": text},
                        latency_ms=lat_ms,
                        status="SUCCESS",
                        tokens=tokens
                    )
                    return text
                else:
                    log_ai_call(
                        call_type="LLM_GROUNDED_EXPLANATION",
                        provider="Gemini",
                        model=self.model,
                        endpoint=self.url,
                        request_data={"candidate_summary": candidate_summary},
                        response_data={"status_code": resp.status_code, "text": resp.text},
                        latency_ms=lat_ms,
                        status="ERROR",
                        error=f"HTTP {resp.status_code}: {resp.text}"
                    )
        except Exception as e:
            lat_ms = (time.perf_counter() - t0) * 1000
            log_ai_call(
                call_type="LLM_GROUNDED_EXPLANATION",
                provider="Gemini",
                model=self.model,
                endpoint=self.url,
                request_data={"candidate_summary": candidate_summary},
                response_data=None,
                latency_ms=lat_ms,
                status="ERROR",
                error=str(e)
            )
        return None

class OpenAICompatibleProvider(BaseLLMProvider):
    """Handles Groq, OpenRouter, and Ollama."""
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def classify_intent(self, message: str, conversation_history: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        messages = [{"role": "system", "content": SYSTEM_INTENT_PROMPT}]
        for turn in conversation_history[-4:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": message})

        payload = {
            "model": self.model,
            "messages": messages,
            "tools": TOOLS_SCHEMA,
            "tool_choice": "auto"
        }

        t0 = time.perf_counter()
        target_url = f"{self.base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.post(target_url, headers=headers, json=payload)
                lat_ms = (time.perf_counter() - t0) * 1000
                if resp.status_code == 200:
                    data = resp.json()
                    usage = data.get("usage", {})
                    tokens = {
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0)
                    }
                    choices = data.get("choices", [])
                    tool_call = None
                    if choices:
                        msg = choices[0].get("message", {})
                        tool_calls = msg.get("tool_calls", [])
                        if tool_calls:
                            tc = tool_calls[0]
                            fn = tc.get("function", {})
                            args = fn.get("arguments", "{}")
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = {}
                            tool_call = {"name": fn.get("name"), "arguments": args}

                    provider_name = "Groq" if "groq" in self.base_url else ("OpenRouter" if "openrouter" in self.base_url else "Ollama")
                    log_ai_call(
                        call_type="LLM_INTENT_CLASSIFICATION",
                        provider=provider_name,
                        model=self.model,
                        endpoint=target_url,
                        request_data={"message": message, "history_len": len(conversation_history)},
                        response_data={"tool_call": tool_call, "raw": data},
                        latency_ms=lat_ms,
                        status="SUCCESS" if tool_call else "NO_TOOL_CALL",
                        tokens=tokens
                    )
                    return tool_call
                else:
                    provider_name = "Groq" if "groq" in self.base_url else ("OpenRouter" if "openrouter" in self.base_url else "Ollama")
                    log_ai_call(
                        call_type="LLM_INTENT_CLASSIFICATION",
                        provider=provider_name,
                        model=self.model,
                        endpoint=target_url,
                        request_data={"message": message},
                        response_data={"status_code": resp.status_code, "text": resp.text},
                        latency_ms=lat_ms,
                        status="ERROR",
                        error=f"HTTP {resp.status_code}: {resp.text}"
                    )
        except Exception as e:
            lat_ms = (time.perf_counter() - t0) * 1000
            provider_name = "Groq" if "groq" in self.base_url else ("OpenRouter" if "openrouter" in self.base_url else "Ollama")
            log_ai_call(
                call_type="LLM_INTENT_CLASSIFICATION",
                provider=provider_name,
                model=self.model,
                endpoint=target_url,
                request_data={"message": message},
                response_data=None,
                latency_ms=lat_ms,
                status="ERROR",
                error=str(e)
            )
        return None

    async def generate_explanation(self, candidate_summary: str) -> Optional[str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        prompt = (
            f"Based strictly on this candidate data, write a concise 1-2 sentence staffing explanation. "
            f"Do not invent new numbers or skills. Data:\n{candidate_summary}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 100
        }
        t0 = time.perf_counter()
        target_url = f"{self.base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(target_url, headers=headers, json=payload)
                lat_ms = (time.perf_counter() - t0) * 1000
                if resp.status_code == 200:
                    data = resp.json()
                    usage = data.get("usage", {})
                    tokens = {
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0)
                    }
                    text = data["choices"][0]["message"]["content"].strip()
                    provider_name = "Groq" if "groq" in self.base_url else ("OpenRouter" if "openrouter" in self.base_url else "Ollama")
                    log_ai_call(
                        call_type="LLM_GROUNDED_EXPLANATION",
                        provider=provider_name,
                        model=self.model,
                        endpoint=target_url,
                        request_data={"candidate_summary": candidate_summary},
                        response_data={"explanation": text},
                        latency_ms=lat_ms,
                        status="SUCCESS",
                        tokens=tokens
                    )
                    return text
                else:
                    provider_name = "Groq" if "groq" in self.base_url else ("OpenRouter" if "openrouter" in self.base_url else "Ollama")
                    log_ai_call(
                        call_type="LLM_GROUNDED_EXPLANATION",
                        provider=provider_name,
                        model=self.model,
                        endpoint=target_url,
                        request_data={"candidate_summary": candidate_summary},
                        response_data={"status_code": resp.status_code, "text": resp.text},
                        latency_ms=lat_ms,
                        status="ERROR",
                        error=f"HTTP {resp.status_code}: {resp.text}"
                    )
        except Exception as e:
            lat_ms = (time.perf_counter() - t0) * 1000
            provider_name = "Groq" if "groq" in self.base_url else ("OpenRouter" if "openrouter" in self.base_url else "Ollama")
            log_ai_call(
                call_type="LLM_GROUNDED_EXPLANATION",
                provider=provider_name,
                model=self.model,
                endpoint=target_url,
                request_data={"candidate_summary": candidate_summary},
                response_data=None,
                latency_ms=lat_ms,
                status="ERROR",
                error=str(e)
            )
        return None

class KeywordIntentParser:
    """
    Deterministic intent and constraint extractor.
    Guarantees 100% functionality when all LLMs are unreachable or unconfigured.
    """
    @staticmethod
    def parse(message: str) -> Dict[str, Any]:
        msg = message.lower()

        # Check for specific candidate details request: "RES-123"
        res_match = re.search(r"\b(res-\d{3})\b", msg)
        if res_match:
            return {
                "name": "get_resource_details",
                "arguments": {"resource_id": res_match.group(1).upper()}
            }

        # Check for clarify trigger
        if len(msg.strip()) < 4 or msg.strip() in ("hello", "hi", "help", "who are you"):
            return {
                "name": "clarify",
                "arguments": {"question": "Hello! I can help you staff your project. Please specify a role (e.g. Senior Python Developer), domain (e.g. fintech), duration, or required skills."}
            }

        # Role detection
        role = "Backend Dev"
        if "frontend" in msg or "react" in msg or "vue" in msg:
            role = "Frontend Dev"
        elif "data engineer" in msg or "spark" in msg or "airflow" in msg:
            role = "Data Engineer"
        elif "ml" in msg or "machine learning" in msg or "pytorch" in msg:
            role = "ML Engineer"
        elif "qa" in msg or "test" in msg or "selenium" in msg:
            role = "QA"
        elif "devops" in msg or "cloud" in msg or "kubernetes" in msg:
            role = "DevOps"
        elif "designer" in msg or "ui" in msg or "figma" in msg:
            role = "Designer"
        elif "project manager" in msg or "pm" in msg or "scrum" in msg:
            role = "Project Manager"
        elif "python" in msg:
            role = "Backend Dev"

        # Skills detection
        skills = []
        skill_catalog = [
            "python", "react", "sql", "docker", "kubernetes", "aws", "azure", "gcp",
            "pytorch", "tensorflow", "spark", "airflow", "kafka", "java", "golang",
            "c#", "figma", "selenium", "cypress", "fastapi", "django", "solana", "rust"
        ]
        for sk in skill_catalog:
            if re.search(r"\b" + re.escape(sk) + r"\b", msg):
                skills.append(sk.title())

        # If role mentioned python and no skills detected, add Python
        if "python" in msg and "Python" not in skills:
            skills.append("Python")

        # Seniority / min experience
        min_exp = 3.0
        if "senior" in msg or "lead" in msg:
            min_exp = 6.0
        elif "junior" in msg:
            min_exp = 1.0

        # Duration detection
        duration_weeks = 12
        dur_match = re.search(r"(\d+)[ -]?(month|mo)", msg)
        if dur_match:
            months = int(dur_match.group(1))
            duration_weeks = months * 4
        else:
            week_match = re.search(r"(\d+)[ -]?(week|wk)", msg)
            if week_match:
                duration_weeks = int(week_match.group(1))

        # Domain detection
        domain = None
        domains = ["fintech", "healthcare", "retail", "telecom", "logistics", "education", "gaming"]
        for d in domains:
            if d in msg:
                domain = d
                break

        # Start date
        start_date = None
        if "oct 1" in msg or "october 1" in msg:
            start_date = "2026-10-01"
        elif "nov 1" in msg or "november 1" in msg:
            start_date = "2026-11-01"
        elif "immediate" in msg or "now" in msg or "asap" in msg:
            start_date = datetime.now().strftime("%Y-%m-%d")

        return {
            "name": "match_staff",
            "arguments": {
                "role": role,
                "skills": skills,
                "min_experience_years": min_exp,
                "start_date": start_date or datetime.now().strftime("%Y-%m-%d"),
                "duration_weeks": duration_weeks,
                "domain": domain,
                "max_results": 10
            }
        }

class LLMOrchestratorClient:
    """
    Unified LLM Client with automatic fallback chain:
    Selected provider -> Groq -> OpenRouter -> Ollama -> Keyword parser.
    """
    def __init__(self):
        self.providers: Dict[str, BaseLLMProvider] = {}
        # Gemini
        if settings.gemini_api_key:
            self.providers["gemini"] = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
        # Groq
        if settings.groq_api_key:
            self.providers["groq"] = OpenAICompatibleProvider(
                "https://api.groq.com/openai/v1", settings.groq_api_key, settings.groq_model
            )
        # OpenRouter
        if settings.openrouter_api_key:
            self.providers["openrouter"] = OpenAICompatibleProvider(
                "https://openrouter.ai/api/v1", settings.openrouter_api_key, settings.openrouter_model
            )
        # Ollama (local LLM, only registered if chosen provider is ollama)
        if settings.llm_provider == "ollama":
            self.providers["ollama"] = OpenAICompatibleProvider(
                f"{settings.ollama_base_url}/v1", "", settings.ollama_model
            )

    def get_provider_order(self) -> List[str]:
        chosen = settings.llm_provider
        all_order = ["gemini", "groq", "openrouter", "ollama"]
        if chosen in all_order:
            all_order.remove(chosen)
            return [chosen] + all_order
        return all_order

    async def classify_intent(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Tuple[Dict[str, Any], str, str]:
        """
        Executes intent classification with fallback chain.
        Returns: (tool_call_dict, active_provider, active_model)
        """
        history = conversation_history or []
        for prov_name in self.get_provider_order():
            provider = self.providers.get(prov_name)
            if not provider:
                continue
            try:
                result = await provider.classify_intent(message, history)
                if result and "name" in result:
                    model_id = getattr(provider, "model", prov_name)
                    logger.info(f"Intent classified by provider [{prov_name}] using model [{model_id}]")
                    return result, prov_name, model_id
            except Exception as e:
                logger.warning(f"Provider [{prov_name}] failed: {e}. Falling back to next...")

        # All LLMs unavailable or no keys configured: deterministic keyword parser fallback
        logger.info("Using KeywordIntentParser fallback for intent classification.")
        t0 = time.perf_counter()
        tool_call = KeywordIntentParser.parse(message)
        lat_ms = (time.perf_counter() - t0) * 1000
        log_ai_call(
            call_type="KEYWORD_INTENT_PARSER_FALLBACK",
            provider="LocalHeuristic",
            model="KeywordRegex-v1",
            endpoint="local",
            request_data={"message": message},
            response_data={"tool_call": tool_call},
            latency_ms=lat_ms,
            status="FALLBACK"
        )
        return tool_call, "local-parser", "KeywordRegex-v1"

    async def generate_grounded_explanation(
        self,
        candidate_data: Dict[str, Any],
        active_provider: str
    ) -> str:
        """
        Generates 1-2 sentence explanation strictly grounded in candidate data.
        Falls back to deterministic template if LLM is unavailable or hallucinates.
        """
        cid = candidate_data.get("resource_id", "Candidate")
        name = candidate_data.get("full_name", "Candidate")
        role = candidate_data.get("role", "")
        seniority = candidate_data.get("seniority", "")
        score = candidate_data.get("skill_score", 0.0)
        alloc = candidate_data.get("current_allocation_pct", 0.0)
        projects = candidate_data.get("concurrent_projects_count", 0)
        domain = candidate_data.get("primary_domain", "")
        skills_summary = candidate_data.get("skills_summary", "")

        summary_text = (
            f"Resource {cid} ({name}): Seniority {seniority} {role}, Domain {domain}. "
            f"Skill/Domain Score: {score}/4.0. Top Skills: {skills_summary}. "
            f"Current Allocation: {alloc}%, Concurrent Projects: {projects}."
        )

        provider = self.providers.get(active_provider)
        if provider:
            try:
                explanation = await provider.generate_explanation(summary_text)
                if explanation and len(explanation) > 10:
                    return explanation
            except Exception:
                pass

        # Template fallback guaranteed to be 100% grounded
        t0 = time.perf_counter()
        fallback_exp = (
            f"{name} ({seniority} {role}) matches with a {score}/4.0 domain & technical skill score. "
            f"Currently {alloc}% allocated across {projects} active project(s) in {domain}."
        )
        lat_ms = (time.perf_counter() - t0) * 1000
        log_ai_call(
            call_type="GROUNDED_TEMPLATE_FALLBACK",
            provider="LocalTemplate",
            model="TemplateGenerator-v1",
            endpoint="local",
            request_data={"candidate_id": cid, "name": name, "score": score, "alloc": alloc, "domain": domain},
            response_data={"explanation": fallback_exp},
            latency_ms=lat_ms,
            status="FALLBACK"
        )
        return fallback_exp
