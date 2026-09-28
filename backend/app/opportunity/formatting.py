"""
formatting.py — imkoniyat postini matn qilib formatlash va hash.
Eski monitor.py dan ko'chirilgan (o'zgarishsiz): format_opportunity, _opp_hash.
"""

import hashlib
import re
from datetime import date


def _opp_hash(opp) -> str:
    """Imkoniyat uchun yagona hash (takror oldini olish)."""
    key = f"{opp.title[:60].lower().strip()}|{opp.deadline}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def format_opportunity(opp, channel_name: str) -> str:
    """Bitta imkoniyatni Telegram xabari uchun formatlaydi."""
    def _md_safe(text: str) -> str:
        if not text:
            return ""
        for ch in ["*", "_", "`", "[", "]"]:
            text = text.replace(ch, "")
        return text

    title = _md_safe(opp.title[:120])
    lines = [f"🎯 **{title}**"]

    if opp.deadline:
        days_left = (opp.deadline - date.today()).days
        if days_left <= 3:
            lines.append(f"⏰ **{days_left} kun qoldi!** ({opp.deadline})")
        elif days_left <= 7:
            lines.append(f"📅 {days_left} kun qoldi ({opp.deadline})")
        else:
            lines.append(f"📅 {opp.deadline} ({days_left} kun)")

    if opp.is_free:
        lines.append("💰 Bepul / Grant")
    if opp.fields:
        lines.append(f"🏷 {_md_safe(', '.join(opp.fields))}")
    if opp.match_reasons:
        reasons_clean = _md_safe(" · ".join(r.lstrip("✅✓ ") for r in opp.match_reasons[:3]))
        lines.append("✅ " + reasons_clean)
    lines.append(f"📎 {_md_safe(channel_name)}")
    if opp.link:
        lines.append(f"🔗 {opp.link}")

    return "\n".join(lines)


def parse_formatted_meta(text: str) -> dict:
    """
    format_opportunity() natijasidan (qat'iy belgilar: 🎯 ⏰/📅 💰 🏷 ✅ 📎 🔗) UI uchun
    meta'ni ajratadi: title, deadline (ISO|None), fields[list], is_free, reasons, link.
    Ball matnda YO'Q — u alohida saqlanadi (Message.opp_score) yoki None.
    """
    meta = {"title": "", "deadline": None, "fields": [], "is_free": False, "reasons": "", "link": None}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("🎯"):
            meta["title"] = line[1:].strip().strip("*").strip()
        elif line.startswith("⏰") or line.startswith("📅"):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", line)
            if m:
                meta["deadline"] = m.group(1)
        elif line.startswith("💰"):
            meta["is_free"] = True
        elif line.startswith("🏷"):
            meta["fields"] = [f.strip() for f in line[1:].split(",") if f.strip()]
        elif line.startswith("✅"):
            meta["reasons"] = line[1:].strip()
        elif line.startswith("🔗"):
            meta["link"] = line[1:].strip() or None
    return meta
