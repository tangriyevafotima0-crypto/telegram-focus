from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Opportunity, SubmittedOpportunity

try:
    from app.opportunity.store import get_recent_telegram_messages, get_recent_emails
except (ImportError, AttributeError):
    async def get_recent_telegram_messages(limit: int = 50) -> List[Dict[str, Any]]:
        return []
    async def get_recent_emails(limit: int = 50) -> List[Dict[str, Any]]:
        return []


def categorize_telegram_messages(messages: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    important = []
    unimportant = []

    priority_keywords = [
        "stipendiya", "scholarship", "grant", "olimpiada", "olympiad",
        "deadline", "oxirgi muddat", "qabul", "natija", "topshirish", "interview"
    ]

    for msg in messages:
        text = (msg.get("text") or "").lower()
        is_priority = any(kw in text for kw in priority_keywords) or msg.get("is_opportunity_candidate", False)

        item = {
            "id": msg.get("id"),
            "sender": msg.get("sender"),
            "snippet": (msg.get("text") or "")[:120],
            "date": msg.get("date"),
        }
        if is_priority:
            important.append(item)
        else:
            unimportant.append(item)

    return {"important": important, "unimportant": unimportant}


def categorize_emails(emails: List[Dict[str, Any]], submitted_thread_ids: set) -> Dict[str, List[Dict[str, Any]]]:
    admissions_and_direct = []
    automated_notifications = []

    admission_markers = ["admission", "committee", "scholarship", "application", "decision", "interview", "invitation"]
    automated_markers = ["noreply", "no-reply", "notification", "newsletter", "update@", "digest"]

    for email in emails:
        sender = (email.get("sender") or "").lower()
        subject = (email.get("subject") or "").lower()
        thread_id = str(email.get("thread_id", ""))

        is_submitted_reply = thread_id in submitted_thread_ids if thread_id else False
        is_automated = any(marker in sender for marker in automated_markers) and not is_submitted_reply
        is_admission = any(marker in sender or marker in subject for marker in admission_markers)

        item = {
            "id": email.get("id"),
            "thread_id": thread_id,
            "sender": email.get("sender"),
            "subject": email.get("subject"),
            "snippet": (email.get("snippet") or "")[:120],
            "received_at": email.get("received_at"),
            "is_submitted_reply": is_submitted_reply,
        }

        if is_submitted_reply or (is_admission and not is_automated):
            admissions_and_direct.append(item)
        else:
            automated_notifications.append(item)

    return {
        "admissions_and_direct": admissions_and_direct,
        "automated_notifications": automated_notifications,
    }


async def get_top_recommended_opportunities(session: AsyncSession, limit: int = 3) -> List[Dict[str, Any]]:
    now = datetime.utcnow()
    result = await session.execute(
        select(Opportunity)
        .where(
            Opportunity.is_paid.is_(False),
            Opportunity.match_score >= 70.0,
            (Opportunity.deadline.is_(None) | (Opportunity.deadline >= now)),
        )
        .order_by(desc(Opportunity.match_score), Opportunity.deadline.asc().nullslast())
        .limit(limit)
    )
    rows = result.scalars().all()

    results = []
    for opp in rows:
        days_left = (opp.deadline - now).days if opp.deadline else None
        results.append({
            "id": opp.id,
            "title": opp.title,
            "organization": getattr(opp, "organization", None) or getattr(opp, "channel_title", None),
            "match_score": opp.match_score,
            "deadline": opp.deadline.isoformat() if opp.deadline else None,
            "days_left": days_left,
            "is_paid": opp.is_paid,
            "url": getattr(opp, "url", None),
        })
    return results


async def get_pipeline_state(session: AsyncSession) -> Dict[str, Any]:
    now = datetime.utcnow()
    urgent_threshold = now + timedelta(days=3)

    result = await session.execute(
        select(SubmittedOpportunity)
        .order_by(desc(SubmittedOpportunity.submitted_at))
    )
    submitted_list = result.scalars().all()

    items = []
    urgent_alerts = []
    active_thread_ids = set()

    for sub in submitted_list:
        if sub.related_email_thread_id:
            active_thread_ids.add(str(sub.related_email_thread_id))

        is_urgent = False
        if sub.next_deadline and sub.next_deadline >= now:
            if sub.next_deadline <= urgent_threshold:
                is_urgent = True
                urgent_alerts.append({
                    "submission_id": sub.id,
                    "title": sub.opportunity.title if sub.opportunity else "Noma'lum dastur",
                    "next_deadline": sub.next_deadline.isoformat(),
                    "note": sub.next_deadline_note or "Keyingi bosqich muddati yaqinlashmoqda",
                })

        items.append({
            "id": sub.id,
            "opportunity_id": sub.opportunity_id,
            "title": sub.opportunity.title if sub.opportunity else "Noma'lum dastur",
            "status": sub.status,
            "submitted_at": sub.submitted_at.isoformat(),
            "next_deadline": sub.next_deadline.isoformat() if sub.next_deadline else None,
            "next_deadline_note": sub.next_deadline_note,
            "is_urgent": is_urgent,
        })

    return {
        "submissions": items,
        "urgent_alerts": urgent_alerts,
        "active_thread_ids": active_thread_ids,
    }


def determine_rule_of_one_task(
    urgent_alerts: List[Dict[str, Any]],
    admission_replies: List[Dict[str, Any]],
    top_opportunities: List[Dict[str, Any]],
) -> Dict[str, str]:
    if urgent_alerts:
        alert = urgent_alerts[0]
        return {
            "task_type": "URGENT_SUBMISSION_DEADLINE",
            "title": f"'{alert['title']}' bo'yicha keyingi bosqichga tayyorlanish",
            "detail": f"Muddat: {alert['next_deadline']}. Izoh: {alert['note']}",
        }

    submitted_replies = [e for e in admission_replies if e.get("is_submitted_reply")]
    if submitted_replies:
        rep = submitted_replies[0]
        return {
            "task_type": "SUBMISSION_REPLY_ACTION",
            "title": f"Dastur javobini ko'rib chiqish: {rep.get('subject')}",
            "detail": f"Kimdan: {rep.get('sender')}. Xatni o'qib, talab qilingan amalni bajarish.",
        }

    if top_opportunities:
        top_opp = top_opportunities[0]
        deadline_text = f"{top_opp['days_left']} kun qoldi" if top_opp.get("days_left") is not None else "Muddat ochiq"
        return {
            "task_type": "APPLY_TOP_OPPORTUNITY",
            "title": f"'{top_opp['title']}' dasturiga ariza tayyorlash",
            "detail": f"Moslik: {top_opp['match_score']}%, Bepul grant. Muddat: {deadline_text}.",
        }

    return {
        "task_type": "GENERAL_REVIEW",
        "title": "Yangi e'lonlar va pochtani ko'zdan kechirish",
        "detail": "Hozircha shoshilinch topshiriq yo'q. Yangi imkoniyatlar saralanmoqda.",
    }


async def record_submission(
    session: AsyncSession,
    opportunity_id: int,
    status: str = "submitted",
    next_deadline: Optional[datetime] = None,
    next_deadline_note: Optional[str] = None,
    related_email_thread_id: Optional[str] = None,
) -> SubmittedOpportunity:
    submission = SubmittedOpportunity(
        opportunity_id=opportunity_id,
        status=status,
        submitted_at=datetime.utcnow(),
        next_deadline=next_deadline,
        next_deadline_note=next_deadline_note,
        related_email_thread_id=related_email_thread_id,
    )
    session.add(submission)
    await session.commit()
    await session.refresh(submission)
    return submission


async def build_briefing_payload(session: AsyncSession) -> Dict[str, Any]:
    raw_tg = await get_recent_telegram_messages(limit=50)
    raw_emails = await get_recent_emails(limit=50)

    pipeline = await get_pipeline_state(session)
    telegram_summary = categorize_telegram_messages(raw_tg)
    email_summary = categorize_emails(raw_emails, pipeline["active_thread_ids"])
    top_opportunities = await get_top_recommended_opportunities(session, limit=3)

    primary_task = determine_rule_of_one_task(
        urgent_alerts=pipeline["urgent_alerts"],
        admission_replies=email_summary["admissions_and_direct"],
        top_opportunities=top_opportunities,
    )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "primary_focus_task": primary_task,
        "top_opportunities": top_opportunities,
        "pipeline_state": {
            "total_submitted": len(pipeline["submissions"]),
            "urgent_alerts": pipeline["urgent_alerts"],
            "submissions": pipeline["submissions"],
        },
        "email_summary": {
            "admissions_count": len(email_summary["admissions_and_direct"]),
            "admissions_and_direct": email_summary["admissions_and_direct"],
            "automated_notifications_count": len(email_summary["automated_notifications"]),
        },
        "telegram_summary": {
            "important_count": len(telegram_summary["important"]),
            "important": telegram_summary["important"],
            "unimportant_count": len(telegram_summary["unimportant"]),
        },
    }
