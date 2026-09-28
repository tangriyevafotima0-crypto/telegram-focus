import sys, imaplib, email.message, email.policy, base64
import os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# app/__init__ boş; email_client faqat stdlib -> to'g'ridan import
import importlib.util
spec = importlib.util.spec_from_file_location("email_client", os.path.join(BASE, "app", "email_client.py"))
ec = importlib.util.module_from_spec(spec); spec.loader.exec_module(ec)

def build(**k):
    m = email.message.EmailMessage()
    for h, v in k.get("headers", {}).items(): m[h] = v
    return m

# 1. RFC2047 sarlavha + multipart/alternative
m = email.message.EmailMessage()
m["Subject"] = "=?UTF-8?B?" + base64.b64encode("Salom dunyo — Ziyofat".encode()).decode() + "?="
m["From"] = "=?UTF-8?Q?Alisher_Navoiy?= <alisher@example.com>"
m["Date"] = "Sat, 19 Sep 2026 10:00:00 +0500"
m["Message-ID"] = "<abc@x>"
m.set_content("Oddiy matn")
m.add_alternative("<html><body><p>HTML matn</p></body></html>", subtype="html")
p = ec.parse_email_bytes(m.as_bytes(), 5)
assert p.subject == "Salom dunyo — Ziyofat", p.subject
assert p.from_name == "Alisher Navoiy" and p.from_addr == "alisher@example.com"
assert p.text == "Oddiy matn", p.text            # plain ustun
assert p.date.hour == 5 and p.date.tzinfo is not None
assert p.message_id == "<abc@x>"
print("1 OK rfc2047+alternative")

# 2. HTML-only, script/style tashlanadi, XSS teg matnga aylanmaydi
m = email.message.EmailMessage(); m["Subject"]="H"; m["From"]="a@b.c"
m.set_content("<style>x{}</style><script>alert(1)</script><div>Salom<br>dunyo</div><a href='javascript:x'>bos</a>", subtype="html")
p = ec.parse_email_bytes(m.as_bytes(), 1)
assert "alert" not in p.text and "<" not in p.text and "Salom" in p.text and "dunyo" in p.text, repr(p.text)
print("2 OK html-only:", repr(p.text))

# 3. Ilovali xat: faqat metadata
m = email.message.EmailMessage(); m["Subject"]="I"; m["From"]="a@b.c"
m.set_content("matn")
m.add_attachment(b"x"*1234, maintype="application", subtype="pdf", filename="hisobot.pdf")
p = ec.parse_email_bytes(m.as_bytes(), 2)
assert p.attachments == [{"name":"hisobot.pdf","size":1234}], p.attachments
assert "PDF" not in p.text and p.text == "matn"
print("3 OK attachments")

# 4. Buzuq kodirovka (charset noto'g'ri / bayt yaroqsiz)
raw = (b"Subject: =?UTF-8?B?/////w==?=\r\nFrom: x@y.z\r\nContent-Type: text/plain; charset=utf-8\r\n"
       b"Content-Transfer-Encoding: 8bit\r\n\r\nSalom \xff\xfe dunyo\r\n")
p = ec.parse_email_bytes(raw, 3)
assert "Salom" in p.text and "dunyo" in p.text
raw2 = (b"Subject: T\r\nFrom: x@y.z\r\nContent-Type: text/plain; charset=nonexistent-cs\r\n\r\nhello\r\n")
p2 = ec.parse_email_bytes(raw2, 4); assert "hello" in p2.text
raw3 = b"Subject: \xd0\xbf\xd1\x80\r\nFrom: \xff\xfe\r\n\r\nbody"   # xom 8-bit sarlavha
p3 = ec.parse_email_bytes(raw3, 6); assert p3.text == "body"
print("4 OK buzuq kodirovka")

# 5. Matn cheki 20000
m = email.message.EmailMessage(); m["Subject"]="L"; m["From"]="a@b.c"; m.set_content("a"*50000)
p = ec.parse_email_bytes(m.as_bytes(), 7)
assert len(p.text) <= 20000 + len(ec._TEXT_TRUNC_NOTE) and p.text.endswith("qisqartirildi ...]")
print("5 OK 20000 chek")

# 6. Sarlavhasiz / Date yo'q
p = ec.parse_email_bytes(b"\r\nhi", 8); assert p.subject == "(mavzusiz)" and p.date.tzinfo
print("6 OK bo'sh sarlavha")

# ---------------- FakeIMAP
class FakeIMAP:
    def __init__(self, uids, uidvalidity=100, big=None, fail_login=False):
        self.uids = uids; self.uidv = uidvalidity; self.big = big or set()
        self.fail_login = fail_login; self.logged_out = False; self.readonly = None
        self.fetch_calls = []
    def login(self, u, p):
        if self.fail_login: raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
    def select(self, folder, readonly=False):
        self.readonly = readonly; return "OK", [b"1"]
    def response(self, name): return name, [str(self.uidv).encode()]
    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            crit = args[1]
            if crit == "ALL": return "OK", [" ".join(map(str, self.uids)).encode()]
            lo = int(crit.split()[1].split(":")[0])
            # IMAP: "N:*" har doim kamida oxirgi xatni qaytaradi
            sel = [u for u in self.uids if u >= lo] or ([self.uids[-1]] if self.uids else [])
            return "OK", [" ".join(map(str, sel)).encode()]
        if cmd == "FETCH":
            uid = int(args[0]); what = args[1]; self.fetch_calls.append((uid, what))
            if "RFC822.SIZE" in what:
                size = 3_000_000 if uid in self.big else 500
                return "OK", [f"{uid} (UID {uid} RFC822.SIZE {size})".encode()]
            body = (f"Subject: Xat {uid}\r\nFrom: Test <t@x.com>\r\nDate: Sat, 19 Sep 2026 10:00:00 +0000\r\n"
                    f"Message-ID: <{uid}@x>\r\n\r\nMatn {uid}\r\n").encode()
            return "OK", [(f"{uid} (UID {uid} BODY[] {{{len(body)}}}".encode(), body), b")"]
    def logout(self): self.logged_out = True

def run(fake, last_uid=0, stored_v=None):
    ec._IMAP_FACTORY = lambda h, p: fake
    return ec.fetch_new_sync("h", 993, "u", "p", "INBOX", last_uid, stored_v)

# 7. Baseline: 50 xatdan faqat oxirgi 20 ta
f = FakeIMAP(list(range(1, 51)))
r = run(f, 0)
assert [e.uid for e in r.emails] == list(range(31, 51)), [e.uid for e in r.emails]
assert r.new_last_uid == 50 and r.baseline_skipped == 30 and r.uid_validity == 100
assert f.readonly is True and f.logged_out
assert not any("BODY[]" == w or w == "(BODY[])" for _, w in f.fetch_calls)  # faqat PEEK
assert all("PEEK" in w or "SIZE" in w for _, w in f.fetch_calls), f.fetch_calls
print("7 OK baseline (oxirgi 20, last_uid=50, readonly, PEEK)")

# 8. Inkremental: last_uid=50, yangi 51,52
f = FakeIMAP(list(range(1, 53)))
r = run(f, 50, 100)
assert [e.uid for e in r.emails] == [51, 52] and r.new_last_uid == 52
print("8 OK inkremental")

# 9. Yangi xat yo'q: "N:*" oxirgi xatni qaytaradi, lekin u <= last_uid -> filtrlanadi
f = FakeIMAP(list(range(1, 51)))
r = run(f, 50, 100)
assert r.emails == [] and r.new_last_uid == 50
print("9 OK yangi xat yo'q (IMAP '*' qoidasi)")

# 10. UIDVALIDITY o'zgardi -> qayta baseline
f = FakeIMAP(list(range(1, 4)), uidvalidity=999)
r = run(f, 50, 100)
assert [e.uid for e in r.emails] == [1, 2, 3] and r.new_last_uid == 3 and r.uid_validity == 999
print("10 OK UIDVALIDITY o'zgarishi")

# 11. Bo'sh papka
r = run(FakeIMAP([]), 0); assert r.emails == [] and r.new_last_uid == 0
print("11 OK bo'sh papka")

# 12. 2MB+ xat: faqat HEADER
f = FakeIMAP([1, 2], big={2})
r = run(f, 0)
big = [e for e in r.emails if e.uid == 2][0]
assert big.truncated_body and "2 MB" in big.text
assert (2, "(BODY.PEEK[HEADER])") in f.fetch_calls and (2, "(BODY.PEEK[])") not in f.fetch_calls
print("12 OK 2MB cheki")

# 13. Auth xatosi + logout
f = FakeIMAP([1], fail_login=True)
try: run(f, 0); raise SystemExit("XATO")
except ec.EmailAuthError: pass
assert f.logged_out
print("13 OK auth xatosi + logout")

# 14. Tarmoq xatosi
def boom(h, p): raise OSError("timed out")
ec._IMAP_FACTORY = boom
try: ec.fetch_new_sync("h", 993, "u", "p", "INBOX", 0, None); raise SystemExit("XATO")
except ec.EmailConnectionError: pass
print("14 OK tarmoq xatosi")

# 15. check_login + humanize
ec._IMAP_FACTORY = lambda h, p: FakeIMAP([1])
ec.check_login_sync("h", 993, "u", "p", "INBOX")
assert "App Password" in ec.humanize_auth_error("imap.gmail.com", "x")
assert "OAuth2" in ec.humanize_auth_error("outlook.office365.com", "x")
print("15 OK check_login/humanize")
print("HAMMASI OK")
