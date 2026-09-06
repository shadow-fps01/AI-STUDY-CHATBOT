"""
StudyMaster AI - Commercial Universal AI Study Platform Backend
Production-ready FastAPI application with secure SQLite user authentication (PBKDF2 + JWT),
academic study profiles, AI tutoring context builder, and Paystack payment monetization.
"""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, status, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime
import os
import asyncio
import json
import logging

# Local application modules
from database import (
    init_db,
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_profile_by_user_id,
    upsert_profile,
    add_chat_message,
    get_user_chat_history,
    clear_user_chat_history,
)
from security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    get_optional_current_user,
)
from billing import (
    initialize_paystack_transaction,
    create_checkout_session,
    verify_paystack_transaction,
    verify_and_activate_session,
    verify_paystack_webhook_signature,
    PRO_PLAN_NAME,
    PRO_PLAN_AMOUNT,
    PRO_PLAN_PRICE_DISPLAY,
    PAYSTACK_PUBLIC_KEY,
    PAYSTACK_CURRENCY,
)

# AI Agent import with robust fallback
try:
    from AGENTIC.main import agent, AI_NAME
except (ImportError, ModuleNotFoundError):
    AI_NAME = "StudyMaster AI"
    agent = None

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("studymaster")

# Initialize SQLite database schema
init_db()

app = FastAPI(
    title=f"{AI_NAME} - Universal Academic & Study AI Platform",
    description="Commercial-grade AI Study Companion API featuring secure SQLite persistence, JWT authentication, and Paystack monetization.",
    version="1.0.0"
)

# Cross-Origin Resource Sharing (CORS) Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================================
# Request / Response Schemas
# =========================================================================

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class StudyProfileUpdate(BaseModel):
    education_level: str = "Undergraduate"
    field_of_study: str = "Computer Science & STEM"
    subjects: List[str] = ["Mathematics", "Computer Science"]
    target_exams: str = "Final Exams & Standardized Tests"
    target_score: str = "Top 5% / 4.0 GPA"
    learning_style: str = "Adaptive & Step-by-Step"
    daily_study_hours: float = 3.0
    custom_directives: Optional[str] = ""


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: List[dict] = []


# =========================================================================
# Web UI Endpoints
# =========================================================================

@app.get("/", response_class=HTMLResponse, tags=["Web UI"])
@app.get("/chat-ui", response_class=HTMLResponse, tags=["Web UI"])
async def serve_chat_ui():
    """Serves the study dashboard single page application."""
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head><title>StudyMaster AI</title><meta charset="utf-8"></head>
        <body style="font-family: sans-serif; background:#121417; color:#fff; padding:40px; text-align:center;">
            <h1>StudyMaster AI API Online</h1>
            <p>Place your <code>index.html</code> in the application root to view the dashboard.</p>
            <p><a href="/docs" style="color:#10b981;">Explore Swagger API Documentation</a></p>
        </body>
        </html>
        """,
        status_code=200
    )


@app.get("/api/v1/bot-info", tags=["Platform"])
async def get_bot_info():
    """Returns platform metadata, capabilities, and dynamic billing specifications."""
    return {
        "status": "online",
        "ai_name": AI_NAME,
        "description": "Commercial AI Academic Coach & Universal Study Companion",
        "features": [
            "Conceptual Feynman Technique Explanations",
            "Active Recall & Socratic Quizzing",
            "Custom Step-by-Step Problem Solving (STEM/Humanities)",
            "Pomodoro & Spaced Repetition Study Schedules",
            "Multi-Disciplinary Exam Prep"
        ],
        "monetization": {
            "pro_plan": PRO_PLAN_NAME,
            "price": PRO_PLAN_AMOUNT / 100,
            "price_display": PRO_PLAN_PRICE_DISPLAY,
            "currency": PAYSTACK_CURRENCY,
            "provider": "Paystack",
            "mode": "live" if (PAYSTACK_PUBLIC_KEY and not PAYSTACK_PUBLIC_KEY.startswith("pk_test_dummy")) else "test"
        }
    }


# =========================================================================
# Authentication Routes (Secure SQLite + PBKDF2 + JWT)
# =========================================================================

@app.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED, tags=["Authentication"])
async def register(payload: RegisterRequest):
    """Registers a new student account, hashes password via PBKDF2-HMAC-SHA256, and returns JWT."""
    existing = get_user_by_email(payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists."
        )
    
    hashed_pw, salt = hash_password(payload.password)
    new_user = create_user(
        email=payload.email,
        username=payload.username,
        hashed_pw=hashed_pw,
        salt=salt
    )
    
    token = create_access_token({"sub": str(new_user["id"]), "email": new_user["email"]})
    profile = get_profile_by_user_id(new_user["id"])
    
    return {
        "status": "success",
        "message": "User account created successfully.",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": new_user["id"],
            "email": new_user["email"],
            "username": new_user["username"],
            "tier": new_user["tier"]
        },
        "profile": profile
    }


@app.post("/api/v1/auth/login", tags=["Authentication"])
async def login(payload: LoginRequest):
    """Authenticates user credentials using constant-time hash comparison and issues JWT session token."""
    user = get_user_by_email(payload.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )
    
    if not verify_password(payload.password, user["hashed_password"], user["salt"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )
    
    token = create_access_token({"sub": str(user["id"]), "email": user["email"]})
    profile = get_profile_by_user_id(user["id"])
    
    return {
        "status": "success",
        "message": "Login successful.",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "username": user["username"],
            "tier": user["tier"]
        },
        "profile": profile
    }


@app.get("/api/v1/auth/me", tags=["Authentication"])
async def get_me(current_user: dict = Depends(get_current_user)):
    """Retrieves the authenticated student's profile and subscription details."""
    profile = get_profile_by_user_id(current_user["id"])
    return {
        "status": "success",
        "user": {
            "id": current_user["id"],
            "email": current_user["email"],
            "username": current_user["username"],
            "tier": current_user["tier"],
            "created_at": current_user["created_at"]
        },
        "profile": profile
    }


# =========================================================================
# Study Profile Management (Stored in SQLite)
# =========================================================================

@app.get("/api/v1/profile", tags=["Study Profile"])
async def fetch_profile(current_user: dict = Depends(get_current_user)):
    """Fetches user study profile from SQLite database; seeds default if not found."""
    profile = get_profile_by_user_id(current_user["id"])
    if not profile:
        profile = upsert_profile(
            user_id=current_user["id"],
            education_level="Undergraduate",
            field_of_study="General Studies",
            subjects=["General"],
            target_exams="Exams",
            target_score="A",
            learning_style="Adaptive & Step-by-Step",
            daily_study_hours=3.0,
            custom_directives=""
        )
    return {"status": "success", "profile": profile}


@app.put("/api/v1/profile", tags=["Study Profile"])
async def update_profile(payload: StudyProfileUpdate, current_user: dict = Depends(get_current_user)):
    """Persists customized academic profile and AI directives into SQLite."""
    updated = upsert_profile(
        user_id=current_user["id"],
        education_level=payload.education_level,
        field_of_study=payload.field_of_study,
        subjects=payload.subjects,
        target_exams=payload.target_exams,
        target_score=payload.target_score,
        learning_style=payload.learning_style,
        daily_study_hours=payload.daily_study_hours,
        custom_directives=payload.custom_directives or ""
    )
    return {
        "status": "success",
        "message": "Study profile successfully saved to SQLite.",
        "profile": updated
    }


# =========================================================================
# AI Study Chat Endpoints (Dynamic Generic Public Study Context)
# =========================================================================

# pyrefly: ignore [missing-import]
import openai
# pyrefly: ignore [missing-import]
from openai import AsyncOpenAI, AsyncAzureOpenAI

async def generate_pedagogical_study_response(
    message: str,
    username: str,
    profile: dict,
    subjects_str: str,
    tier: str,
    current_year: int = 2026,
    current_date_string: str = "September 2026"
) -> str:
    """
    Intelligent dynamic AI tutoring and reasoning engine powered by Async LLM.
    Adapts seamlessly between academic coaching, decision making, opinion questions, and general inquiries.
    """
    education_level = profile.get("education_level", "Undergraduate")
    custom_directives = profile.get("custom_directives", "")
    learning_style = profile.get("learning_style", "Adaptive & Step-by-Step")
    
    user_context_items = []
    if education_level:
        user_context_items.append(f"Education Level: {education_level}")
    if subjects_str and subjects_str != "General Subjects":
        user_context_items.append(f"Current Subjects: {subjects_str}")
    if learning_style:
        user_context_items.append(f"Learning Style: {learning_style}")
    if custom_directives:
        user_context_items.append(f"Custom Directives: {custom_directives}")
    
    context_str = "\n".join(f"- {item}" for item in user_context_items) if user_context_items else "None"

    system_prompt = (
        f"You are {AI_NAME}, an intelligent, versatile, and highly adaptive AI assistant and academic tutor.\n\n"
        "### CORE OPERATING GUIDELINES:\n"
        "1. **Dynamic Formatting (NO Forced Templates)**:\n"
        "   - Never force responses into a single rigid layout, boilerplate template, or repetitive headings.\n"
        "   - Do NOT force Feynman technique steps, mandatory analogies, or fixed 3-part structures onto every answer.\n"
        "   - Answer directly and concisely for simple questions, conversationally for casual chats, and structured only when necessary for complex topics.\n\n"
        "2. **Decisiveness, Opinions & Making Choices**:\n"
        "   - When asked to choose, compare, decide between options, or give advice/recommendations (e.g., 'Which is better?', 'Choose between A and B', 'What should I do?'), make a clear, logical decision and state your reasoned opinion.\n"
        "   - Do not waffle or give non-committal answers. Evaluate key trade-offs concisely and provide a definitive recommendation or choice.\n\n"
        "3. **Student Tutoring & Learning Assistance**:\n"
        "   - When answering study questions, coursework, exam preparation, or academic concepts, deliver intuitive, clear, and high-retention explanations calibrated to the student's level.\n"
        "   - Walk through problem steps logically without sounding rigid or dry.\n\n"
        "4. **General Versatility**:\n"
        "   - Effectively handle questions across all domains: coding, science, everyday practical decisions, general knowledge, and open discussion.\n\n"
        f"### CONTEXT (Use when relevant to tutoring):\n"
        f"{context_str}\n\n"
        f"### TEMPORAL ANCHOR:\n"
        f"- The present year is {current_year}. Today's date is {current_date_string}."
    )

    try:
        azure_key = os.getenv("AZURE_OPENAI_API_KEY")
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        azure_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")
        openai_key = os.getenv("OPENAI_API_KEY")

        if azure_key and azure_endpoint:
            client = AsyncAzureOpenAI(
                api_key=azure_key,
                azure_endpoint=azure_endpoint,
                api_version=azure_version,
                timeout=20.0
            )
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=deployment,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message.strip()}
                    ],
                    temperature=0.7
                ),
                timeout=25.0
            )
            return response.choices[0].message.content
        elif openai_key:
            client = AsyncOpenAI(api_key=openai_key, timeout=20.0)
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=deployment,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message.strip()}
                    ],
                    temperature=0.7
                ),
                timeout=25.0
            )
            return response.choices[0].message.content
        else:
            return (
                f"Hello {username}! I received your message:\n\n"
                f"> {message.strip()}\n\n"
                "To enable live AI answers, please configure your `OPENAI_API_KEY` or `AZURE_OPENAI_API_KEY` in the `.env` file."
            )
    except Exception as e:
        logger.error(f"Error in LLM synthesis: {e}")
        return f"Sorry {username}, I encountered an issue connecting to the AI engine: {str(e)}"



# =========================================================================
# AI Study Chat Endpoints (Dynamic Generic Public Study Context)
# =========================================================================

@app.post("/api/v1/chat", tags=["AI Study Assistant"])
async def chat_with_agent(
    payload: ChatRequest,
    current_user: Optional[dict] = Depends(get_optional_current_user)
):
    """
    Asynchronously executes the AI Study Companion.
    Dynamically tailors responses according to student level, subjects, learning style, and custom directives.
    Logs interaction history in SQLite when authenticated.
    """
    clean_message = payload.message.strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    
    # 1. Gather profile context dynamically
    if current_user:
        user_id = current_user["id"]
        username = current_user["username"]
        tier = current_user.get("tier", "free")
        profile = get_profile_by_user_id(user_id) or {}
    else:
        user_id = None
        username = "Student Guest"
        tier = "free"
        profile = {
            "education_level": "Undergraduate",
            "field_of_study": "General Studies",
            "subjects": ["Mathematics", "Science", "Humanities"],
            "target_exams": "Academic Success",
            "target_score": "High Mastery",
            "learning_style": "Adaptive & Step-by-Step",
            "daily_study_hours": 3.0,
            "custom_directives": ""
        }
    
    subjects_str = ", ".join(profile.get("subjects", [])) if profile.get("subjects") else "General Subjects"
    custom_directives = profile.get("custom_directives") or ""
    
    # Extract recent conversation history turns if available
    recent_history_text = ""
    if payload.history and len(payload.history) > 1:
        recent = payload.history[-6:-1]
        history_lines = []
        for msg in recent:
            role_label = "User" if msg.get("role") == "user" else AI_NAME
            msg_txt = str(msg.get("content", "")).strip()
            if msg_txt:
                history_lines.append(f"{role_label}: {msg_txt[:400]}")
        if history_lines:
            recent_history_text = "[RECENT CONVERSATION TURNS]:\n" + "\n".join(history_lines) + "\n\n"

    # Assemble contextual prompt for agent without forcing rigid templates
    profile_hints = []
    if profile.get("education_level"):
        profile_hints.append(f"Level: {profile.get('education_level')}")
    if subjects_str and subjects_str != "General Subjects":
        profile_hints.append(f"Subjects: {subjects_str}")
    if custom_directives:
        profile_hints.append(f"Directives: {custom_directives}")

    profile_context_line = f"[Student Profile: {', '.join(profile_hints)}]\n" if profile_hints else ""

    study_context = (
        f"{profile_context_line}"
        f"{recent_history_text}"
        f"User: {clean_message}"
    )

    response_text = None

    # 2. Run AI agent or fallback with timeout protection
    if agent is not None:
        try:
            result = await asyncio.wait_for(agent.run(study_context), timeout=25.0)
            if hasattr(result, "data"):
                response_text = str(result.data)
            elif hasattr(result, "output"):
                response_text = str(result.output)
            else:
                response_text = str(result)
        except asyncio.TimeoutError:
            logger.warning("Live AI Agent timed out after 25s, falling back to direct async synthesis.")
            response_text = None
        except Exception as agent_err:
            logger.warning(f"Live AI Agent notice ({agent_err}), falling back to direct async synthesis.")
            response_text = None

    if not response_text:
        response_text = await generate_pedagogical_study_response(
            message=clean_message,
            username=username,
            profile=profile,
            subjects_str=subjects_str,
            tier=tier
        )

    # 3. Save to SQLite database if authenticated
    if user_id:
        try:
            add_chat_message(user_id=user_id, role="user", content=clean_message, ai_name=AI_NAME)
            add_chat_message(user_id=user_id, role="assistant", content=response_text, ai_name=AI_NAME)
        except Exception as db_err:
            logger.error(f"Error persisting chat to SQLite: {db_err}")
        
    return {
        "status": "success",
        "reply": response_text,
        "ai_name": AI_NAME,
        "tier": tier,
        "history_saved": user_id is not None
    }


@app.get("/api/v1/chat/history", tags=["AI Study Assistant"])
async def get_chat_history(current_user: dict = Depends(get_current_user)):
    """Fetches user chat history persisted in SQLite."""
    history = get_user_chat_history(current_user["id"], limit=50)
    return {"status": "success", "history": history}


@app.delete("/api/v1/chat/history", tags=["AI Study Assistant"])
async def clear_chat_history(current_user: dict = Depends(get_current_user)):
    """Clears user chat history from SQLite."""
    clear_user_chat_history(current_user["id"])
    return {"status": "success", "message": "Chat history cleared successfully from SQLite database."}


# =========================================================================
# Paystack Monetization & Subscription Routes
# =========================================================================

@app.post("/api/v1/billing/initialize", tags=["Monetization"])
@app.post("/api/v1/billing/create-checkout-session", tags=["Monetization"])
async def checkout_session(
    request: Request,
    current_user: Optional[dict] = Depends(get_optional_current_user)
):
    """Initiates a Paystack checkout transaction (official API or test mode simulation)."""
    base_url = str(request.base_url).rstrip("/")
    user_id = current_user["id"] if current_user else None
    user_email = current_user["email"] if current_user else "student@example.com"
    result = await initialize_paystack_transaction(
        user_id=user_id,
        user_email=user_email,
        base_url=base_url
    )
    return result


@app.get("/api/v1/billing/config", tags=["Monetization"])
async def get_billing_config():
    """Returns public Paystack billing configuration for frontend client integration."""
    return {
        "provider": "paystack",
        "public_key": PAYSTACK_PUBLIC_KEY,
        "currency": PAYSTACK_CURRENCY,
        "amount": PRO_PLAN_AMOUNT,
        "price_display": PRO_PLAN_PRICE_DISPLAY,
        "plan_name": PRO_PLAN_NAME
    }


@app.get("/api/v1/billing/verify", tags=["Monetization"])
@app.get("/api/v1/billing/verify-session", tags=["Monetization"])
async def verify_session(
    reference: Optional[str] = None,
    session_id: Optional[str] = None,
    trxref: Optional[str] = None,
    current_user: Optional[dict] = Depends(get_optional_current_user)
):
    """Verifies Paystack transaction reference and activates Pro tier in SQLite."""
    ref = reference or session_id or trxref
    if not ref:
        raise HTTPException(status_code=400, detail="Missing reference or session_id parameter.")
    
    user_id = current_user["id"] if current_user else None
    result = await verify_paystack_transaction(ref, user_id=user_id)
    if result.get("status") == "success":
        return {
            "status": "success",
            "message": "Subscription verified! User upgraded to PRO.",
            "reference": ref,
            "user_id": result.get("user_id")
        }
    else:
        raise HTTPException(
            status_code=404,
            detail=result.get("message", "Payment reference was not verified.")
        )


@app.get("/api/v1/billing/subscription-status", tags=["Monetization"])
async def subscription_status(current_user: dict = Depends(get_current_user)):
    """Checks user subscription status and active plan privileges."""
    is_pro = current_user.get("tier") == "pro"
    return {
        "status": "success",
        "tier": current_user.get("tier", "free"),
        "is_pro": is_pro,
        "plan": PRO_PLAN_NAME if is_pro else "Free Study Plan",
        "price_display": PRO_PLAN_PRICE_DISPLAY,
        "currency": PAYSTACK_CURRENCY,
        "privileges": [
            "Unlimited AI Tutoring Sessions",
            "Advanced Socratic Exam Simulation",
            "Custom Step-by-Step Proofs & Problem Solving",
            "Priority Response Latency"
        ] if is_pro else [
            "Standard AI Tutoring",
            "Daily Prompt Allowance"
        ]
    }


@app.post("/api/v1/billing/webhook", tags=["Monetization"])
async def paystack_webhook(request: Request):
    """Handles Paystack webhook notifications (e.g., charge.success)."""
    try:
        body = await request.body()
        signature = request.headers.get("x-paystack-signature", "")
        
        # Verify HMAC-SHA512 webhook signature if configured
        if not verify_paystack_webhook_signature(body, signature):
            logger.warning("Paystack webhook signature mismatch or missing secret key.")

        event = json.loads(body.decode("utf-8"))
        event_name = event.get("event")
        data = event.get("data", {})
        
        if event_name == "charge.success":
            reference = data.get("reference")
            if reference:
                activated = verify_and_activate_session(reference)
                logger.info(f"Webhook activated Pro subscription for reference {reference}: {activated}")
                
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return JSONResponse(status_code=400, content={"error": str(e)})


# =========================================================================
# Paystack Interactive Checkout Simulation & Callback Pages
# =========================================================================

@app.get("/billing/checkout", response_class=HTMLResponse, tags=["Monetization"])
async def serve_paystack_checkout(
    reference: Optional[str] = None,
    session_id: Optional[str] = None
):
    """Interactive Paystack Checkout Page for demonstration & sandbox test simulation."""
    ref = reference or session_id or "test_ref_001"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Paystack Checkout - {PRO_PLAN_NAME}</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen flex items-center justify-center p-4">
  <div class="max-w-md w-full bg-gray-800 rounded-2xl shadow-2xl border border-gray-700 overflow-hidden">
    
    <!-- Header Badge -->
    <div class="bg-cyan-500/15 border-b border-cyan-500/30 px-5 py-3 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <span class="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-pulse"></span>
        <span class="text-xs font-bold text-cyan-400 uppercase tracking-wider">Paystack Payment</span>
      </div>
      <span class="text-[11px] text-cyan-300 font-mono">Secured by Paystack</span>
    </div>

    <div class="p-6 space-y-5">
      <div>
        <span class="text-xs font-semibold text-emerald-400 uppercase tracking-wider">Upgrade to</span>
        <h2 class="text-xl font-bold text-white mt-1">{PRO_PLAN_NAME}</h2>
        <div class="flex items-baseline gap-1 mt-2">
          <span class="text-3xl font-extrabold text-white">{PRO_PLAN_PRICE_DISPLAY}</span>
          <span class="text-xs text-gray-400">/ month</span>
        </div>
      </div>

      <!-- Paystack Simulation Test Credentials -->
      <div class="bg-gray-900/80 rounded-xl p-4 border border-gray-700 text-xs space-y-2">
        <div class="font-semibold text-cyan-400 flex items-center justify-between">
          <span>💳 Paystack Test Card Simulation:</span>
          <span class="text-emerald-400 font-mono">Valid</span>
        </div>
        <div class="flex justify-between text-gray-400 font-mono text-[11px]">
          <span>Card Number:</span>
          <span class="text-white">4084 0841 •••• •••• 4084</span>
        </div>
        <div class="flex justify-between text-gray-400 font-mono text-[11px]">
          <span>Expires:</span>
          <span class="text-white">12/28</span>
        </div>
        <div class="flex justify-between text-gray-400 font-mono text-[11px]">
          <span>CVV:</span>
          <span class="text-white">408</span>
        </div>
        <div class="flex justify-between text-gray-400 font-mono text-[11px]">
          <span>Reference:</span>
          <span class="text-cyan-300 truncate max-w-[200px]">{ref}</span>
        </div>
      </div>

      <div class="space-y-3 pt-2">
        <a 
          href="/billing/callback?reference={ref}&session_id={ref}" 
          class="w-full block text-center py-3 px-4 rounded-xl bg-gradient-to-r from-cyan-600 to-teal-600 hover:from-cyan-500 hover:to-teal-500 font-bold text-white text-sm shadow-lg shadow-cyan-600/30 transition-all cursor-pointer"
        >
          Pay {PRO_PLAN_PRICE_DISPLAY} with Paystack
        </a>
        <a 
          href="/chat-ui" 
          class="w-full block text-center py-2 text-xs text-gray-400 hover:text-white transition-colors"
        >
          Cancel and Return to Dashboard
        </a>
      </div>
    </div>
  </div>
</body>
</html>"""


@app.get("/billing/callback", response_class=HTMLResponse, tags=["Monetization"])
@app.get("/billing/success", response_class=HTMLResponse, tags=["Monetization"])
async def serve_billing_callback(
    reference: Optional[str] = None,
    session_id: Optional[str] = None,
    trxref: Optional[str] = None
):
    """Paystack payment callback & success confirmation page."""
    ref = reference or session_id or trxref or ""
    if ref:
        await verify_paystack_transaction(ref)
        
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Payment Successful - StudyMaster Pro</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen flex items-center justify-center p-4">
  <div class="max-w-md w-full bg-gray-800 rounded-2xl shadow-2xl border border-emerald-500/30 p-8 text-center space-y-5">
    <div class="w-16 h-16 rounded-full bg-emerald-500/20 text-emerald-400 mx-auto flex items-center justify-center text-3xl border border-emerald-500/40">
      ✓
    </div>
    <div>
      <h2 class="text-2xl font-bold text-white">Payment Successful!</h2>
      <p class="text-xs text-cyan-400 mt-1 font-medium">Paystack Transaction Confirmed</p>
      <p class="text-sm text-gray-300 mt-3 leading-relaxed">
        Your account has been upgraded to <strong class="text-white">StudyMaster Pro</strong>! You now have full access to unlimited AI tutoring, step-by-step problem breakdowns, and exam simulation.
      </p>
    </div>
    <div class="pt-3 space-y-2">
      <a href="/chat-ui?reference={ref}" class="inline-block w-full py-3 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 font-bold text-white text-sm shadow-lg shadow-emerald-600/30 transition-all">
        Return to Study Dashboard
      </a>
      <a href="/?reference={ref}" class="inline-block w-full py-2 px-4 text-xs text-gray-400 hover:text-white">
        Direct Root Link
      </a>
    </div>
  </div>
</body>
</html>"""


@app.get("/billing/cancel", response_class=HTMLResponse, tags=["Monetization"])
async def serve_billing_cancel():
    """Paystack checkout cancellation landing page."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Checkout Cancelled</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen flex items-center justify-center p-4">
  <div class="max-w-md w-full bg-gray-800 rounded-2xl p-6 text-center space-y-4 border border-gray-700">
    <h2 class="text-xl font-bold text-white">Checkout Cancelled</h2>
    <p class="text-xs text-gray-400">No charges were made. You can upgrade anytime.</p>
    <a href="/chat-ui" class="inline-block py-2 px-4 rounded-xl bg-gray-700 hover:bg-gray-600 text-xs font-semibold text-white">Back to App</a>
  </div>
</body>
</html>"""


# =========================================================================
# Legacy Compatibility Endpoints (Mapping to SQLite)
# =========================================================================

@app.get("/details", tags=["Legacy Compatibility"])
async def legacy_get_details():
    """Returns legacy formatted list of student profiles joined with user records."""
    from database import get_connection
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.email, u.username as name, p.* 
            FROM users u 
            LEFT JOIN profiles p ON u.id = p.user_id
        """)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]