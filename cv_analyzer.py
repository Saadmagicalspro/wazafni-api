"""
Wazafni CV Analyzer v4.0
Production-grade CV analysis using OpenAI GPT-4o-mini + text-embedding-3-small
Saves results directly to Supabase cv_analysis table
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
import httpx
import json
import uuid
import time
import os
from datetime import datetime

router = APIRouter(prefix="/api/cv", tags=["CV Analyzer"])

# ─── Config ───────────────────────────────────────────────────────────────────
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
SUPABASE_URL = "https://gqulqneqynhxxybupkbi.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdxdWxxbmVxeW5oeHh5YnVwa2JpIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NDg1ODk2MiwiZXhwIjoyMDkwNDM0OTYyfQ.qssMYJoNthfHw_kxgkRCjADjsm51UdxnAg2G5rtu0zI"

SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

OPENAI_HEADERS = {
    "Authorization": f"Bearer {OPENAI_KEY}",
    "Content-Type": "application/json"
}

# ─── Models ───────────────────────────────────────────────────────────────────
class CVAnalyzeRequest(BaseModel):
    candidate_id: Optional[str] = None
    cv_text: str
    target_role: Optional[str] = "General"

class CVAnalyzeResponse(BaseModel):
    success: bool
    candidate_id: str
    overall_score: int
    skills_extracted: List[str]
    experience_years: int
    market_fit_score: int
    career_level: str
    ai_summary: str
    embedding_dims: int
    processing_time_ms: int
    record_saved: bool

# ─── Core Functions ───────────────────────────────────────────────────────────
async def analyze_cv_with_gpt(cv_text: str, target_role: str) -> dict:
    """Call GPT-4o-mini to analyze CV and return structured JSON"""
    prompt = f"""You are an expert HR consultant specializing in the Gulf/Saudi Arabia job market.
Analyze this CV for the role: {target_role}

CV TEXT:
{cv_text[:4000]}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "overall_score": <0-100>,
  "skills_extracted": ["skill1", "skill2", ...],
  "experience_years": <number>,
  "education_parsed": {{"degree": "...", "field": "...", "university": "..."}},
  "languages_detected": ["Arabic", "English"],
  "strengths": ["strength1", "strength2", "strength3"],
  "weaknesses": ["weakness1", "weakness2"],
  "improvement_tips": ["tip1", "tip2", "tip3"],
  "rewrite_suggestions": ["suggestion1", "suggestion2"],
  "market_fit_score": <0-100>,
  "career_level": "junior|mid|senior|executive",
  "top_industries": ["industry1", "industry2"],
  "ai_summary": "2-3 sentence professional summary of the candidate"
}}"""

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=OPENAI_HEADERS,
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 1500,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": "You are an expert HR consultant for the Gulf job market. Return ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ]
            }
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

    # Parse JSON from response
    try:
        # Remove markdown code blocks if present
        clean = content.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        return json.loads(clean.strip())
    except json.JSONDecodeError:
        # Try to extract JSON object
        import re
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse GPT response as JSON: {content[:200]}")


async def generate_embedding(text: str) -> list:
    """Generate 768-dim embedding using text-embedding-3-small"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers=OPENAI_HEADERS,
            json={
                "model": "text-embedding-3-small",
                "input": text[:2000],
                "dimensions": 768
            }
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


async def ensure_candidate_exists(candidate_id: str) -> bool:
    """Ensure candidate record exists in candidates table (required by FK constraint)"""
    async with httpx.AsyncClient(timeout=15) as client:
        # Check if exists
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/candidates?id=eq.{candidate_id}&select=id",
            headers=SB_HEADERS
        )
        if r.status_code == 200 and r.json():
            return True  # Already exists
        # Create minimal candidate record
        r2 = await client.post(
            f"{SUPABASE_URL}/rest/v1/candidates",
            headers=SB_HEADERS,
            json={
                "id": candidate_id,
                "full_name": "CV Upload",
                "status": "active",
                "source": "direct"
            }
        )
        return r2.status_code in (200, 201)


async def save_to_supabase(payload: dict) -> dict:
    """Save CV analysis result to Supabase cv_analysis table"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/cv_analysis",
            headers=SB_HEADERS,
            json=payload
        )
        if resp.status_code not in (200, 201):
            raise ValueError(f"Supabase error {resp.status_code}: {resp.text[:300]}")
        result = resp.json()
        return result[0] if isinstance(result, list) else result


# ─── Endpoints ────────────────────────────────────────────────────────────────
@router.post("/analyze", response_model=CVAnalyzeResponse)
async def analyze_cv(request: CVAnalyzeRequest):
    """
    Analyze a CV using GPT-4o-mini, generate semantic embedding, and save to Supabase.
    
    - **candidate_id**: Optional UUID. Auto-generated if not provided.
    - **cv_text**: Full CV text content (required)
    - **target_role**: Target job role for analysis (default: General)
    """
    start_time = time.time()

    # Validate input
    if len(request.cv_text.strip()) < 50:
        raise HTTPException(status_code=400, detail="cv_text is too short (minimum 50 characters)")

    # Generate or validate candidate_id
    candidate_id = request.candidate_id
    if not candidate_id:
        candidate_id = str(uuid.uuid4())
    else:
        try:
            uuid.UUID(candidate_id)
        except ValueError:
            candidate_id = str(uuid.uuid4())

    # Step 1: Analyze CV with GPT-4o-mini
    try:
        analysis = await analyze_cv_with_gpt(request.cv_text, request.target_role)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GPT analysis failed: {str(e)}")

    # Step 2: Generate embedding
    try:
        embedding = await generate_embedding(request.cv_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding generation failed: {str(e)}")

    processing_ms = int((time.time() - start_time) * 1000)

    # Step 3: Save to Supabase
    payload = {
        "candidate_id": candidate_id,
        "overall_score": analysis.get("overall_score", 50),
        "skills_extracted": analysis.get("skills_extracted", []),
        "experience_years": analysis.get("experience_years", 0),
        "education_parsed": analysis.get("education_parsed", {}),
        "languages_detected": analysis.get("languages_detected", []),
        "strengths": analysis.get("strengths", []),
        "weaknesses": analysis.get("weaknesses", []),
        "improvement_tips": analysis.get("improvement_tips", []),
        "rewrite_suggestions": analysis.get("rewrite_suggestions", []),
        "market_fit_score": analysis.get("market_fit_score", 50),
        "embedding": embedding,
        "analysis_version": "4.0",
        "model_used": "gpt-4o-mini",
        "processing_time_ms": processing_ms
    }

    record_saved = False
    try:
        await ensure_candidate_exists(candidate_id)
        await save_to_supabase(payload)
        record_saved = True
    except Exception as e:
        # Don't fail the request if save fails — return analysis anyway
        print(f"[CV Analyzer] Supabase save failed: {e}")

    return CVAnalyzeResponse(
        success=True,
        candidate_id=candidate_id,
        overall_score=analysis.get("overall_score", 50),
        skills_extracted=analysis.get("skills_extracted", []),
        experience_years=analysis.get("experience_years", 0),
        market_fit_score=analysis.get("market_fit_score", 50),
        career_level=analysis.get("career_level", "unknown"),
        ai_summary=analysis.get("ai_summary", ""),
        embedding_dims=len(embedding),
        processing_time_ms=processing_ms,
        record_saved=record_saved
    )


@router.get("/analysis/{candidate_id}")
async def get_cv_analysis(candidate_id: str):
    """Retrieve CV analysis result from Supabase by candidate_id"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/cv_analysis?candidate_id=eq.{candidate_id}&select=candidate_id,overall_score,skills_extracted,experience_years,market_fit_score,strengths,weaknesses,model_used,processing_time_ms,analysis_version,created_at",
            headers=SB_HEADERS
        )
        data = resp.json()
        if not data:
            raise HTTPException(status_code=404, detail="CV analysis not found")
        return data[0]


@router.get("/stats")
async def get_analyzer_stats():
    """Get CV Analyzer statistics from Supabase"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/cv_analysis?select=overall_score,experience_years,market_fit_score,model_used,created_at&order=created_at.desc&limit=100",
            headers=SB_HEADERS
        )
        records = resp.json()
        if not records:
            return {"total": 0, "avg_score": 0}

        scores = [r["overall_score"] for r in records if r.get("overall_score")]
        return {
            "total_analyzed": len(records),
            "avg_overall_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "avg_market_fit": round(sum(r.get("market_fit_score", 0) for r in records) / len(records), 1),
            "model": "gpt-4o-mini",
            "latest_analysis": records[0].get("created_at") if records else None
        }
