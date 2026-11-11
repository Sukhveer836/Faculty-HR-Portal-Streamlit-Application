"""Resource Hub: central links, forms, notices/circulars, units & contacts, timetable, global search."""
import os, re, datetime as dt
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
import db

CENTRAL_UNITS = ["IQAC", "Training & Placement", "Examination Cell",
                 "Academic Administration", "Library", "IT Cell"]
CATEGORIES = ["Academic", "Examination", "Research & IQAC", "Placement", "Library", "HR & Payroll",
              "Student Services", "IT & Systems", "Forms", "Policies", "External"]
NOTICE_CATEGORIES = ["Notice", "Circular", "Event", "Deadline", "Policy Update"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
HUB_DIR = os.path.join(db.UPLOAD_DIR, "_hub")
STALE_DAYS = 90

STOP = set(ENGLISH_STOP_WORDS) - {"it", "id"}
NOISE = {"new", "recent", "any", "whats", "what", "link", "links", "url", "website", "site", "portal", "page", "form", "forms", "open", "access",
         "login", "download", "where", "find", "give", "send", "show", "please", "need", "want", "get",
         "can", "tell", "latest", "contact", "details", "number", "official", "online", "incharge",
         "coordinator", "who", "email", "phone", "address", "location", "circular", "notice", "notices"}


def _today():
    return dt.date.today().isoformat()


def init_hub():
    db.init_db()
    with db.conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS units(
            name TEXT PRIMARY KEY, kind TEXT, head TEXT, email TEXT, phone TEXT,
            location TEXT, description TEXT);
        CREATE TABLE IF NOT EXISTS unit_members(
            unit TEXT, faculty_id TEXT, PRIMARY KEY(unit, faculty_id));
        CREATE TABLE IF NOT EXISTS resources(
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, url TEXT, file_path TEXT,
            category TEXT, unit TEXT, description TEXT, tags TEXT, pinned INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1, added_by TEXT, added_at TEXT, last_verified TEXT,
            flags INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS notices(
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, body TEXT, category TEXT, unit TEXT,
            file_path TEXT, pinned INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
            posted_by TEXT, posted_at TEXT);
        CREATE TABLE IF NOT EXISTS timetable(
            id INTEGER PRIMARY KEY AUTOINCREMENT, faculty_id TEXT, day TEXT, start_time TEXT,
            end_time TEXT, subject TEXT, class_name TEXT, room TEXT);
        """)


def sync_units():
    """Make sure every department and central unit exists as a unit (so people can publish for it)."""
    with db.conn() as c:
        for u in CENTRAL_UNITS:
            c.execute("INSERT OR IGNORE INTO units(name,kind) VALUES (?,?)", (u, "Central unit"))
        for r in c.execute("SELECT DISTINCT department FROM faculty").fetchall():
            c.execute("INSERT OR IGNORE INTO units(name,kind) VALUES (?,?)", (r["department"], "Department / Office"))


# ------------------------------------------------------------------- units
def list_units():
    with db.conn() as c:
        units = [dict(r) for r in c.execute("SELECT * FROM units ORDER BY kind, name")]
        for u in units:
            u["publishers"] = [r["name"] for r in c.execute(
                "SELECT f.name FROM unit_members m JOIN faculty f ON f.faculty_id=m.faculty_id "
                "WHERE m.unit=? ORDER BY f.name", (u["name"],))]
    return units


def unit_names():
    with db.conn() as c:
        return [r["name"] for r in c.execute("SELECT name FROM units ORDER BY kind, name")]


def save_unit(name, kind="Central unit", head="", email="", phone="", location="", description=""):
    if not name.strip():
        raise ValueError("Unit name is required.")
    with db.conn() as c:
        c.execute("INSERT INTO units(name,kind,head,email,phone,location,description) VALUES (?,?,?,?,?,?,?) "
                  "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, head=excluded.head, email=excluded.email, "
                  "phone=excluded.phone, location=excluded.location, description=excluded.description",
                  (name.strip(), kind, head, email, phone, location, description))


def add_publisher(unit, faculty_id):
    with db.conn() as c:
        c.execute("INSERT OR IGNORE INTO unit_members VALUES (?,?)", (unit, faculty_id))


def remove_publisher(unit, faculty_id):
    with db.conn() as c:
        c.execute("DELETE FROM unit_members WHERE unit=? AND faculty_id=?", (unit, faculty_id))


def publishable_units(user):
    """Units this person may publish links/notices for."""
    if user["role"] in ("HR", "Admin"):
        return unit_names()
    with db.conn() as c:
        mine = [r["unit"] for r in c.execute("SELECT unit FROM unit_members WHERE faculty_id=?",
                                             (user["faculty_id"],))]
    if user["role"] == "HOD":
        mine.append(user["department"])
    return sorted(set(mine))


# --------------------------------------------------------------- resources
def _save_file(sub, name, data):
    folder = os.path.join(HUB_DIR, sub)
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r"[^\w.\- ]", "_", os.path.basename(name))
    path = os.path.join(folder, f"{dt.datetime.now():%Y%m%d%H%M%S%f}_{safe}")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def add_resource(title, category, unit, url="", description="", tags="", pinned=False,
                 added_by=None, file=None):
    title, url = (title or "").strip(), (url or "").strip()
    if not title:
        raise ValueError("Title is required.")
    if not url and not file:
        raise ValueError("Give a link (URL) or upload a file.")
    if url and not re.match(r"^https?://", url, re.I):
        raise ValueError("The link must start with http:// or https://")
    if unit not in unit_names():
        raise ValueError(f"Unknown unit '{unit}'. Add it under Admin > Units first.")
    path = _save_file("files", *file) if file else None
    with db.conn() as c:
        cur = c.execute("INSERT INTO resources(title,url,file_path,category,unit,description,tags,pinned,"
                        "added_by,added_at,last_verified) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (title, url or None, path, category, unit, description, tags, int(pinned),
                         added_by, db.now(), _today()))
        return cur.lastrowid


def list_resources(unit=None, category=None, text=None, kind=None, pinned=None, flagged=False):
    q, p = "SELECT r.*, COALESCE(f.name,'') AS owner FROM resources r " \
           "LEFT JOIN faculty f ON f.faculty_id=r.added_by WHERE r.active=1", []
    if unit:
        q += " AND r.unit=?"; p.append(unit)
    if category:
        q += " AND r.category=?"; p.append(category)
    if kind == "link":
        q += " AND r.url IS NOT NULL"
    if kind == "file":
        q += " AND r.file_path IS NOT NULL"
    if pinned:
        q += " AND r.pinned=1"
    if flagged:
        q += " AND r.flags>0"
    if text:
        q += " AND (r.title LIKE ? OR r.description LIKE ? OR r.tags LIKE ?)"; p += [f"%{text}%"] * 3
    q += " ORDER BY r.pinned DESC, r.title"
    with db.conn() as c:
        rows = [dict(r) for r in c.execute(q, p)]
    cutoff = (dt.date.today() - dt.timedelta(days=STALE_DAYS)).isoformat()
    for r in rows:
        r["stale"] = (r["last_verified"] or "") < cutoff
    return rows


def flag_resource(rid):
    with db.conn() as c:
        c.execute("UPDATE resources SET flags=flags+1 WHERE id=?", (rid,))


def verify_resource(rid):
    with db.conn() as c:
        c.execute("UPDATE resources SET flags=0, last_verified=? WHERE id=?", (_today(), rid))


def remove_resource(rid):
    with db.conn() as c:
        c.execute("UPDATE resources SET active=0 WHERE id=?", (rid,))


def import_resources_df(df, user_id):
    """Bulk add links from a CSV. Returns (added, errors)."""
    df = df.rename(columns=lambda x: str(x).strip().lower()).fillna("")
    added, errors = 0, []
    for i, r in df.iterrows():
        try:
            add_resource(str(r.get("title", "")), str(r.get("category", "")) or "Academic",
                         str(r.get("unit", "")), str(r.get("url", "")), str(r.get("description", "")),
                         str(r.get("tags", "")), str(r.get("pinned", "")).strip().lower() in ("1", "yes", "true", "y"),
                         user_id)
            added += 1
        except ValueError as e:
            errors.append(f"Row {i + 2}: {e}")
    return added, errors


# ----------------------------------------------------------------- notices
def add_notice(title, body, category, unit, posted_by, pinned=False, file=None):
    if not (title or "").strip():
        raise ValueError("Title is required.")
    if not (body or "").strip() and not file:
        raise ValueError("Write the notice text or attach a file.")
    if unit not in unit_names():
        raise ValueError("Unknown unit.")
    path = _save_file("notices", *file) if file else None
    with db.conn() as c:
        c.execute("INSERT INTO notices(title,body,category,unit,file_path,pinned,posted_by,posted_at) "
                  "VALUES (?,?,?,?,?,?,?,?)", (title.strip(), body, category, unit, path, int(pinned),
                                               posted_by, db.now()))


def list_notices(unit=None, category=None, text=None, limit=None):
    q = ("SELECT n.*, COALESCE(f.name,'') AS poster FROM notices n "
         "LEFT JOIN faculty f ON f.faculty_id=n.posted_by WHERE n.active=1")
    p = []
    if unit:
        q += " AND n.unit=?"; p.append(unit)
    if category:
        q += " AND n.category=?"; p.append(category)
    if text:
        q += " AND (n.title LIKE ? OR n.body LIKE ?)"; p += [f"%{text}%"] * 2
    q += " ORDER BY n.pinned DESC, n.posted_at DESC"
    if limit:
        q += f" LIMIT {int(limit)}"
    with db.conn() as c:
        rows = [dict(r) for r in c.execute(q, p)]
    week = (dt.datetime.now() - dt.timedelta(days=7)).isoformat()
    for r in rows:
        r["is_new"] = r["posted_at"] >= week
    return rows


def remove_notice(nid):
    with db.conn() as c:
        c.execute("UPDATE notices SET active=0 WHERE id=?", (nid,))


# --------------------------------------------------------------- timetable
def _norm_day(s):
    s = str(s).strip().lower()
    return next((d for d in DAYS if d.lower().startswith(s[:3]) and s), None)


def _norm_time(s):
    s = str(s).strip()
    for f in ("%H:%M", "%I:%M %p", "%H.%M", "%H:%M:%S", "%I:%M%p"):
        try:
            return dt.datetime.strptime(s, f).strftime("%H:%M")
        except ValueError:
            pass
    return None


def import_timetable_df(df):
    """Replaces the whole timetable. Columns: faculty (name or id), day, start, end, subject, class, room."""
    df = df.rename(columns=lambda x: str(x).strip().lower()).fillna("")
    users = db.all_users()
    by_id = {u["faculty_id"].lower(): u["faculty_id"] for u in users}
    by_name = {u["name"].lower(): u["faculty_id"] for u in users}
    rows, errors = [], []
    for i, r in df.iterrows():
        who = str(r.get("faculty", "")).strip().lower()
        fid = by_id.get(who) or by_name.get(who)
        day, st_, en = _norm_day(r.get("day", "")), _norm_time(r.get("start", "")), _norm_time(r.get("end", ""))
        if not fid:
            errors.append(f"Row {i + 2}: faculty '{r.get('faculty')}' not found")
        elif not day:
            errors.append(f"Row {i + 2}: day '{r.get('day')}' not understood")
        elif not st_ or not en or en <= st_:
            errors.append(f"Row {i + 2}: start/end time invalid")
        else:
            rows.append((fid, day, st_, en, str(r.get("subject", "")), str(r.get("class", "")),
                         str(r.get("room", ""))))
    if errors:
        return 0, errors
    with db.conn() as c:
        c.execute("DELETE FROM timetable")
        c.executemany("INSERT INTO timetable(faculty_id,day,start_time,end_time,subject,class_name,room) "
                      "VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows), []


def get_timetable(fid, day=None):
    q, p = "SELECT * FROM timetable WHERE faculty_id=?", [fid]
    if day:
        q += " AND day=?"; p.append(day)
    q += " ORDER BY start_time"
    with db.conn() as c:
        return [dict(r) for r in c.execute(q, p)]


def classes_today(fid, now=None):
    now = now or dt.datetime.now()
    rows = get_timetable(fid, now.strftime("%A"))
    t = now.strftime("%H:%M")
    for r in rows:
        r["status"] = "done" if r["end_time"] <= t else ("now" if r["start_time"] <= t else "upcoming")
    return rows


# ------------------------------------------------------------------ search
def _tokens(q):
    return [t for t in re.findall(r"\w+", q.lower())
            if len(t) > 1 and t not in STOP and t not in NOISE and t.rstrip("s") not in NOISE]


def clean_query(q):
    return " ".join(_tokens(q))


def _rank(items, texts, titles, query, k, min_score=0.12):
    toks = _tokens(query)
    if not items or not toks:
        return []
    sims = [0.0] * len(items)
    try:
        vec = TfidfVectorizer(stop_words=list(STOP), ngram_range=(1, 2), sublinear_tf=True)
        mat = vec.fit_transform(texts)
        sims = (mat @ vec.transform([" ".join(toks)]).T).toarray().ravel().tolist()
    except ValueError:
        pass
    scored = []
    for it, s, title in zip(items, sims, titles):
        title = title.lower()
        boost = sum(0.35 for t in toks if t in title)
        scored.append((s + boost, it))
    scored = [x for x in sorted(scored, key=lambda x: -x[0]) if x[0] >= min_score]
    return [dict(it, score=round(s, 2)) for s, it in scored[:k]]


def search_all(query, k=5):
    """Returns {'links','files','notices','units'}: each a ranked list."""
    res = list_resources()
    links = [r for r in res if r["url"]]
    files = [r for r in res if r["file_path"]]
    rt = lambda r: f"{r['title']} {r['title']} {r['title']} {r['tags']} {r['tags']} {r['description']} {r['unit']} {r['category']}"
    notices = list_notices()
    units = list_units()
    return {
        "links": _rank(links, [rt(r) for r in links], [r["title"] for r in links], query, k),
        "files": _rank(files, [rt(r) for r in files], [r["title"] for r in files], query, k),
        "notices": _rank(notices, [f"{n['title']} {n['title']} {n['body']} {n['unit']} {n['category']}" for n in notices],
                         [n["title"] for n in notices], query, k),
        "units": _rank(units, [f"{u['name']} {u['name']} {u['name']} {u['head'] or ''} {u['description'] or ''} "
                               f"{u['location'] or ''}" for u in units], [u["name"] for u in units], query, k),
    }
