"""Database + workflow engine for the Faculty Portal (SQLite = free, permanent, no server)."""
import sqlite3, json, os, re, hashlib, datetime as dt
from contextlib import contextmanager
import pandas as pd

DB_PATH = os.getenv("PORTAL_DB", "faculty_portal.db")
UPLOAD_DIR = os.getenv("PORTAL_UPLOADS", "uploads")

# Each request type = ordered approval steps, and the ROLE that must act on each step.
WORKFLOWS = {
    "Leave":           {"prefix": "LV", "steps": ["HOD Review", "HR Approval"],
                        "roles": ["HOD", "HR"], "final": "Approved"},
    "Gate Pass":       {"prefix": "GP", "steps": ["HOD Approval", "Security Clearance"],
                        "roles": ["HOD", "Security"], "final": "Pass Issued"},
    "Room Booking":    {"prefix": "RB", "steps": ["Admin Approval"],
                        "roles": ["Admin"], "final": "Confirmed"},
    "Salary Update":   {"prefix": "SU", "steps": ["HR Verification", "Accounts Processing"],
                        "roles": ["HR", "Accounts"], "final": "Completed"},
    "Document Update": {"prefix": "DU", "steps": ["HR Verification", "Admin Record Update"],
                        "roles": ["HR", "Admin"], "final": "Updated"},
}
LEAVE_TYPES = ["CL", "EL", "ML", "Half Day", "OD"]
LEAVE_LABELS = {"CL": "Casual Leave (CL)", "EL": "Earned Leave (EL)", "ML": "Medical Leave (ML)",
                "Half Day": "Half Day (counts 0.5 CL)", "OD": "On Duty (OD) - no deduction"}
ROOMS = {"Seminar Hall": 150, "Conference Room A": 30, "Conference Room B": 20,
         "Board Room": 12, "Computer Lab 1": 60, "Smart Classroom 204": 60}


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def hash_pin(pin):
    return hashlib.sha256(("portal:" + str(pin)).encode()).hexdigest()


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS faculty(
            faculty_id TEXT PRIMARY KEY, name TEXT, department TEXT, designation TEXT,
            email TEXT, phone TEXT, role TEXT, doj TEXT, mentor_id TEXT, pin_hash TEXT);
        CREATE TABLE IF NOT EXISTS leave_balance(
            faculty_id TEXT PRIMARY KEY, CL REAL, EL REAL, ML REAL);
        CREATE TABLE IF NOT EXISTS requests(
            ref_no TEXT PRIMARY KEY, req_type TEXT, faculty_id TEXT, department TEXT,
            summary TEXT, details TEXT, stage_idx INTEGER, stage TEXT, status TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ref_no TEXT, stage TEXT, action TEXT,
            actor_id TEXT, remarks TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS attachments(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ref_no TEXT, filename TEXT, path TEXT,
            uploaded_at TEXT);
        """)


# ------------------------------------------------------------------ users
def add_user(name, department, designation, email, phone, role, doj,
             mentor_id=None, pin="1234", fid=None, cl=12, el=15, ml=10):
    with conn() as c:
        if not fid:
            n = c.execute("SELECT COUNT(*) FROM faculty").fetchone()[0] + 1
            fid = f"EMP{n:03d}"
        c.execute("INSERT INTO faculty VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (fid, name, department, designation, email, phone, role, doj,
                   mentor_id, hash_pin(pin)))
        c.execute("INSERT INTO leave_balance VALUES (?,?,?,?)", (fid, cl, el, ml))
    return fid


def all_users():
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT faculty_id,name,department,designation,email,phone,role,doj,mentor_id "
            "FROM faculty ORDER BY name")]


def get_user(fid):
    with conn() as c:
        r = c.execute("SELECT faculty_id,name,department,designation,email,phone,role,doj,mentor_id "
                      "FROM faculty WHERE faculty_id=?", (fid,)).fetchone()
    return dict(r) if r else None


def users_with_role(role, dept=None):
    with conn() as c:
        q, p = "SELECT name FROM faculty WHERE role=?", [role]
        if dept and role == "HOD":
            q += " AND department=?"; p.append(dept)
        return [r["name"] for r in c.execute(q, p)]


def verify(fid, pin):
    with conn() as c:
        r = c.execute("SELECT 1 FROM faculty WHERE faculty_id=? AND pin_hash=?",
                      (fid, hash_pin(pin))).fetchone()
    return get_user(fid) if r else None


def set_pin(fid, new_pin):
    with conn() as c:
        c.execute("UPDATE faculty SET pin_hash=? WHERE faculty_id=?", (hash_pin(new_pin), fid))


def balance(fid):
    with conn() as c:
        r = c.execute("SELECT CL,EL,ML FROM leave_balance WHERE faculty_id=?", (fid,)).fetchone()
    return dict(r) if r else {"CL": 0, "EL": 0, "ML": 0}


# --------------------------------------------------------------- validation
def leave_days(ltype, d_from, d_to):
    return 0.5 if ltype == "Half Day" else float((d_to - d_from).days + 1)


def room_conflicts(c, room, date, start, end):
    out = []
    for r in c.execute("SELECT ref_no,details FROM requests WHERE req_type='Room Booking' "
                       "AND status!='Rejected'"):
        d = json.loads(r["details"])
        if d["room"] == room and d["date"] == date and start < d["end"] and d["start"] < end:
            out.append((r["ref_no"], d["start"], d["end"]))
    return out


def _validate(c, rtype, fid, d, files):
    if rtype == "Leave":
        f, t = dt.date.fromisoformat(d["from"]), dt.date.fromisoformat(d["to"])
        if t < f:
            raise ValueError("'To' date cannot be before 'From' date.")
        if d["leave_type"] == "Half Day" and f != t:
            raise ValueError("Half Day leave must be for a single date.")
        if not d.get("reason", "").strip():
            raise ValueError("Please give a reason.")
        days = leave_days(d["leave_type"], f, t)
        d["days"] = days
        key = "CL" if d["leave_type"] == "Half Day" else d["leave_type"]
        if key in ("CL", "EL", "ML"):
            bal = c.execute("SELECT * FROM leave_balance WHERE faculty_id=?", (fid,)).fetchone()
            if bal[key] < days:
                raise ValueError(f"Not enough {key} balance. You have {bal[key]:g}, requested {days:g}.")
        for r in c.execute("SELECT ref_no,details FROM requests WHERE faculty_id=? "
                           "AND req_type='Leave' AND status!='Rejected'", (fid,)):
            x = json.loads(r["details"])
            if f <= dt.date.fromisoformat(x["to"]) and dt.date.fromisoformat(x["from"]) <= t:
                raise ValueError(f"These dates overlap with your earlier request {r['ref_no']}.")
    elif rtype == "Room Booking":
        if d["end"] <= d["start"]:
            raise ValueError("End time must be after start time.")
        if d["start"] < "08:00" or d["end"] > "20:00":
            raise ValueError("Rooms can be booked between 08:00 and 20:00 only.")
        if d["attendees"] > ROOMS[d["room"]]:
            raise ValueError(f"{d['room']} seats only {ROOMS[d['room']]} people.")
        clash = room_conflicts(c, d["room"], d["date"], d["start"], d["end"])
        if clash:
            raise ValueError(f"{d['room']} is already booked {clash[0][1]}-{clash[0][2]} "
                             f"(request {clash[0][0]}). Pick another slot or room.")
    elif rtype == "Gate Pass":
        if d["return_time"] <= d["out_time"]:
            raise ValueError("Return time must be after out time.")
        if not d.get("reason", "").strip():
            raise ValueError("Please give a reason.")
    elif rtype == "Salary Update":
        if not d.get("description", "").strip():
            raise ValueError("Please describe what needs to be updated.")
    elif rtype == "Document Update":
        if not files:
            raise ValueError("Please attach at least one supporting document.")
        if not d.get("description", "").strip():
            raise ValueError("Please add a short description.")


def summarize(rtype, d):
    if rtype == "Leave":
        return f"{d['leave_type']} {d['from']} to {d['to']} ({d['days']:g} day{'s' if d['days'] > 1 else ''})"
    if rtype == "Gate Pass":
        return f"{d['purpose']} pass on {d['date']} {d['out_time']}-{d['return_time']}"
    if rtype == "Room Booking":
        return f"{d['room']} on {d['date']} {d['start']}-{d['end']} ({d['purpose']})"
    if rtype == "Salary Update":
        return f"{d['category']}"
    return f"{d['category']}"


def _note(d):
    return d.get("reason") or d.get("purpose") or d.get("description") or ""


# ------------------------------------------------------------ workflow core
def _next_ref(c, prefix, ts):
    n = c.execute("SELECT COUNT(*) FROM requests WHERE ref_no LIKE ?",
                  (f"{prefix}-{ts[:4]}-%",)).fetchone()[0] + 1
    return f"{prefix}-{ts[:4]}-{n:04d}"


def _log(c, ref, stage, action, actor, remarks, ts):
    c.execute("INSERT INTO history(ref_no,stage,action,actor_id,remarks,ts) VALUES (?,?,?,?,?,?)",
              (ref, stage, action, actor, remarks, ts))


def _finalize(c, r):
    """Side-effects when a request is fully approved (e.g. deduct leave balance)."""
    if r["req_type"] == "Leave":
        d = json.loads(r["details"])
        key = "CL" if d["leave_type"] == "Half Day" else d["leave_type"]
        if key in ("CL", "EL", "ML"):
            c.execute(f"UPDATE leave_balance SET {key}=MAX(0,{key}-?) WHERE faculty_id=?",
                      (d["days"], r["faculty_id"]))


def _set_progress(c, r, idx, ts):
    wf = WORKFLOWS[r["req_type"]]
    if idx >= len(wf["steps"]):
        c.execute("UPDATE requests SET stage_idx=?,stage=?,status='Completed',updated_at=? "
                  "WHERE ref_no=?", (idx, wf["final"], ts, r["ref_no"]))
        _finalize(c, r)
    else:
        c.execute("UPDATE requests SET stage_idx=?,stage=?,status='In Progress',updated_at=? "
                  "WHERE ref_no=?", (idx, wf["steps"][idx], ts, r["ref_no"]))


def _auto_skip(c, ref, ts):
    """If the requester is himself the HOD, the 'HOD' step is skipped automatically."""
    while True:
        r = c.execute("SELECT r.*, f.role AS frole FROM requests r "
                      "JOIN faculty f ON f.faculty_id=r.faculty_id WHERE r.ref_no=?", (ref,)).fetchone()
        wf = WORKFLOWS[r["req_type"]]
        if r["status"] != "In Progress" or wf["roles"][r["stage_idx"]] != "HOD" or r["frole"] != "HOD":
            return
        _log(c, ref, r["stage"], "Auto-skipped", "SYSTEM", "Requester is the HOD", ts)
        _set_progress(c, r, r["stage_idx"] + 1, ts)


def create_request(fid, rtype, details, files=None, ts=None):
    ts = ts or now()
    files = files or []
    with conn() as c:
        u = c.execute("SELECT * FROM faculty WHERE faculty_id=?", (fid,)).fetchone()
        _validate(c, rtype, fid, details, files)
        wf = WORKFLOWS[rtype]
        ref = _next_ref(c, wf["prefix"], ts)
        c.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (ref, rtype, fid, u["department"], summarize(rtype, details),
                   json.dumps(details), 0, wf["steps"][0], "In Progress", ts, ts))
        _log(c, ref, "Submitted", "Submitted", fid, _note(details), ts)
        _auto_skip(c, ref, ts)
    for name, data in files:
        save_attachment(ref, name, data, ts)
    return ref


def act(ref, actor_id, decision, remarks="", ts=None):
    """decision: 'Approve' or 'Reject'. Enforces who is allowed to act on the current stage."""
    ts = ts or now()
    with conn() as c:
        r = c.execute("SELECT * FROM requests WHERE ref_no=?", (ref,)).fetchone()
        if not r:
            raise ValueError("Request not found.")
        if r["status"] != "In Progress":
            raise ValueError("This request is already closed.")
        a = c.execute("SELECT * FROM faculty WHERE faculty_id=?", (actor_id,)).fetchone()
        need = WORKFLOWS[r["req_type"]]["roles"][r["stage_idx"]]
        if a["role"] != need or (need == "HOD" and a["department"] != r["department"]):
            raise ValueError("You are not the approver for this stage.")
        if actor_id == r["faculty_id"]:
            raise ValueError("You cannot approve your own request.")
        if decision == "Reject":
            if not remarks.strip():
                raise ValueError("Please give a reason for rejection.")
            c.execute("UPDATE requests SET status='Rejected',updated_at=? WHERE ref_no=?", (ts, ref))
            _log(c, ref, r["stage"], "Rejected", actor_id, remarks, ts)
        else:
            _log(c, ref, r["stage"], "Approved", actor_id, remarks, ts)
            _set_progress(c, r, r["stage_idx"] + 1, ts)
            _auto_skip(c, ref, ts)


# ------------------------------------------------------------------ queries
def get_request(ref):
    with conn() as c:
        r = c.execute("SELECT r.*, f.name AS requester, f.role AS requester_role "
                      "FROM requests r JOIN faculty f ON f.faculty_id=r.faculty_id "
                      "WHERE r.ref_no=?", (ref,)).fetchone()
        if not r:
            return None
        out = dict(r)
        out["details"] = json.loads(r["details"])
        out["history"] = [dict(h) for h in c.execute(
            "SELECT h.*, COALESCE(f.name,'System') AS actor_name FROM history h "
            "LEFT JOIN faculty f ON f.faculty_id=h.actor_id WHERE h.ref_no=? ORDER BY h.id", (ref,))]
        out["attachments"] = [dict(a) for a in c.execute(
            "SELECT * FROM attachments WHERE ref_no=?", (ref,))]
    return out


def pending_for(u):
    with conn() as c:
        rows = c.execute("SELECT r.*, f.name AS requester FROM requests r "
                         "JOIN faculty f ON f.faculty_id=r.faculty_id "
                         "WHERE r.status='In Progress' AND r.faculty_id!=? ORDER BY r.created_at",
                         (u["faculty_id"],)).fetchall()
    out = []
    for r in rows:
        need = WORKFLOWS[r["req_type"]]["roles"][r["stage_idx"]]
        if need == u["role"] and (need != "HOD" or r["department"] == u["department"]):
            out.append(dict(r))
    return out


def query_requests(fid=None, dept=None, types=None, statuses=None, text=None, d_from=None, d_to=None):
    q = ("SELECT r.ref_no, r.req_type AS type, f.name AS requester, r.department, r.summary, "
         "r.stage, r.status, r.created_at, r.updated_at FROM requests r "
         "JOIN faculty f ON f.faculty_id=r.faculty_id WHERE 1=1")
    p = []
    if fid:
        q += " AND r.faculty_id=?"; p.append(fid)
    if dept:
        q += " AND r.department=?"; p.append(dept)
    if types:
        q += f" AND r.req_type IN ({','.join('?' * len(types))})"; p += list(types)
    if statuses:
        q += f" AND r.status IN ({','.join('?' * len(statuses))})"; p += list(statuses)
    if text:
        q += " AND (r.ref_no LIKE ? OR r.summary LIKE ? OR f.name LIKE ?)"; p += [f"%{text}%"] * 3
    if d_from:
        q += " AND substr(r.created_at,1,10)>=?"; p.append(str(d_from))
    if d_to:
        q += " AND substr(r.created_at,1,10)<=?"; p.append(str(d_to))
    q += " ORDER BY r.created_at DESC"
    with conn() as c:
        return pd.read_sql_query(q, c, params=p)


def room_bookings(room, date):
    out = []
    with conn() as c:
        for r in c.execute("SELECT r.ref_no,r.details,r.status,f.name FROM requests r "
                           "JOIN faculty f ON f.faculty_id=r.faculty_id "
                           "WHERE r.req_type='Room Booking' AND r.status!='Rejected'"):
            d = json.loads(r["details"])
            if d["room"] == room and d["date"] == date:
                out.append({"ref": r["ref_no"], "start": d["start"], "end": d["end"],
                            "by": r["name"], "status": r["status"]})
    return sorted(out, key=lambda x: x["start"])


def audit_trail():
    with conn() as c:
        return pd.read_sql_query(
            "SELECT h.ref_no, r.req_type AS type, h.stage, h.action, "
            "COALESCE(f.name,'System') AS by_whom, h.remarks, h.ts "
            "FROM history h JOIN requests r ON r.ref_no=h.ref_no "
            "LEFT JOIN faculty f ON f.faculty_id=h.actor_id ORDER BY h.ts", c)


def save_attachment(ref, filename, data, ts=None):
    safe = re.sub(r"[^\w.\- ]", "_", os.path.basename(filename))
    folder = os.path.join(UPLOAD_DIR, ref)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, safe)
    with open(path, "wb") as fh:
        fh.write(data)
    with conn() as c:
        c.execute("INSERT INTO attachments(ref_no,filename,path,uploaded_at) VALUES (?,?,?,?)",
                  (ref, safe, path, ts or now()))
