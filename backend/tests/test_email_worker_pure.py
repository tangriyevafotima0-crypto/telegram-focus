"""email_worker.py ning SOF funksiyalari (SQLAlchemy kerak emas) AST orqali ajratib sinaladi.
DB/FastAPI oqimi bu muhitda sinalmadi (kutubxonalar yo'q) — HANDOFF ga qarang."""
import ast, os, re, sys, time, importlib.util
from dataclasses import dataclass, field
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(BASE, "app", "email_worker.py")).read()
tree = ast.parse(src)
want = {"_safe_received_at", "poll_seconds", "_register_failure", "_clear_backoff", "_extract_links", "_format_size", "_compose_text", "_attachment_meta"}
body = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in want)
        or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in {"_URL_RE","MIN_POLL_SECONDS","DEFAULT_POLL_SECONDS","BACKOFF_START","BACKOFF_MAX","_backoff"} for t in n.targets))
        or (isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "_backoff")]
mod = ast.Module(body=body, type_ignores=[])
from datetime import datetime, timezone, timedelta
ns = {"utc_now": lambda: datetime.now(timezone.utc), "os": os, "re": re, "time": time, "Any": object, "Optional": object, "ParsedEmail": object}
exec("from typing import Any\nfrom __future__ import annotations", {}) if False else None
ns["__annotations__"] = {}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)] + body, type_ignores=[])), "w", "exec"), ns)

@dataclass
class P:
    subject: str = "Mavzu"; text: str = "Salom https://a.com/x?y=1, va http://b.org."
    attachments: list = field(default_factory=lambda: [{"name": "a.pdf", "size": 2048}, {"name": "b.zip", "size": 3*1024*1024}])
    @property
    def message_text(self): return f"{self.subject}\n\n{self.text}".rstrip()

# 1. havolalar: tinish belgisi kesiladi, faqat http/https, takror yo'q
links = ns["_extract_links"]("a https://a.com/x?y=1, b http://b.org. c javascript:alert(1) d ftp://x.com https://a.com/x?y=1")
assert links == ["https://a.com/x?y=1", "http://b.org"], links
assert len(ns["_extract_links"](" ".join(f"https://x{i}.com" for i in range(50)))) == 20
print("1 OK havolalar")

# 2. matn + ilovalar qatorlari (frontend 📎 formatini kutadi)
t = ns["_compose_text"](P())
assert t.startswith("Mavzu\n\nSalom") and t.endswith("📎 a.pdf (2 KB)\n📎 b.zip (3.0 MB)"), repr(t)
print("2 OK compose")

# 3. eksponensial backoff 60 -> 120 -> ... -> 900 cheklov; tozalash
ns["_backoff"].clear()
seq = [ns["_register_failure"](1) for _ in range(8)]
assert seq == [60, 120, 240, 480, 900, 900, 900, 900], seq
ns["_clear_backoff"](1); assert ns["_register_failure"](1) == 60
print("3 OK backoff", seq)

# 4. EMAIL_POLL_SECONDS: min 30, noto'g'ri qiymat -> 60
for env, exp in [("10", 30), ("45", 45), ("abc", 60), ("", 60)]:
    os.environ["EMAIL_POLL_SECONDS"] = env; assert ns["poll_seconds"]() == exp, (env, ns["poll_seconds"]())
os.environ.pop("EMAIL_POLL_SECONDS"); assert ns["poll_seconds"]() == 60
print("4 OK poll_seconds")
now = datetime.now(timezone.utc)
assert ns["_safe_received_at"](now + timedelta(days=400)) <= datetime.now(timezone.utc)
past = now - timedelta(days=3); assert ns["_safe_received_at"](past) == past
print("5 OK kelajak sanasi cheklanadi")
print("HAMMASI OK")
