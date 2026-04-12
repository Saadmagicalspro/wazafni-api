"""
Wazafni Hiring OS - FastAPI Backend v1.0
Core APIs: CV Upload, Jobs, Matches, Events, Subscriptions
"""
from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks, UploadFile, File
from revenue import router as revenue_router
from cv_analyzer import router as cv_analyzer_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import httpx
import os
import json
from datetime import datetime

app = FastAPI(
    title="Wazafni Hiring OS API",
    description="Core APIs for Wazafni Hiring Platform",
    version="1.0.0"
)

# Include Revenue Engine
app.include_router(revenue_router)
# Include CV Analyzer v4.0
app.include_router(cv_analyzer_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Config
SUPABASE_URL = "https://gqulqneqynhxxybupkbi.supabase.co"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdxdWxxbmVxeW5oeHh5YnVwa2JpIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NDg1ODk2MiwiZXhwIjoyMDkwNDM0OTYyfQ.qssMYJoNthfHw_kxgkRCjADjsm51UdxnAg2G5rtu0zI"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdxdWxxbmVxeW5oeHh5YnVwa2JpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ4NTg5NjIsImV4cCI6MjA5MDQzNDk2Mn0.OOSduWJUQw0_IA0RBu5r07bjZaAG6aUVcjAtddoU76Y"
N8N_URL = "https://n8n.wazafni.net"
N8N_WEBHOOK_CV = f"{N8N_URL}/webhook/cv-supabase"

SB_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# ─── Models ───────────────────────────────────────────────────────────────────

class CandidateCreate(BaseModel):
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    current_title: Optional[str] = None
    years_experience: Optional[int] = 0
    skills: Optional[List[str]] = []
    cv_url: Optional[str] = None
    cv_raw_text: Optional[str] = None
    nationality: Optional[str] = None
    current_location: Optional[str] = None

class JobCreate(BaseModel):
    title: str
    description: Optional[str] = None
    location: Optional[str] = "Saudi Arabia"
    job_type: Optional[str] = "full_time"
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    skills_required: Optional[List[str]] = []
    experience_min: Optional[int] = 0
    category: Optional[str] = None
    company_id: Optional[str] = None

class SubscriptionCreate(BaseModel):
    company_id: str
    plan: str  # starter, growth, pro
    email: str

class EventCreate(BaseModel):
    type: str
    payload: Optional[dict] = {}
    source: Optional[str] = "api"
    related_id: Optional[str] = None
    related_type: Optional[str] = None

# ─── Helpers ──────────────────────────────────────────────────────────────────

async def sb_get(path: str, params: str = "") -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SUPABASE_URL}/rest/v1/{path}{params}", headers=SB_HEADERS, timeout=15)
        return r.json()

async def sb_post(path: str, data: dict) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{SUPABASE_URL}/rest/v1/{path}", headers=SB_HEADERS, json=data, timeout=15)
        if r.status_code in [200, 201]:
            return r.json()
        raise HTTPException(status_code=r.status_code, detail=r.text)

async def sb_patch(path: str, data: dict) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.patch(f"{SUPABASE_URL}/rest/v1/{path}", headers=SB_HEADERS, json=data, timeout=15)
        return r.json()

async def log_event(event_type: str, payload: dict = {}, related_id: str = None, related_type: str = None):
    try:
        await sb_post("events", {
            "type": event_type,
            "payload": payload,
            "source": "api",
            "related_id": related_id,
            "related_type": related_type,
            "status": "completed"
        })
    except:
        pass  # Don't fail on event logging

# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "service": "Wazafni Hiring OS API", "version": "1.0.0"}

@app.get("/health")
async def health():
    # Check Supabase
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{SUPABASE_URL}/rest/v1/candidates?select=count&limit=1",
                                headers=SB_HEADERS, timeout=5)
            sb_ok = r.status_code in [200, 206]
    except:
        sb_ok = False

    return {
        "status": "healthy" if sb_ok else "degraded",
        "supabase": "connected" if sb_ok else "error",
        "timestamp": datetime.utcnow().isoformat()
    }

# ─── Dashboard Stats ──────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    """Get dashboard statistics from Supabase"""
    async with httpx.AsyncClient() as client:
        # Parallel requests
        headers_count = {**SB_HEADERS, "Prefer": "count=exact"}
        
        results = {}
        tables = {
            "candidates": "candidates?select=count",
            "companies": "companies?select=count",
            "jobs": "jobs?status=eq.active&select=count",
            "matches": "matches?select=count",
            "events_today": "events?created_at=gte." + datetime.utcnow().strftime("%Y-%m-%d") + "&select=count"
        }
        
        for key, path in tables.items():
            r = await client.get(f"{SUPABASE_URL}/rest/v1/{path}",
                                headers=headers_count, timeout=10)
            cr = r.headers.get("Content-Range", "0/0")
            results[key] = int(cr.split("/")[1]) if "/" in cr else 0
        
        # Get recent events
        events_r = await client.get(
            f"{SUPABASE_URL}/rest/v1/events?order=created_at.desc&limit=10&select=type,created_at,payload",
            headers=SB_HEADERS, timeout=10
        )
        recent_events = events_r.json() if events_r.status_code == 200 else []
        
        # Get top matches
        matches_r = await client.get(
            f"{SUPABASE_URL}/rest/v1/matches?order=match_score.desc&limit=5&select=match_score,status,candidate_id,job_id",
            headers=SB_HEADERS, timeout=10
        )
        top_matches = matches_r.json() if matches_r.status_code == 200 else []
        
        return {
            "total_candidates": results.get("candidates", 0),
            "total_companies": results.get("companies", 0),
            "active_jobs": results.get("jobs", 0),
            "total_matches": results.get("matches", 0),
            "events_today": results.get("events_today", 0),
            "recent_events": recent_events,
            "top_matches": top_matches,
            "timestamp": datetime.utcnow().isoformat()
        }

# ─── Candidates ───────────────────────────────────────────────────────────────

@app.get("/api/candidates")
async def list_candidates(limit: int = 20, offset: int = 0, status: str = "active"):
    data = await sb_get(f"candidates?status=eq.{status}&order=ai_score.desc&limit={limit}&offset={offset}&select=id,full_name,email,current_title,years_experience,skills,ai_score,status,created_at")
    return {"candidates": data, "limit": limit, "offset": offset}

@app.get("/api/candidates/{candidate_id}")
async def get_candidate(candidate_id: str):
    data = await sb_get(f"candidates?id=eq.{candidate_id}&select=*")
    if not data:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return data[0]

@app.post("/api/candidates")
async def create_candidate(candidate: CandidateCreate, background_tasks: BackgroundTasks):
    data = candidate.dict()
    data["status"] = "active"
    data["source"] = "api"
    result = await sb_post("candidates", data)
    candidate_id = result[0]["id"] if isinstance(result, list) else result.get("id")
    background_tasks.add_task(log_event, "CV_UPLOADED", {"name": candidate.full_name}, candidate_id, "candidate")
    return {"success": True, "candidate_id": candidate_id, "data": result}

@app.post("/api/cv/upload")
async def upload_cv(candidate: CandidateCreate, background_tasks: BackgroundTasks):
    """Upload CV and trigger n8n pipeline"""
    # Save to Supabase
    data = candidate.dict()
    data["status"] = "active"
    data["source"] = "api"
    result = await sb_post("candidates", data)
    candidate_id = result[0]["id"] if isinstance(result, list) else result.get("id")
    
    # Trigger n8n webhook
    try:
        async with httpx.AsyncClient() as client:
            await client.post(N8N_WEBHOOK_CV, json={**data, "id": candidate_id}, timeout=5)
    except:
        pass
    
    background_tasks.add_task(log_event, "CV_UPLOADED", {"name": candidate.full_name, "source": "api"}, candidate_id, "candidate")
    return {"success": True, "candidate_id": candidate_id, "message": "CV uploaded and pipeline triggered"}

# ─── Jobs ─────────────────────────────────────────────────────────────────────

@app.get("/api/jobs")
async def list_jobs(limit: int = 20, offset: int = 0, status: str = "active"):
    data = await sb_get(f"jobs?status=eq.{status}&order=created_at.desc&limit={limit}&offset={offset}&select=id,title,location,job_type,salary_min,salary_max,skills_required,category,source,created_at")
    return {"jobs": data, "limit": limit, "offset": offset}

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    data = await sb_get(f"jobs?id=eq.{job_id}&select=*")
    if not data:
        raise HTTPException(status_code=404, detail="Job not found")
    return data[0]

@app.post("/api/jobs")
async def create_job(job: JobCreate, background_tasks: BackgroundTasks):
    data = job.dict()
    data["status"] = "active"
    data["source"] = "api"
    result = await sb_post("jobs", data)
    job_id = result[0]["id"] if isinstance(result, list) else result.get("id")
    background_tasks.add_task(log_event, "JOB_POSTED", {"title": job.title}, job_id, "job")
    return {"success": True, "job_id": job_id, "data": result}

# ─── Matches ──────────────────────────────────────────────────────────────────

@app.get("/api/matches")
async def list_matches(limit: int = 20, min_score: float = 40.0):
    data = await sb_get(f"matches?match_score=gte.{min_score}&order=match_score.desc&limit={limit}&select=id,candidate_id,job_id,match_score,skills_match,experience_match,status,delivery_batch,created_at")
    return {"matches": data, "count": len(data)}

@app.get("/api/matches/candidate/{candidate_id}")
async def get_candidate_matches(candidate_id: str):
    data = await sb_get(f"matches?candidate_id=eq.{candidate_id}&order=match_score.desc&select=*")
    return {"matches": data}

@app.get("/api/matches/job/{job_id}")
async def get_job_matches(job_id: str):
    data = await sb_get(f"matches?job_id=eq.{job_id}&order=match_score.desc&limit=10&select=*")
    return {"matches": data}

# ─── Events ───────────────────────────────────────────────────────────────────

@app.get("/api/events")
async def list_events(limit: int = 50, event_type: Optional[str] = None):
    path = f"events?order=created_at.desc&limit={limit}"
    if event_type:
        path += f"&type=eq.{event_type}"
    data = await sb_get(path + "&select=id,type,payload,source,status,created_at")
    return {"events": data}

@app.post("/api/events")
async def create_event(event: EventCreate):
    data = event.dict()
    data["status"] = "completed"
    result = await sb_post("events", data)
    return {"success": True, "event": result}

# ─── Companies ────────────────────────────────────────────────────────────────

@app.get("/api/companies")
async def list_companies(limit: int = 20):
    data = await sb_get(f"companies?order=created_at.desc&limit={limit}&select=id,name,industry,crm_stage,subscription_plan,total_views,created_at")
    return {"companies": data}

@app.get("/api/companies/{company_id}")
async def get_company(company_id: str):
    data = await sb_get(f"companies?id=eq.{company_id}&select=*")
    if not data:
        raise HTTPException(status_code=404, detail="Company not found")
    return data[0]

# ─── Subscriptions ────────────────────────────────────────────────────────────

PLANS = {
    "starter": {"price": 299, "cv_limit": 50, "jobs_limit": 5, "features": ["basic_matching", "email_support"]},
    "growth": {"price": 799, "cv_limit": 200, "jobs_limit": 20, "features": ["ai_ranking", "priority_matching", "crm", "chat_support"]},
    "pro": {"price": 1999, "cv_limit": 999999, "jobs_limit": 999999, "features": ["all", "dedicated_manager", "api_access", "white_label"]}
}

@app.get("/api/plans")
async def get_plans():
    return {"plans": PLANS}

@app.post("/api/subscribe")
async def create_subscription(sub: SubscriptionCreate, background_tasks: BackgroundTasks):
    if sub.plan not in PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Choose: {list(PLANS.keys())}")
    
    plan_info = PLANS[sub.plan]
    
    # Create subscription record
    sub_data = {
        "company_id": sub.company_id,
        "plan": sub.plan,
        "status": "trialing",
        "cv_limit": plan_info["cv_limit"],
        "cv_used": 0,
        "amount": plan_info["price"],
        "currency": "SAR",
        "billing_cycle": "monthly"
    }
    result = await sb_post("subscriptions", sub_data)
    
    # Update company subscription
    await sb_patch(f"companies?id=eq.{sub.company_id}", {
        "subscription_plan": sub.plan,
        "crm_stage": "trial"
    })
    
    sub_id = result[0]["id"] if isinstance(result, list) else result.get("id")
    background_tasks.add_task(log_event, "SUBSCRIPTION_CREATED", 
                              {"plan": sub.plan, "company_id": sub.company_id, "price": plan_info["price"]},
                              sub_id, "subscription")
    
    return {
        "success": True,
        "subscription_id": sub_id,
        "plan": sub.plan,
        "price": plan_info["price"],
        "currency": "SAR",
        "message": f"Trial started for {sub.plan} plan"
    }

# ─── Webhook from n8n ─────────────────────────────────────────────────────────

@app.post("/webhook/n8n")
async def n8n_webhook(payload: dict):
    """Receive events from n8n workflows"""
    event_type = payload.get("type", "N8N_EVENT")
    await log_event(event_type, payload, payload.get("related_id"), payload.get("related_type"))
    return {"received": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
