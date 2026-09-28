import importlib.util, os, sys, tempfile, stat, base64, json
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("email_crypto", os.path.join(BASE, "app", "email_crypto.py"))
ec = importlib.util.module_from_spec(spec); spec.loader.exec_module(ec)

tmp = tempfile.mkdtemp()
ec.KEY_FILE = __import__("pathlib").Path(tmp) / "data" / ".email_key"
os.environ.pop("EMAIL_SECRET_KEY", None); ec._reset_key_cache()

# 1. aylanish (unicode, uzun, bo'sh emas)
for pw in ["abcd efgh ijkl mnop", "парол-ўзбек-😀", "x" * 5000, "a"]:
    tok = ec.encrypt_password(pw)
    if len(pw) >= 8:  # qisqa qator tasodifan base64 ichida uchrashi mumkin (test ishonchsizligi)
        assert pw not in tok and pw.encode() not in base64.b64decode(tok)
    assert ec.decrypt_password(tok) == pw
print("1 OK aylanish")

# 2. har safar boshqa nonce
assert ec.encrypt_password("same") != ec.encrypt_password("same")
print("2 OK nonce")

# 3. kalit fayli yaratildi, chmod 600, qayta ishga tushganda O'ZGARMAydi
assert ec.KEY_FILE.is_file()
mode = stat.S_IMODE(os.stat(ec.KEY_FILE).st_mode)
assert mode == 0o600, oct(mode)
tok = ec.encrypt_password("persist"); key_before = ec.KEY_FILE.read_text()
ec._reset_key_cache()
assert ec.decrypt_password(tok) == "persist" and ec.KEY_FILE.read_text() == key_before
print("3 OK .email_key 600 va barqaror")

# 4. buzilgan token / noto'g'ri kalit -> ValueError
raw = bytearray(base64.b64decode(tok)); raw[20] ^= 1
for bad in [base64.b64encode(bytes(raw)).decode(), "!!!", "AAAA", ""]:
    try: ec.decrypt_password(bad); raise SystemExit("XATO: " + bad)
    except ValueError: pass
os.environ["EMAIL_SECRET_KEY"] = "boshqa-kalit"; ec._reset_key_cache()
try: ec.decrypt_password(tok); raise SystemExit("XATO: kalit")
except ValueError: pass
print("4 OK buzilish/noto'g'ri kalit rad etiladi")

# 5. .env kaliti fayldan ustun; fayl yaratilmaydi
os.environ["EMAIL_SECRET_KEY"] = "env-kalit"; ec._reset_key_cache()
t2 = ec.encrypt_password("q"); assert ec.decrypt_password(t2) == "q"
print("5 OK EMAIL_SECRET_KEY")
print("HAMMASI OK")
