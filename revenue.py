"""
Wazafni Revenue Engine v1.0
Manual Billing System (Stripe-ready architecture)
Plans: Starter / Growth / Pro
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import httpx
from datetime import datetime, timedelta
import uuid

router = APIRouter(prefix="/api/revenue", tags=["Revenue"])

SUPABASE_URL = "https://gqulqneqynhxxybupkbi.supabase.co"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdxdWxxbmVxeW5oeHh5YnVwa2JpIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NDg1ODk2MiwiZXhwIjoyMDkwNDM0OTYyfQ.qssMYJoNthfHw_kxgkRCjADjsm51UdxnAg2G5rtu0zI"

SB_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# ─── Plans Definition ─────────────────────────────────────────────────────────

PLANS = {
    "free": {
        "name": "مجاني",
        "name_en": "Free",
        "price_sar": 0,
        "price_usd": 0,
        "billing_cycle": "monthly",
        "cv_limit": 5,
        "jobs_limit": 1,
        "matches_per_job": 3,
        "ai_ranking": False,
        "crm_access": False,
        "api_access": False,
        "priority_support": False,
        "white_label": False,
        "dedicated_manager": False,
        "features": [
            "3 مرشحين لكل وظيفة",
            "وظيفة واحدة نشطة",
            "دعم عبر البريد الإلكتروني"
        ],
        "color": "#6B7280",
        "popular": False
    },
    "starter": {
        "name": "أساسي",
        "name_en": "Starter",
        "price_sar": 299,
        "price_usd": 80,
        "billing_cycle": "monthly",
        "cv_limit": 50,
        "jobs_limit": 5,
        "matches_per_job": 10,
        "ai_ranking": False,
        "crm_access": False,
        "api_access": False,
        "priority_support": False,
        "white_label": False,
        "dedicated_manager": False,
        "features": [
            "50 سيرة ذاتية شهرياً",
            "5 وظائف نشطة",
            "مطابقة ذكية أساسية",
            "تقارير أسبوعية",
            "دعم عبر البريد الإلكتروني"
        ],
        "color": "#3B82F6",
        "popular": False
    },
    "growth": {
        "name": "نمو",
        "name_en": "Growth",
        "price_sar": 799,
        "price_usd": 213,
        "billing_cycle": "monthly",
        "cv_limit": 200,
        "jobs_limit": 20,
        "matches_per_job": 25,
        "ai_ranking": True,
        "crm_access": True,
        "api_access": False,
        "priority_support": True,
        "white_label": False,
        "dedicated_manager": False,
        "features": [
            "200 سيرة ذاتية شهرياً",
            "20 وظيفة نشطة",
            "تقييم AI للمرشحين",
            "CRM متكامل",
            "تقارير يومية",
            "دعم أولوية عبر الدردشة",
            "API محدود"
        ],
        "color": "#8B5CF6",
        "popular": True
    },
    "pro": {
        "name": "احترافي",
        "name_en": "Pro",
        "price_sar": 1999,
        "price_usd": 533,
        "billing_cycle": "monthly",
        "cv_limit": -1,  # unlimited
        "jobs_limit": -1,
        "matches_per_job": -1,
        "ai_ranking": True,
        "crm_access": True,
        "api_access": True,
        "priority_support": True,
        "white_label": True,
        "dedicated_manager": True,
        "features": [
            "سير ذاتية غير محدودة",
            "وظائف غير محدودة",
            "AI Ranking متقدم",
            "CRM + Sales Automation",
            "API كامل",
            "White Label",
            "مدير حساب مخصص",
            "SLA 99.9%"
        ],
        "color": "#F59E0B",
        "popular": False
    }
}

# ─── Models ───────────────────────────────────────────────────────────────────

class SubscriptionRequest(BaseModel):
    company_id: str
    plan: str
    contact_name: str
    contact_email: str
    contact_phone: Optional[str] = None
    billing_cycle: Optional[str] = "monthly"
    notes: Optional[str] = None

class SubscriptionUpgrade(BaseModel):
    subscription_id: str
    new_plan: str
    reason: Optional[str] = None

class UsageCheck(BaseModel):
    company_id: str
    resource: str  # cv, job, match

# ─── Helpers ──────────────────────────────────────────────────────────────────

async def sb_get(path: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=SB_HEADERS, timeout=15)
        return r.json() if r.status_code in [200, 206] else []

async def sb_post(path: str, data: dict) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{SUPABASE_URL}/rest/v1/{path}", headers=SB_HEADERS, json=data, timeout=15)
        if r.status_code in [200, 201]:
            result = r.json()
            return result[0] if isinstance(result, list) else result
        raise HTTPException(status_code=r.status_code, detail=r.text)

async def sb_patch(path: str, data: dict) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.patch(f"{SUPABASE_URL}/rest/v1/{path}", headers=SB_HEADERS, json=data, timeout=15)
        return r.json()

async def log_event(event_type: str, payload: dict = {}, related_id: str = None):
    try:
        await sb_post("events", {
            "type": event_type,
            "payload": payload,
            "source": "revenue_engine",
            "related_id": related_id,
            "related_type": "subscription",
            "status": "completed"
        })
    except:
        pass

# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/plans")
async def get_all_plans():
    """Get all subscription plans with full details"""
    return {
        "plans": PLANS,
        "currency": "SAR",
        "note": "الأسعار بالريال السعودي، تشمل VAT 15%"
    }

@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str):
    if plan_id not in PLANS:
        raise HTTPException(status_code=404, detail="Plan not found")
    return PLANS[plan_id]

@router.post("/subscribe")
async def create_subscription(req: SubscriptionRequest, background_tasks: BackgroundTasks):
    """Create a new subscription (manual billing)"""
    if req.plan not in PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Options: {list(PLANS.keys())}")
    
    plan = PLANS[req.plan]
    now = datetime.utcnow()
    
    # Calculate trial/billing dates
    trial_end = now + timedelta(days=14)
    next_billing = now + timedelta(days=30)
    
    # Create subscription record
    sub_data = {
        "company_id": req.company_id,
        "plan": req.plan,
        "status": "trialing" if req.plan != "free" else "active",
        "cv_limit": plan["cv_limit"] if plan["cv_limit"] != -1 else 999999,
        "cv_used": 0,
        "amount": plan["price_sar"],
        "currency": "SAR",
        "billing_cycle": req.billing_cycle,
        "trial_end": trial_end.isoformat() if req.plan != "free" else None,
        "next_billing_date": next_billing.isoformat() if req.plan != "free" else None,
        "metadata": {
            "contact_name": req.contact_name,
            "contact_email": req.contact_email,
            "contact_phone": req.contact_phone,
            "notes": req.notes,
            "payment_method": "manual",
            "stripe_ready": True  # Flag for future Stripe integration
        }
    }
    
    sub = await sb_post("subscriptions", sub_data)
    sub_id = sub.get("id")
    
    # Update company
    crm_stage = "trial" if req.plan in ["starter", "growth"] else ("paying" if req.plan == "pro" else "new_lead")
    await sb_patch(f"companies?id=eq.{req.company_id}", {
        "subscription_plan": req.plan,
        "crm_stage": crm_stage
    })
    
    # Log event
    background_tasks.add_task(log_event, "SUBSCRIPTION_CREATED", {
        "plan": req.plan,
        "company_id": req.company_id,
        "amount": plan["price_sar"],
        "contact": req.contact_email,
        "trial_end": trial_end.isoformat()
    }, sub_id)
    
    return {
        "success": True,
        "subscription_id": sub_id,
        "plan": req.plan,
        "plan_name": plan["name"],
        "status": sub_data["status"],
        "amount_sar": plan["price_sar"],
        "trial_end": trial_end.isoformat() if req.plan != "free" else None,
        "next_billing": next_billing.isoformat() if req.plan != "free" else None,
        "features": plan["features"],
        "payment_instructions": {
            "method": "bank_transfer",
            "bank": "البنك الأهلي السعودي",
            "iban": "SA0000000000000000000000",  # Placeholder
            "reference": f"WAZ-{sub_id[:8].upper() if sub_id else 'XXXX'}",
            "amount": f"{plan['price_sar']} SAR",
            "note": "سيتم تفعيل الاشتراك خلال 24 ساعة من استلام الدفع"
        }
    }

@router.post("/upgrade")
async def upgrade_subscription(req: SubscriptionUpgrade, background_tasks: BackgroundTasks):
    """Upgrade/downgrade subscription plan"""
    if req.new_plan not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    # Get current subscription
    subs = await sb_get(f"subscriptions?id=eq.{req.subscription_id}&select=*")
    if not subs:
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    current_sub = subs[0]
    old_plan = current_sub.get("plan")
    new_plan_info = PLANS[req.new_plan]
    
    # Update subscription
    await sb_patch(f"subscriptions?id=eq.{req.subscription_id}", {
        "plan": req.new_plan,
        "amount": new_plan_info["price_sar"],
        "cv_limit": new_plan_info["cv_limit"] if new_plan_info["cv_limit"] != -1 else 999999,
        "status": "active"
    })
    
    # Update company
    await sb_patch(f"companies?id=eq.{current_sub['company_id']}", {
        "subscription_plan": req.new_plan,
        "crm_stage": "paying" if req.new_plan in ["growth", "pro"] else "trial"
    })
    
    background_tasks.add_task(log_event, "SUBSCRIPTION_UPGRADED", {
        "from": old_plan,
        "to": req.new_plan,
        "reason": req.reason
    }, req.subscription_id)
    
    return {
        "success": True,
        "old_plan": old_plan,
        "new_plan": req.new_plan,
        "new_price_sar": new_plan_info["price_sar"],
        "features": new_plan_info["features"]
    }

@router.get("/subscription/{company_id}")
async def get_company_subscription(company_id: str):
    """Get current subscription for a company"""
    subs = await sb_get(f"subscriptions?company_id=eq.{company_id}&order=created_at.desc&limit=1&select=*")
    if not subs:
        return {"plan": "free", "status": "active", "plan_details": PLANS["free"]}
    
    sub = subs[0]
    plan_id = sub.get("plan", "free")
    plan_details = PLANS.get(plan_id, PLANS["free"])
    
    # Calculate usage percentage
    cv_used = sub.get("cv_used", 0)
    cv_limit = sub.get("cv_limit", 5)
    usage_pct = round((cv_used / cv_limit * 100), 1) if cv_limit > 0 else 0
    
    return {
        **sub,
        "plan_details": plan_details,
        "usage": {
            "cv_used": cv_used,
            "cv_limit": cv_limit,
            "cv_usage_pct": usage_pct,
            "is_near_limit": usage_pct >= 80
        }
    }

@router.post("/check-usage")
async def check_usage_limit(req: UsageCheck):
    """Check if company can use a resource (cv/job/match)"""
    subs = await sb_get(f"subscriptions?company_id=eq.{req.company_id}&order=created_at.desc&limit=1&select=*")
    
    if not subs:
        plan = PLANS["free"]
        return {"allowed": True, "plan": "free", "limit": plan["cv_limit"], "used": 0}
    
    sub = subs[0]
    plan_id = sub.get("plan", "free")
    plan = PLANS.get(plan_id, PLANS["free"])
    
    if req.resource == "cv":
        limit = sub.get("cv_limit", plan["cv_limit"])
        used = sub.get("cv_used", 0)
        allowed = limit == 999999 or used < limit
        return {
            "allowed": allowed,
            "plan": plan_id,
            "limit": limit,
            "used": used,
            "remaining": max(0, limit - used) if limit != 999999 else "unlimited",
            "upgrade_to": "growth" if plan_id == "starter" else "pro" if plan_id == "growth" else None
        }
    
    return {"allowed": True, "plan": plan_id}

@router.get("/revenue-summary")
async def get_revenue_summary():
    """Get revenue summary for admin dashboard"""
    subs = await sb_get("subscriptions?status=in.(active,trialing)&select=plan,amount,status,created_at")
    
    summary = {
        "total_subscriptions": len(subs),
        "by_plan": {},
        "mrr_sar": 0,
        "arr_sar": 0,
        "trialing": 0,
        "active": 0
    }
    
    for sub in subs:
        plan = sub.get("plan", "free")
        amount = sub.get("amount", 0)
        status = sub.get("status")
        
        if plan not in summary["by_plan"]:
            summary["by_plan"][plan] = {"count": 0, "revenue": 0}
        
        summary["by_plan"][plan]["count"] += 1
        summary["by_plan"][plan]["revenue"] += amount
        summary["mrr_sar"] += amount
        
        if status == "trialing":
            summary["trialing"] += 1
        elif status == "active":
            summary["active"] += 1
    
    summary["arr_sar"] = summary["mrr_sar"] * 12
    
    return summary

@router.post("/cancel/{subscription_id}")
async def cancel_subscription(subscription_id: str, background_tasks: BackgroundTasks):
    """Cancel a subscription"""
    subs = await sb_get(f"subscriptions?id=eq.{subscription_id}&select=*")
    if not subs:
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    sub = subs[0]
    await sb_patch(f"subscriptions?id=eq.{subscription_id}", {
        "status": "canceled",
        "canceled_at": datetime.utcnow().isoformat()
    })
    
    # Downgrade company to free
    await sb_patch(f"companies?id=eq.{sub['company_id']}", {
        "subscription_plan": "free",
        "crm_stage": "churned"
    })
    
    background_tasks.add_task(log_event, "SUBSCRIPTION_CANCELED", {
        "plan": sub.get("plan"),
        "company_id": sub.get("company_id")
    }, subscription_id)
    
    return {"success": True, "message": "Subscription canceled. Downgraded to free plan."}
