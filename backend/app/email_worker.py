import logging
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SYNC_DB_URL = f"sqlite:///{_BACKEND_DIR}/data/focus.db"
_sync_engine = create_engine(_SYNC_DB_URL, connect_args={"timeout": 60.0})
_SyncSessionLocal = sessionmaker(bind=_sync_engine)

from app.models import Opportunity, SubmittedOpportunity

logger = logging.getLogger(__name__)

# Xavfsiz importlar (agar modul hali to'liq ulanmagan bo'lsa xato bermaydi)
try:
    from app.email_client import fetch_new_emails
except (ImportError, AttributeError):
    def fetch_new_emails() -> List[Dict[str, Any]]:
        return []

try:
    from app.opportunity.delivery import send_telegram_alert
except (ImportError, AttributeError):
    def send_telegram_alert(msg: str):
        logger.info("[Telegram Alert Fallback]: %s", msg)


def extract_domain(email_or_url: Optional[str]) -> str:
    """Email manzili yoki URL'dan asosiy domenni ajratib oladi."""
    if not email_or_url:
        return ""
    val = email_or_url.strip().lower()
    if "@" in val:
        return val.split("@")[-1]
    if "://" in val or val.startswith("www."):
        if not val.startswith("http"):
            val = "https://" + val
        netloc = urlparse(val).netloc
        return netloc.replace("www.", "")
    return val


def process_incoming_email(db: Session, email_message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Yangi kelgan emailni topshirilgan dasturlar bilan thread yoki domen bo'yicha bog'laydi."""
    thread_id = str(email_message.get("thread_id", "")).strip()
    sender = email_message.get("sender", "")
    sender_domain = extract_domain(sender)

    # 1. Thread ID bo'yicha aniq moslik
    if thread_id:
        submission = (
            db.query(SubmittedOpportunity)
            .filter(SubmittedOpportunity.related_email_thread_id == thread_id)
            .first()
        )
        if submission:
            submission.status = "response_received"
            db.commit()
            send_telegram_alert(
                f"Siz topshirgan '{submission.opportunity.title}' dasturi bo'yicha yangi javob keldi!"
            )
            return {"matched_by": "thread_id", "submission_id": submission.id}

    # 2. Jo'natuvchi domeni orqali bog'lash
    if sender_domain:
        active_submissions = (
            db.query(SubmittedOpportunity)
            .join(Opportunity, SubmittedOpportunity.opportunity_id == Opportunity.id)
            .all()
        )
        for sub in active_submissions:
            opp_domain = extract_domain(sub.opportunity.url)
            org_name = (sub.opportunity.organization or "").lower()

            if (opp_domain and (sender_domain == opp_domain or sender_domain.endswith("." + opp_domain))) or                (org_name and org_name in sender_domain):
                if thread_id and not sub.related_email_thread_id:
                    sub.related_email_thread_id = thread_id
                sub.status = "response_received"
                db.commit()
                send_telegram_alert(
                    f"Siz topshirgan '{sub.opportunity.title}' tashkilotidan yangi xat keldi: {email_message.get('subject')}"
                )
                return {"matched_by": "domain", "submission_id": sub.id}

    return None


def run_email_poll_cycle(db: Session):
    """Muntazam email tekshirish sikli."""
    new_emails = fetch_new_emails()
    for mail in new_emails:
        match_result = process_incoming_email(db, mail)
        if match_result:
            logger.info("Email matched to submission: %s", match_result)
        logger.info("Yangi email qabul qilindi: %s", mail.get("id"))


import asyncio

async def email_worker_loop(broadcast=None, *args, **kwargs):
    """Fonda email qabulini muntazam tekshirib turuvchi asinxron sikl."""
    logger.info("[EmailWorker] Sikl ishga tushdi.")
    while True:
        try:
            db = _SyncSessionLocal()
            try:
                run_email_poll_cycle(db)
            finally:
                db.close()
        except Exception as e:
            logger.error("[EmailWorker] Sikl xatosi: %s", e)
        await asyncio.sleep(60)



def check_account_locked(*args, **kwargs) -> bool:
    return False
