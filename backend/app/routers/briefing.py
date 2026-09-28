from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.opportunity.briefing_service import build_briefing_payload, record_submission
from app.opportunity.gemini_analyzer import generate_ai_briefing
from app.opportunity.dashboard_formatter import generate_dashboard_format

router = APIRouter(prefix="/briefing", tags=["briefing"])


@router.get("", response_model=Dict[str, Any])
@router.get("/", response_model=Dict[str, Any])
async def get_daily_briefing(
    generate_ai: bool = Query(True, description="AI 'Rule of One' matnini qo'shish"),
    db: AsyncSession = Depends(get_session),
):
    """
    Kirish briefingi:
    - Telegram & Email filtrlangan tahlili
    - Top-3 bepul (is_paid=False) va match_score >= 70 imkoniyatlar
    - Topshirilgan dasturlar (pipeline) va yaqin muddatlar
    - Rule of One bo'yicha yagona AI vazifasi
    """
    payload = await build_briefing_payload(db)

    ai_message = None
    ai_briefing_dashboard = None
    if generate_ai:
        ai_message = generate_ai_briefing(payload)
        # Stage 4: `ai_briefing` maydoni endi strukturalangan dashboard format
        # ({xulosa, holat, tavsiya, tahlil}) qaytaradi — erkin matn emas.
        ai_briefing_dashboard = generate_dashboard_format(ai_message or "", context="Kunlik briefing")

    return {
        "status": "success",
        "data": payload,
        "ai_briefing": ai_briefing_dashboard,
        "ai_briefing_text": ai_message,
    }


@router.post("/submit", response_model=Dict[str, Any])
async def submit_opportunity(
    opportunity_id: int,
    next_deadline_note: Optional[str] = None,
    db: AsyncSession = Depends(get_session),
):
    """
    Foydalanuvchi 'topshiraman' degan dasturni DB'da saqlash.
    """
    submission = await record_submission(
        session=db,
        opportunity_id=opportunity_id,
        status="submitted",
        next_deadline_note=next_deadline_note,
    )
    return {
        "status": "success",
        "message": "Dastur topshirilganlar ro'yxatiga saqlandi.",
        "submission_id": submission.id,
    }
