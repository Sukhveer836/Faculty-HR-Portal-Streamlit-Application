"""Faculty Portal: HR chatbot + online requests + approval tracking + permanent records.
Run:  streamlit run app.py      (first run auto-creates a sample dataset)"""
import os, re, glob, datetime as dt
import pandas as pd
import requests
import streamlit as st
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics.pairwise import cosine_similarity

import db, hub, seed

st.set_page_config(page_title="Faculty Portal", page_icon="🎓", layout="wide")

DOCS_DIR = "docs"
APPROVER_ROLES = {"HOD", "HR", "Admin", "Accounts", "Security"}
MGMT_ROLES = {"HR", "Admin"}
REF_RE = re.compile(r"\b([A-Za-z]{2}-\d{4}-\d{4})\b")

if not os.path.exists(db.DB_PATH):
    seed.run()                               # first launch: build sample dataset
db.init_db()
hub.init_hub()
hub.sync_units()
os.makedirs(DOCS_DIR, exist_ok=True)


# ----------------------------------------------------------------- helpers
def secret(name, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)


def flash(msg, kind="success"):
    st.session_state["_flash"] = (kind, msg)


def show_flash():
    f = st.session_state.pop("_flash", None)
    if f:
        getattr(st, f[0])(f[1])


def goto(page, rtype=None, ref=None):
    st.session_state.nav = page
    if rtype:
        st.session_state.new_type = rtype
    if ref:
        st.session_state.track_ref = ref


def can_view(user, r):
    if r["faculty_id"] == user["faculty_id"] or user["role"] in MGMT_ROLES:
        return True
    if user["role"] == "HOD" and user["department"] == r["department"]:
        return True
    return user["role"] in db.WORKFLOWS[r["req_type"]]["roles"] and user["role"] != "HOD"


def pretty(k):
    return k.replace("_", " ").title()


def render_tracker(r):
    wf = db.WORKFLOWS[r["req_type"]]
    labels = ["Submitted"] + wf["steps"] + [wf["final"]]
    done = r["stage_idx"] + 1
    cols = st.columns(len(labels))
    for i, lab in enumerate(labels):
        if r["status"] == "Completed" or i < done:
            icon = "✅"
        elif i == done and r["status"] == "In Progress":
            icon = "⏳"
        elif i == done and r["status"] == "Rejected":
            icon = "❌"
        else:
            icon = "⬜"
        cols[i].markdown(f"### {icon}\n**{lab}**")
    st.progress(1.0 if r["status"] == "Completed" else min(1.0, done / (len(labels) - 1)))
    if r["status"] == "In Progress":
        role = wf["roles"][r["stage_idx"]]
        who = ", ".join(db.users_with_role(role, r["department"]))
        st.info(f"⏳ Waiting for **{r['stage']}** — {role}: {who}")
    elif r["status"] == "Rejected":
        st.error("❌ This request was rejected. See remarks in the history below.")
    else:
        st.success(f"✅ Completed: {r['stage']}")


def render_request_body(r, key):
    st.markdown(f"**{r['req_type']}** • requested by **{r['requester']}** ({r['department']}) • "
                f"submitted {r['created_at'].replace('T', ' ')}")
    det = pd.DataFrame({"Field": [pretty(k) for k in r["details"]],
                        "Value": [str(v) for v in r["details"].values()]})
    st.dataframe(det, hide_index=True)
    for a in r["attachments"]:
        if os.path.exists(a["path"]):
            with open(a["path"], "rb") as fh:
                st.download_button(f"📎 {a['filename']}", fh.read(), file_name=a["filename"],
                                   key=f"dl_{key}_{a['id']}")


def render_history(r):
    h = pd.DataFrame(r["history"])
    if len(h):
        h = h[["ts", "stage", "action", "actor_name", "remarks"]]
        h.columns = ["Time", "Stage", "Action", "By", "Remarks"]
        h["Time"] = h["Time"].str.replace("T", " ")
        st.dataframe(h, hide_index=True)


# ------------------------------------------------------------ document search
def read_file(path):
    if path.lower().endswith(".pdf"):
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    return open(path, encoding="utf-8", errors="ignore").read()


def chunk(text, size=1100, overlap=150):
    """Split by markdown sections (keeps each rule together); long sections are split further."""
    parts = re.split(r"\n(?=#{1,3} )", text)
    title = parts[0].strip().splitlines()[0].lstrip("# ") if parts and parts[0].strip() else ""
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if title and not p.startswith("# "):
            p = f"[{title}]\n{p}"
        out += [p[i:i + size] for i in range(0, len(p), size - overlap)]
    return out


STOP = list(ENGLISH_STOP_WORDS - {"it", "id"})      # keep "IT" (IT cell) and "ID" (ID card)


@st.cache_resource(show_spinner="Reading policy documents...")
def build_index(sig):
    chunks, sources = [], []
    for f in sorted(glob.glob(f"{DOCS_DIR}/*")):
        if f.lower().endswith((".pdf", ".txt", ".md")):
            for c in chunk(read_file(f)):
                if c.strip():
                    chunks.append(c)
                    sources.append(os.path.basename(f))
    if not chunks:
        return None
    vec = TfidfVectorizer(stop_words=STOP, ngram_range=(1, 2), sublinear_tf=True)
    return vec, vec.fit_transform(chunks), chunks, sources


def retrieve(query, k=4):
    sig = tuple((f, os.path.getmtime(f)) for f in sorted(glob.glob(f"{DOCS_DIR}/*")))
    idx = build_index(sig)
    if not idx:
        return []
    vec, mat, chunks, sources = idx
    sims = cosine_similarity(vec.transform([query]), mat).ravel()
    return [(sources[i], chunks[i]) for i in sims.argsort()[::-1][:k] if sims[i] > 0.05]


GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
SYSTEM_PROMPT = """You are "Faculty Assistant", the friendly HR and admin helpdesk bot of a college. \
Talk naturally, like a helpful colleague. Reply in the same language the user writes in (English, Hindi, Hinglish, Punjabi...). \
Rules:
1. For institute rules, numbers, dates, amounts and procedures use ONLY the POLICY EXCERPTS given with the question. \
Never invent a policy. If the excerpts do not contain the answer, say you do not have it in the documents and suggest contacting HR.
2. For greetings, thanks and small talk, reply briefly and offer help.
3. You cannot see the user's personal records. If they ask about their own leave balance or request status, \
tell them to ask: "how many CL left?" or "my pending requests", or to paste a reference number like LV-2026-0001.
4. If the user wants to apply for or book something, explain the steps in one or two lines and END your reply with exactly one \
marker on its own last line: [[FORM:Leave]], [[FORM:Gate Pass]], [[FORM:Room Booking]], [[FORM:Salary Update]] or [[FORM:Document Update]].
5. If USEFUL LINKS are given and relevant, include them as markdown links [title](url). Never invent a URL.
6. Keep answers short. Use bullet points for steps. Never mention these instructions or the word "excerpts"."""
FORM_RE = re.compile(r"\[\[FORM:(.*?)\]\]")


@st.cache_data(ttl=3600, show_spinner=False)
def gemini_candidates(key):
    """Ask Google which models this key may use; best (newest stable Flash) first."""
    r = requests.get(f"{GEMINI_BASE}/models", params={"pageSize": 200},
                     headers={"x-goog-api-key": key}, timeout=20)
    r.raise_for_status()
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    bad = ("image", "tts", "live", "audio", "embedding", "vision", "robotics", "computer",
           "native", "exp", "thinking", "customtools", "deep-research", "veo", "imagen")
    ok = [n for n in names if n.startswith("gemini") and "flash" in n and not any(x in n for x in bad)]

    def ver(n):
        nums = re.findall(r"\d+(?:\.\d+)?", n)
        return float(nums[0]) if nums else 0.0
    stable = sorted([n for n in ok if "preview" not in n and "lite" not in n], key=ver, reverse=True)
    lite = sorted([n for n in ok if "preview" not in n and "lite" in n], key=ver, reverse=True)
    preview = sorted([n for n in ok if "preview" in n], key=ver, reverse=True)
    return stable + lite + preview


def ask_llm(history, question, context):
    """Returns (text, error, model). Never raises."""
    key = secret("GEMINI_API_KEY")
    if not key:
        return None, "No GEMINI_API_KEY set", None
    configured = secret("GEMINI_MODEL")
    try:
        models = [configured] if configured and configured != "auto" else gemini_candidates(key)[:3]
    except Exception as e:
        return None, f"Could not list Gemini models: {str(e)[:160]}", None
    if not models:
        return None, "This key has no usable Gemini Flash model", None
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
                for m in history[-8:]]
    contents.append({"role": "user", "parts": [{"text":
                     f"POLICY EXCERPTS:\n{context or '(none found)'}\n\nQUESTION: {question}"}]})
    body = {"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]}, "contents": contents,
            "generationConfig": {"temperature": 0.3}}
    err = None
    for model in models:
        try:
            r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent", json=body,
                              headers={"x-goog-api-key": key}, timeout=45)
            if r.status_code != 200:
                err = f"{model}: HTTP {r.status_code} {r.text[:160]}"
                continue
            parts = r.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
            if text:
                return text, None, model
            err = f"{model}: empty answer"
        except Exception as e:
            err = f"{model}: {str(e)[:160]}"
    return None, err, None


INTENTS = [
    ("Leave", ["apply leave", "apply for leave", "take leave", "need leave", "want leave",
               "leave application", "half day", "apply cl", "apply el", "apply for cl"]),
    ("Room Booking", ["book room", "book a room", "conference room", "seminar hall", "book hall", "book the hall"]),
    ("Gate Pass", ["gate pass", "gatepass", "leave campus", "go out of campus"]),
    ("Salary Update", ["change bank", "bank account change", "salary update", "update salary", "update my bank"]),
    ("Document Update", ["update document", "upload degree", "update certificate", "document update",
                         "update my degree", "service book entry"]),
]


LOOKUP_WORDS = ["link", "url", "website", "portal", "form", "download", "circular", "notice", "where",
                "contact", "incharge", "in-charge", "coordinator", "who is", "email", "phone", "extension",
                "address", "open", "login", "helpdesk", "location"]


def hub_reply(q):
    """Answer from links / forms / notices / unit contacts, or None."""
    cq = hub.clean_query(q)
    if not cq:
        return None
    low = q.lower()
    res = hub.search_all(cq, 3)
    contact = any(w in low for w in ["incharge", "in-charge", "coordinator", "who is", "contact", "email",
                                     "phone", "extension", "where is", "location", "address"])
    unit_lines = []
    for u in res["units"][:1]:
        bits = [x for x in (f"in-charge **{u['head']}**" if u["head"] else "", u["email"], u["phone"], u["location"]) if x]
        if bits:
            unit_lines.append(f"- 🏛 **{u['name']}**: " + " • ".join(bits))
    if contact and unit_lines:
        extra = [f"- 🔗 [{r['title']}]({r['url']})" for r in res["links"][:3] if r["score"] >= 0.5][:1]
        return "\n".join(unit_lines + ([""] + ["Related link:"] + extra if extra else []))
    lines = []
    for r in res["links"][:3]:
        lines.append(f"- 🔗 **[{r['title']}]({r['url']})**: {r['description']} *({r['unit']})*")
    for r in res["files"][:2]:
        lines.append(f"- 📎 **{r['title']}**: download it in **Resource Hub → Forms & Documents** *({r['unit']})*")
    for n in res["notices"][:2]:
        body = n["body"][:150] + ("…" if len(n["body"]) > 150 else "")
        lines.append(f"- 📢 **{n['title']}** *({n['unit']}, {n['posted_at'][:10]})*: {body}")
    lines += unit_lines
    return ("Here is what I found:\n\n" + "\n".join(lines)) if lines else None


def docs_exist():
    return any(f.lower().endswith((".pdf", ".txt", ".md")) for f in glob.glob(f"{DOCS_DIR}/*"))


def bot_reply(q, user, history=None):
    """Returns (text, form_to_open). Personal data answers are computed locally and never sent to the AI."""
    history = history or []
    low = q.lower()
    m = REF_RE.search(q)
    if m:
        r = db.get_request(m.group(1).upper())
        if not r or not can_view(user, r):
            return "I couldn't find that reference number (or you don't have access to it).", None
        last = r["history"][-1]
        return (f"**{r['ref_no']}** — {r['req_type']}: {r['summary']}\n\n"
                f"- Status: **{r['status']}**  |  Stage: **{r['stage']}**\n"
                f"- Last update: {last['ts'].replace('T', ' ')} — {last['action']} by {last['actor_name']}"), None
    for rtype, words in INTENTS:
        if any(w in low for w in words):
            return f"Sure — you can raise a **{rtype}** request online. Use the button below.", rtype
    if any(w in low for w in ["balance", "left", "remaining", "how many cl", "how many el"]) and \
            any(w in low for w in ["cl", "el", "ml", "leave"]):
        b = db.balance(user["faculty_id"])
        return f"Your leave balance: **CL {b['CL']:g}**, **EL {b['EL']:g}**, **ML {b['ML']:g}**.", None
    if any(w in low for w in ["my request", "my pending", "pending request", "status of my", "my application"]):
        df = db.query_requests(fid=user["faculty_id"]).head(5)
        if df.empty:
            return "You have no requests yet.", None
        lines = [f"- **{r.ref_no}** {r.type}: {r.summary} — *{r.status} ({r.stage})*" for r in df.itertuples()]
        return "Your latest requests:\n\n" + "\n".join(lines), None
    if "mentor" in low:
        mt = db.get_user(user["mentor_id"]) if user.get("mentor_id") else None
        return (f"Your mentor is **{mt['name']}** ({mt['department']})." if mt
                else "No mentor is assigned to you in the records."), None

    if any(w in low for w in ["timetable", "next class", "my classes", "classes today", "class today", "free period"]):
        rows = hub.classes_today(user["faculty_id"])
        if not rows:
            return "You have no classes today (or your timetable is not loaded yet; see **📅 Timetable**).", None
        icon = {"done": "✅", "now": "▶️", "upcoming": "⏭"}
        return "Your classes today:\n\n" + "\n".join(
            f"- {icon[r['status']]} **{r['start_time']}-{r['end_time']}** {r['subject']} • {r['class_name']} • {r['room']}"
            for r in rows), None
    if any(w in low for w in ["notice", "circular", "announcement", "what's new", "whats new"]) \
            and not hub.clean_query(q):
        ns = hub.list_notices(limit=5)
        if ns:
            return "Latest notices:\n\n" + "\n".join(
                f"- {'📌 ' if n['pinned'] else ''}**{n['title']}** *({n['unit']}, {n['posted_at'][:10]})*" for n in ns) + \
                "\n\nOpen **🔗 Resource Hub → Notices** for the full text.", None
    if any(w in low for w in LOOKUP_WORDS):
        found = hub_reply(q)
        if found:
            return found, None

    # ---- retrieval over policy documents (use the previous question too, for follow-ups)
    prev = [h["content"] for h in history if h["role"] == "user"][-1:]
    hits = retrieve(" ".join(prev + [q]), k=5) if docs_exist() else []
    srcs = ", ".join(sorted({h[0] for h in hits}))

    # ---- ChatGPT-style answer (needs a Gemini key)
    ai_note = ""
    if secret("GEMINI_API_KEY"):
        ctx = "\n---\n".join(f"[{src}] {txt}" for src, txt in hits)
        cq = hub.clean_query(q)
        if cq:
            ls = hub.search_all(cq, 4)["links"][:4]
            if ls:
                ctx += "\n\nUSEFUL LINKS:\n" + "\n".join(f"- {r['title']} | {r['url']} | {r['description']}" for r in ls)
        text, err, model = ask_llm(history, q, ctx)
        if text:
            st.session_state["ai_model"], st.session_state["ai_error"] = model, None
            action = None
            mk = FORM_RE.search(text)
            if mk:
                action = mk.group(1).strip() if mk.group(1).strip() in db.WORKFLOWS else None
                text = FORM_RE.sub("", text).strip()
            return text + (f"\n\n*Sources: {srcs}*" if hits else ""), action
        st.session_state["ai_error"] = err
        ai_note = "\n\n*(The AI service is not reachable right now, so I am showing matches from the documents.)*"

    # ---- plain mode (no key, or AI failed)
    if re.fullmatch(r"\s*(hi+|hello+|hey+|hii+|namaste|good (morning|afternoon|evening)|help|menu|\?)\W*", low):
        return (f"Hello {user['name'].split()[-1]}! 👋 I can help you with:\n\n"
                "- **Policies and rules:** notice period, dress code, conference funding, service book\n"
                "- **Salary and benefits:** salary date, payslip, NPS, medical claim\n"
                "- **Daily work:** LMS attendance, marks upload, timetable, hostel duty\n"
                "- **New faculty:** IT cell, ID card, mentor\n"
                "- **Your account:** 'how many CL left?', 'my pending requests', or paste a reference like LV-2026-0001\n"
                "- **Requests:** say 'apply leave', 'book conference room', 'gate pass', 'update bank account', "
                "'update document' and I will open the form"), None
    if re.fullmatch(r"\s*(thanks?|thank you|thx|ok(ay)?|great|good)\W*", low):
        return "You're welcome! Ask me anything else.", None
    if not docs_exist():
        return ("No policy documents are loaded yet, so I can't answer policy questions. "
                "Ask HR/Admin to upload them under **Admin → Policy documents**."), None
    if not hits:
        return ("I couldn't find that in the policy documents. Try again with key words "
                "(e.g. *notice period*, *payslip*, *conference funding*), or contact HR." + ai_note), None
    ans = "**Closest matches in the policy documents:**\n\n" + "\n\n".join(
        "> " + h[1][:500].strip().replace("\n", "\n> ") + "..." for h in hits[:3])
    return f"{ans}\n\n*Sources: {srcs}*{ai_note}", None


# -------------------------------------------------------------------- login
def login_screen():
    st.title("🎓 Faculty Portal")
    st.caption("HR Assistant • Online Requests • Approval Tracking • Permanent Records")
    users = db.all_users()
    labels = {f"{u['name']} — {u['designation']} ({u['faculty_id']})": u for u in users}
    with st.form("login"):
        who = st.selectbox("Who are you?", list(labels))
        pin = st.text_input("PIN", type="password")
        ok = st.form_submit_button("Sign in")
    if ok:
        u = db.verify(labels[who]["faculty_id"], pin)
        if u:
            st.session_state.user = u
            for k in ("nav", "chat", "track_ref"):
                st.session_state.pop(k, None)
            st.rerun()
        else:
            st.error("Wrong PIN.")
    st.info("Demo build: every sample user has PIN **1234**. "
            "Try different roles: a Faculty, an HOD, HR, Admin, Accounts, Security.")


# -------------------------------------------------------------------- pages
def page_bot(user):
    st.header("💬 Ask the Bot")
    if secret("GEMINI_API_KEY"):
        st.caption("🟢 AI mode ON: ask in your own words (English / Hindi / Hinglish). "
                   "Say 'apply leave' or 'book conference room' to open a form.")
    else:
        st.caption("⚪ AI mode OFF: showing matches from policy documents. "
                   "Ask HR/IT to add a Gemini key to get ChatGPT-style answers.")
    chat = st.session_state.setdefault("chat", [])
    for i, m in enumerate(chat):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("action"):
                st.button(f"Open {m['action']} form ➜", key=f"act_{i}", on_click=goto,
                          args=("➕ New Request", m["action"]))
    if chat and st.button("🗑 Clear chat"):
        st.session_state["chat"] = []
        st.rerun()
    q = st.chat_input("Type your question…")
    if q:
        with st.spinner("Thinking…"):
            text, action = bot_reply(q, user, list(chat))
        chat.append({"role": "user", "content": q})
        chat.append({"role": "assistant", "content": text, "action": action})
        st.rerun()


# ------------------------------------------------------------- hub helpers
def clean_filename(path):
    return re.sub(r"^\d{20}_", "", os.path.basename(path))


def file_button(path, key, label="Download"):
    if path and os.path.exists(path):
        with open(path, "rb") as fh:
            st.download_button(f"📎 {label}", fh.read(), file_name=clean_filename(path), key=key)
    else:
        st.caption("(file missing)")


LINKS_TEMPLATE = ("title,url,category,unit,description,tags,pinned\n"
                  "ERP Portal,https://erp.yourcollege.edu/login,IT & Systems,IT Cell,Payroll and academics,erp payslip login,yes\n")
TT_TEMPLATE = ("faculty,day,start,end,subject,class,room\n"
               "Dr. Example Name,Monday,09:00,10:00,Data Structures,BCA-1,Room 101\n")


def resource_card(r, user, pub_units, prefix="r"):
    with st.container(border=True):
        c1, c2 = st.columns([5, 2])
        badges = (f"  ⚠️ reported broken x{r['flags']}" if r["flags"] else "") + \
                 ("  🕒 needs verification" if r["stale"] else "")
        c1.markdown(f"**{r['title']}**{badges}")
        c1.caption(f"{r['description'] or ''}  \n{r['unit']} • {r['category']} • last verified {r['last_verified']}")
        with c2:
            if r["url"]:
                st.link_button("Open ↗", r["url"])
            else:
                file_button(r["file_path"], f"{prefix}_dl_{r['id']}")
            if st.button("⚠ Report broken/outdated", key=f"{prefix}_fl_{r['id']}"):
                hub.flag_resource(r["id"])
                flash("Thanks, the owner of this link has been flagged to check it.")
                st.rerun()
            if r["unit"] in pub_units:
                b1, b2 = st.columns(2)
                if b1.button("✔ Verified", key=f"{prefix}_vf_{r['id']}"):
                    hub.verify_resource(r["id"]); st.rerun()
                if b2.button("🗑", key=f"{prefix}_rm_{r['id']}", help="Remove"):
                    hub.remove_resource(r["id"]); st.rerun()


def resource_form(user, pub_units, default_kind, key):
    with st.expander("➕ Add a link or upload a file (for your unit)"):
        with st.form(key, clear_on_submit=True):
            title = st.text_input("Title")
            kind = st.radio("Type", ["Link", "File"], horizontal=True, index=0 if default_kind == "Link" else 1)
            url = st.text_input("URL (if Link)", placeholder="https://")
            up = st.file_uploader("File (if File: PDF, Word, Excel…)")
            c = st.columns(3)
            unit = c[0].selectbox("Unit", pub_units)
            cat = c[1].selectbox("Category", hub.CATEGORIES)
            pin = c[2].checkbox("Show on everyone's dashboard")
            desc = st.text_input("Short description")
            tags = st.text_input("Search keywords (space separated)")
            if st.form_submit_button("Add"):
                try:
                    hub.add_resource(title, cat, unit, url if kind == "Link" else "", desc, tags, pin,
                                     user["faculty_id"], file=(up.name, up.getvalue()) if kind == "File" and up else None)
                    flash("Added. Everyone can now find it, including through the chatbot.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def page_hub(user):
    st.header("🔗 Resource Hub")
    st.caption("One place for links, forms, notices and unit contacts. Found a broken or outdated link? Report it.")
    show_flash()
    pub_units = hub.publishable_units(user)
    units = hub.unit_names()
    t1, t2, t3, t4 = st.tabs(["🔗 Links", "📢 Notices & Circulars", "📄 Forms & Documents", "🏛 Units & Contacts"])
    with t1:
        c = st.columns(3)
        unit = c[0].selectbox("Unit", ["All"] + units, key="hl_unit")
        cat = c[1].selectbox("Category", ["All"] + hub.CATEGORIES, key="hl_cat")
        text = c[2].text_input("Filter by words", key="hl_txt")
        flagged = st.checkbox("Show only links reported broken", key="hl_flag") if pub_units else False
        rows = hub.list_resources(None if unit == "All" else unit, None if cat == "All" else cat,
                                  text or None, kind="link", flagged=flagged)
        st.caption(f"{len(rows)} link(s)")
        for r in rows:
            resource_card(r, user, pub_units, "l")
        if pub_units:
            resource_form(user, pub_units, "Link", "add_link")
    with t2:
        c = st.columns(3)
        unit = c[0].selectbox("Unit", ["All"] + units, key="hn_unit")
        cat = c[1].selectbox("Type", ["All"] + hub.NOTICE_CATEGORIES, key="hn_cat")
        text = c[2].text_input("Filter by words", key="hn_txt")
        for n in hub.list_notices(None if unit == "All" else unit, None if cat == "All" else cat, text or None):
            with st.container(border=True):
                st.markdown(f"{'📌 ' if n['pinned'] else ''}**{n['title']}** {'🆕' if n['is_new'] else ''}")
                st.caption(f"{n['category']} • {n['unit']} • {n['posted_at'][:10]} • posted by {n['poster']}")
                st.write(n["body"])
                if n["file_path"]:
                    file_button(n["file_path"], f"n_dl_{n['id']}", "Attachment")
                if n["unit"] in pub_units and st.button("🗑 Remove notice", key=f"n_rm_{n['id']}"):
                    hub.remove_notice(n["id"]); st.rerun()
        if pub_units:
            with st.expander("➕ Post a notice or circular (for your unit)"):
                with st.form("add_notice", clear_on_submit=True):
                    title = st.text_input("Title")
                    body = st.text_area("Notice text")
                    c = st.columns(3)
                    unit = c[0].selectbox("Unit", pub_units)
                    cat = c[1].selectbox("Type", hub.NOTICE_CATEGORIES)
                    pin = c[2].checkbox("Pin to top")
                    up = st.file_uploader("Attachment (optional)")
                    if st.form_submit_button("Post"):
                        try:
                            hub.add_notice(title, body, cat, unit, user["faculty_id"], pin,
                                           (up.name, up.getvalue()) if up else None)
                            flash("Notice posted.")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
    with t3:
        c = st.columns(2)
        unit = c[0].selectbox("Unit", ["All"] + units, key="hf_unit")
        text = c[1].text_input("Filter by words", key="hf_txt")
        rows = hub.list_resources(None if unit == "All" else unit, None, text or None, kind="file")
        st.caption(f"{len(rows)} file(s)")
        for r in rows:
            resource_card(r, user, pub_units, "f")
        if pub_units:
            resource_form(user, pub_units, "File", "add_file")
    with t4:
        ul = hub.list_units()
        st.dataframe(pd.DataFrame([{"Unit": u["name"], "Type": u["kind"], "In-charge": u["head"],
                                    "Email": u["email"], "Phone": u["phone"], "Location": u["location"],
                                    "What they handle": u["description"],
                                    "Can publish": ", ".join(u["publishers"])} for u in ul]), hide_index=True)
        st.caption("Unit in-charges listed under 'Can publish' keep their unit's links and notices up to date.")


def page_timetable(user):
    st.header("📅 Timetable")
    target = user
    if user["role"] in ("HOD", "HR", "Admin"):
        pool = [u for u in db.all_users() if u["role"] in ("Faculty", "HOD")
                and (user["role"] != "HOD" or u["department"] == user["department"])]
        names = {f"{u['name']} ({u['department']})": u for u in pool}
        keys = list(names)
        me = next((i for i, k in enumerate(keys) if names[k]["faculty_id"] == user["faculty_id"]), 0)
        if keys:
            target = names[st.selectbox("Faculty", keys, index=me)]
    rows = hub.get_timetable(target["faculty_id"])
    if not rows:
        st.info("No timetable is loaded for this person yet. HR/Admin can import it under Admin → Bulk import.")
        return
    icons = {"done": "✅", "now": "▶️", "upcoming": "⏭"}
    today = hub.classes_today(target["faculty_id"])
    st.subheader(f"Today ({dt.datetime.now():%A})")
    if today:
        for r in today:
            st.write(f"{icons[r['status']]} **{r['start_time']}-{r['end_time']}**  {r['subject']} • {r['class_name']} • {r['room']}")
    else:
        st.write("No classes today. 🎉")
    st.subheader("Weekly timetable")
    df = pd.DataFrame(rows)
    df["slot"] = df["start_time"] + "-" + df["end_time"]
    df["cell"] = df["subject"] + " | " + df["class_name"] + " | " + df["room"]
    piv = df.pivot_table(index="slot", columns="day", values="cell", aggfunc=lambda x: " / ".join(x)).fillna("-")
    st.dataframe(piv[[d for d in hub.DAYS if d in piv.columns]])


def page_search(user, q):
    st.header(f"🔎 Results for “{q}”")
    cq = hub.clean_query(q)
    if cq:
        res = hub.search_all(cq, 6)
    else:   # only generic words typed (e.g. "form"): plain text match
        res = {"links": hub.list_resources(text=q, kind="link")[:8], "files": hub.list_resources(text=q, kind="file")[:8],
               "notices": hub.list_notices(text=q, limit=6), "units": []}
    found = False
    if res["links"]:
        found = True
        st.subheader("🔗 Links")
        for r in res["links"]:
            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                c1.markdown(f"**{r['title']}**")
                c1.caption(f"{r['description']}  \n{r['unit']} • {r['category']}")
                c2.link_button("Open ↗", r["url"])
    if res["files"]:
        found = True
        st.subheader("📄 Forms & documents")
        for r in res["files"]:
            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                c1.markdown(f"**{r['title']}**")
                c1.caption(f"{r['description']}  \n{r['unit']}")
                with c2:
                    file_button(r["file_path"], f"s_dl_{r['id']}")
    if res["notices"]:
        found = True
        st.subheader("📢 Notices & circulars")
        for n in res["notices"]:
            with st.expander(f"{n['title']}  •  {n['unit']}  •  {n['posted_at'][:10]}"):
                st.write(n["body"])
    if res["units"]:
        found = True
        st.subheader("🏛 Units & contacts")
        for u in res["units"][:3]:
            st.markdown(f"**{u['name']}** — in-charge: {u['head'] or '-'} • {u['email'] or '-'} • "
                        f"{u['phone'] or '-'} • {u['location'] or '-'}")
    hits = retrieve(q, 3) if docs_exist() else []
    if hits:
        found = True
        st.subheader("📘 Policy documents")
        for src, txt in hits:
            with st.expander(src):
                st.markdown(txt[:900])
    mine = db.query_requests(fid=user["faculty_id"], text=q).head(5)
    if len(mine):
        found = True
        st.subheader("📝 My requests")
        st.dataframe(mine[["ref_no", "type", "summary", "stage", "status"]], hide_index=True)
    if not found:
        st.info("Nothing found. Try other words, or ask the chatbot in your own words.")
    st.button("💬 Ask the bot instead", on_click=lambda: (st.session_state.update(gsearch=""), goto("💬 Ask the Bot")))


def page_dashboard(user):
    st.header(f"🏠 Welcome, {user['name']}")
    st.caption(f"{user['designation']} • {user['department']}")
    quick = [r for r in hub.list_resources(pinned=True) if r["url"]][:8]
    if quick:
        st.subheader("⚡ Quick access")
        cols = st.columns(4)
        for i, r in enumerate(quick):
            cols[i % 4].link_button(r["title"], r["url"])
    cl, cn = st.columns(2)
    with cl:
        st.subheader("📅 My classes today")
        today = hub.classes_today(user["faculty_id"])
        icons = {"done": "✅", "now": "▶️", "upcoming": "⏭"}
        if today:
            for r in today:
                st.write(f"{icons[r['status']]} **{r['start_time']}-{r['end_time']}** {r['subject']} • {r['class_name']} • {r['room']}")
        else:
            st.write("No classes today.")
    with cn:
        st.subheader("📢 Latest notices")
        for n in hub.list_notices(limit=4):
            st.markdown(f"{'📌 ' if n['pinned'] else ''}**{n['title']}** {'🆕' if n['is_new'] else ''}  \n"
                        f"<small>{n['unit']} • {n['posted_at'][:10]}</small>", unsafe_allow_html=True)
        st.button("Open all notices ➜", key="dash_notices", on_click=goto, args=("🔗 Resource Hub",))
    mine = db.query_requests(fid=user["faculty_id"])
    c = st.columns(4)
    c[0].metric("My open requests", int((mine["status"] == "In Progress").sum()))
    c[1].metric("Completed", int((mine["status"] == "Completed").sum()))
    c[2].metric("Rejected", int((mine["status"] == "Rejected").sum()))
    if user["role"] in APPROVER_ROLES:
        c[3].metric("Waiting for my action", len(db.pending_for(user)))
    b = db.balance(user["faculty_id"])
    st.subheader("Leave balance")
    c = st.columns(3)
    c[0].metric("Casual Leave (CL)", f"{b['CL']:g}")
    c[1].metric("Earned Leave (EL)", f"{b['EL']:g}")
    c[2].metric("Medical Leave (ML)", f"{b['ML']:g}")
    st.subheader("My recent requests")
    if mine.empty:
        st.info("No requests yet. Use ➕ New Request.")
    else:
        st.dataframe(mine.head(8)[["ref_no", "type", "summary", "stage", "status", "created_at"]],
                     hide_index=True)
    if user["role"] in MGMT_ROLES:
        st.subheader("Institute overview")
        allr = db.query_requests()
        c1, c2 = st.columns(2)
        c1.caption("Requests by type")
        c1.bar_chart(allr["type"].value_counts())
        c2.caption("Requests by status")
        c2.bar_chart(allr["status"].value_counts())
        done = allr[allr["status"] == "Completed"].copy()
        if len(done):
            done["hours"] = (pd.to_datetime(done["updated_at"]) - pd.to_datetime(done["created_at"])
                             ).dt.total_seconds() / 3600
            st.caption("Average turnaround time (hours) for completed requests")
            st.dataframe(done.groupby("type")["hours"].mean().round(1).rename("avg hours").reset_index(),
                         hide_index=True)


def uploads_to_files(ups):
    return [(f.name, f.getvalue()) for f in (ups or [])]


def page_new(user):
    st.header("➕ New Request")
    show_flash()
    n = st.session_state.get("form_n", 0)
    k = lambda s: f"{s}_{n}"
    rtype = st.selectbox("What do you need?", list(db.WORKFLOWS), key="new_type")
    wf = db.WORKFLOWS[rtype]
    st.caption("Approval path: **You** ➜ " + " ➜ ".join(f"**{s}** ({r})" for s, r in zip(wf["steps"], wf["roles"]))
               + f" ➜ **{wf['final']}**")
    details, files, ready = {}, [], True
    today = dt.date.today()

    if rtype == "Leave":
        b = db.balance(user["faculty_id"])
        c = st.columns(3)
        lt = c[0].selectbox("Leave type", db.LEAVE_TYPES, format_func=db.LEAVE_LABELS.get, key=k("lt"))
        d1 = c[1].date_input("From", today, key=k("d1"))
        d2 = c[2].date_input("To", d1, min_value=d1, key=k("d2")) if lt != "Half Day" else d1
        days = db.leave_days(lt, d1, d2)
        st.caption(f"Days requested: **{days:g}** • Your balance — CL {b['CL']:g}, EL {b['EL']:g}, ML {b['ML']:g}")
        reason = st.text_area("Reason", key=k("rs"))
        details = {"leave_type": lt, "from": str(d1), "to": str(d2), "reason": reason}
        if lt == "ML":
            files = uploads_to_files(st.file_uploader("Medical certificate (if more than 2 days)",
                                                      accept_multiple_files=True, key=k("up")))
    elif rtype == "Gate Pass":
        c = st.columns(3)
        d = c[0].date_input("Date", today, key=k("gd"))
        o = c[1].time_input("Out time", dt.time(13, 0), key=k("go"))
        r_ = c[2].time_input("Expected return", dt.time(15, 0), key=k("gr"))
        c = st.columns(2)
        purpose = c[0].selectbox("Purpose", ["Personal", "Official", "Medical", "Emergency"], key=k("gp"))
        dest = c[1].text_input("Destination", key=k("gdst"))
        reason = st.text_area("Reason", key=k("grs"))
        details = {"date": str(d), "out_time": o.strftime("%H:%M"), "return_time": r_.strftime("%H:%M"),
                   "purpose": purpose, "destination": dest, "reason": reason}
    elif rtype == "Room Booking":
        c = st.columns(4)
        room = c[0].selectbox("Room", list(db.ROOMS), format_func=lambda x: f"{x} (seats {db.ROOMS[x]})", key=k("rm"))
        d = c[1].date_input("Date", today + dt.timedelta(days=1), min_value=today, key=k("rd"))
        s = c[2].time_input("Start", dt.time(10, 0), key=k("rs1"))
        e = c[3].time_input("End", dt.time(12, 0), key=k("re"))
        c = st.columns(3)
        att = c[0].number_input("Attendees", 1, 200, 20, key=k("ra"))
        purpose = c[1].selectbox("Purpose", ["Department meeting", "Guest lecture", "Viva voce", "Workshop",
                                              "Placement drive briefing", "Student orientation", "Other"], key=k("rp"))
        req = c[2].text_input("Requirements (projector, mic…)", key=k("rq"))
        booked = db.room_bookings(room, str(d))
        if booked:
            st.warning("Already booked on this day: " + "; ".join(f"{b['start']}-{b['end']} ({b['by']})" for b in booked))
        else:
            st.success("No bookings yet for this room on this date.")
        details = {"room": room, "date": str(d), "start": s.strftime("%H:%M"), "end": e.strftime("%H:%M"),
                   "attendees": int(att), "purpose": purpose, "requirements": req}
    elif rtype == "Salary Update":
        cat = st.selectbox("What do you want updated?", ["Bank Account Change", "PAN / Aadhaar Update",
                           "NPS / PF Contribution Change", "Allowance Claim (HRA / Conveyance)",
                           "Arrears / Pay Fixation Query", "Other"], key=k("sc"))
        desc = st.text_area("Describe the change / issue", key=k("sd"))
        new = st.text_input("New value (e.g. last 4 digits of account, new percentage)", key=k("sn"))
        files = uploads_to_files(st.file_uploader("Supporting proof (cancelled cheque, receipts…)",
                                                  accept_multiple_files=True, key=k("up")))
        details = {"category": cat, "description": desc, "new_value": new}
    else:
        cat = st.selectbox("Which document?", ["Qualification Certificate (PhD / NET / SET)", "Experience Certificate",
                           "Address Proof", "Publication / Research Record", "Identity Proof",
                           "Service Book Entry", "Other"], key=k("dc"))
        desc = st.text_area("Short description", key=k("dd"))
        files = uploads_to_files(st.file_uploader("Upload document(s) — required",
                                                  accept_multiple_files=True, key=k("up")))
        details = {"category": cat, "description": desc}

    if st.button("Submit request", type="primary"):
        try:
            ref = db.create_request(user["faculty_id"], rtype, details, files)
            st.session_state.track_ref = ref
            st.session_state.form_n = n + 1
            flash(f"Submitted! Your reference number is **{ref}**. Track it any time under 📍 Track Request.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))


def page_track(user):
    st.header("📍 Track Request")
    scope = db.query_requests() if user["role"] in MGMT_ROLES else (
        db.query_requests(dept=user["department"]) if user["role"] == "HOD"
        else db.query_requests(fid=user["faculty_id"]))
    refs = list(scope["ref_no"])
    typed = st.text_input("Type a reference number (e.g. LV-2026-0004)").strip().upper()
    default = st.session_state.get("track_ref")
    pick = st.selectbox("…or pick from the list", refs,
                        index=refs.index(default) if default in refs else 0) if refs else None
    ref = typed or pick
    if not ref:
        st.info("No requests yet.")
        return
    r = db.get_request(ref)
    if not r or not can_view(user, r):
        st.error("Reference not found, or you don't have access to it.")
        return
    st.subheader(f"{r['ref_no']} — {r['summary']}")
    render_tracker(r)
    render_request_body(r, "trk")
    st.markdown("**History (who did what, and when)**")
    render_history(r)


def page_approvals(user):
    st.header("✅ Approvals")
    show_flash()
    rows = db.pending_for(user)
    if not rows:
        st.success("Nothing is waiting for you. 🎉")
        return
    st.caption(f"{len(rows)} request(s) waiting for your action as **{user['role']}**")
    for row in rows:
        r = db.get_request(row["ref_no"])
        with st.expander(f"{r['ref_no']} • {r['req_type']} • {r['requester']} • {r['summary']}"):
            render_tracker(r)
            render_request_body(r, row["ref_no"])
            render_history(r)
            note = st.text_input("Remarks (required for rejection)", key=f"note_{r['ref_no']}")
            c1, c2, _ = st.columns([1, 1, 4])
            for label, dec, col in (("Approve", "Approve", c1), ("Reject", "Reject", c2)):
                if col.button(label, key=f"{dec}_{r['ref_no']}", type="primary" if dec == "Approve" else "secondary"):
                    try:
                        db.act(r["ref_no"], user["faculty_id"], dec, note)
                        flash(f"{r['ref_no']} {'approved' if dec == 'Approve' else 'rejected'}.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))


def page_records(user):
    st.header("🗂 Records")
    st.caption("Every request is stored permanently. Search, filter and download any time.")
    opts = ["My requests"]
    if user["role"] == "HOD":
        opts.append("My department")
    if user["role"] in MGMT_ROLES:
        opts.append("All requests")
    scope = st.radio("Show", opts, horizontal=True)
    c = st.columns([2, 2, 2, 2])
    types = c[0].multiselect("Type", list(db.WORKFLOWS))
    statuses = c[1].multiselect("Status", ["In Progress", "Completed", "Rejected"])
    text = c[2].text_input("Search (ref / name / words)")
    rng = c[3].date_input("Submitted between", value=(dt.date.today() - dt.timedelta(days=365), dt.date.today()))
    d_from, d_to = (rng if isinstance(rng, (tuple, list)) and len(rng) == 2 else (None, None))
    df = db.query_requests(
        fid=user["faculty_id"] if scope == "My requests" else None,
        dept=user["department"] if scope == "My department" else None,
        types=types, statuses=statuses, text=text, d_from=d_from, d_to=d_to)
    st.write(f"**{len(df)}** record(s)")
    st.dataframe(df, hide_index=True)
    c = st.columns(3)
    c[0].download_button("⬇️ Download these records (CSV)", df.to_csv(index=False).encode(),
                         "requests.csv", "text/csv")
    if user["role"] in MGMT_ROLES:
        c[1].download_button("⬇️ Full audit trail (CSV)", db.audit_trail().to_csv(index=False).encode(),
                             "audit_trail.csv", "text/csv")
    if len(df):
        pick = st.selectbox("Open a record", list(df["ref_no"]))
        st.button("Show full tracking ➜", on_click=goto, args=("📍 Track Request", None, pick))


def page_admin(user):
    st.header("⚙️ Admin")
    t1, t2, tu, tb, t3, t4, t5 = st.tabs(["📄 Policy documents", "👥 Staff", "🏛 Units & publishers",
                                           "📥 Bulk import", "💾 Backup", "🔑 My PIN", "🤖 AI status"])
    with t1:
        st.caption("The chatbot answers from these files. Upload your real handbook, circulars, SOPs.")
        ups = st.file_uploader("Add documents (PDF / TXT / MD)", type=["pdf", "txt", "md"], accept_multiple_files=True)
        if ups and st.button("Save documents"):
            for f in ups:
                with open(os.path.join(DOCS_DIR, os.path.basename(f.name)), "wb") as fh:
                    fh.write(f.getbuffer())
            st.success(f"{len(ups)} file(s) saved. The bot has re-indexed them.")
        for f in sorted(glob.glob(f"{DOCS_DIR}/*")):
            st.write("•", os.path.basename(f))
    with t2:
        st.dataframe(pd.DataFrame(db.all_users()), hide_index=True)
        with st.form("adduser"):
            st.markdown("**Add a new staff member**")
            c = st.columns(3)
            name = c[0].text_input("Name")
            dept = c[1].text_input("Department")
            desig = c[2].text_input("Designation")
            c = st.columns(4)
            email = c[0].text_input("Email")
            role = c[1].selectbox("Role", ["Faculty", "HOD", "HR", "Admin", "Accounts", "Security"])
            doj = c[2].date_input("Date of joining")
            pin = c[3].text_input("Initial PIN", "1234")
            if st.form_submit_button("Add") and name and dept:
                fid = db.add_user(name, dept, desig, email, "", role, str(doj), None, pin)
                st.success(f"Added {name} with ID {fid}.")
    with tu:
        ul = hub.list_units()
        st.dataframe(pd.DataFrame([{"Unit": u["name"], "Type": u["kind"], "In-charge": u["head"], "Email": u["email"],
                                    "Phone": u["phone"], "Location": u["location"],
                                    "Can publish": ", ".join(u["publishers"])} for u in ul]), hide_index=True)
        with st.form("unit_form"):
            st.markdown("**Add or update a unit** (use an existing name to update it)")
            c = st.columns(3)
            uname = c[0].text_input("Unit name (e.g. Research Cell)")
            ukind = c[1].selectbox("Type", ["Central unit", "Department / Office"])
            uhead = c[2].text_input("In-charge name")
            c = st.columns(3)
            uemail, uphone, uloc = c[0].text_input("Email"), c[1].text_input("Phone / extension"), c[2].text_input("Location")
            udesc = st.text_input("What this unit handles")
            if st.form_submit_button("Save unit"):
                try:
                    hub.save_unit(uname, ukind, uhead, uemail, uphone, uloc, udesc)
                    st.success("Saved.")
                except ValueError as e:
                    st.error(str(e))
        st.markdown("**Who can publish links and notices for a unit**")
        people = {f"{u['name']} ({u['department']})": u["faculty_id"] for u in db.all_users()}
        c = st.columns([2, 3, 1, 1])
        pu = c[0].selectbox("Unit", hub.unit_names(), key="pub_unit")
        pp = c[1].selectbox("Person", list(people), key="pub_person")
        if c[2].button("Add"):
            hub.add_publisher(pu, people[pp]); st.rerun()
        if c[3].button("Remove"):
            hub.remove_publisher(pu, people[pp]); st.rerun()
        st.caption("HODs can always publish for their own department. HR and Admin can publish for every unit.")
    with tb:
        st.markdown("**Links: add many at once**")
        st.download_button("⬇️ Links template (CSV)", LINKS_TEMPLATE, "links_template.csv", "text/csv")
        lf = st.file_uploader("Upload links CSV", type=["csv"], key="imp_links")
        if lf and st.button("Import links"):
            added, errs = hub.import_resources_df(pd.read_csv(lf, dtype=str), user["faculty_id"])
            st.success(f"{added} link(s) added.")
            for e in errs:
                st.warning(e)
        st.divider()
        st.markdown("**Timetable: replaces the whole timetable**")
        st.download_button("⬇️ Timetable template (CSV)", TT_TEMPLATE, "timetable_template.csv", "text/csv")
        tf = st.file_uploader("Upload timetable CSV", type=["csv"], key="imp_tt")
        if tf and st.button("Import timetable (replace all)"):
            n, errs = hub.import_timetable_df(pd.read_csv(tf, dtype=str))
            if errs:
                st.error("Nothing imported. Fix these rows and try again:")
                for e in errs[:30]:
                    st.write("•", e)
            else:
                st.success(f"{n} timetable row(s) imported.")
    with t3:
        st.caption("Your data lives in one file. Download a backup regularly.")
        with open(db.DB_PATH, "rb") as fh:
            st.download_button("⬇️ Download database backup", fh.read(),
                               f"faculty_portal_backup_{dt.date.today()}.db")
    with t4:
        pin_tab(user)
    with t5:
        key = secret("GEMINI_API_KEY")
        st.write("Gemini key:", "✅ found" if key else "❌ not set (see README: Phase 4)")
        if key:
            if st.button("Test AI connection"):
                with st.spinner("Contacting Gemini…"):
                    text, err, model = ask_llm([], "Say hello to the faculty in one short sentence.", "")
                if text:
                    st.success(f"Working. Model used: **{model}**")
                    st.write(text)
                else:
                    st.error(f"Not working: {err}")
            try:
                st.caption("Models available to your key (best first): " + ", ".join(gemini_candidates(key)[:6]))
            except Exception as e:
                st.caption(f"Could not list models: {str(e)[:150]}")
            if st.session_state.get("ai_error"):
                st.warning("Last chat error: " + str(st.session_state["ai_error"]))
        st.info("Privacy: with the free Gemini tier, Google may use what is sent to improve its products. "
                "This bot sends only the user's question, recent chat, and matching policy text. "
                "Leave balances and request details are answered locally and never sent.")


def pin_tab(user):
    with st.form("pin"):
        old = st.text_input("Current PIN", type="password")
        new = st.text_input("New PIN (min 4 characters)", type="password")
        if st.form_submit_button("Change PIN"):
            if not db.verify(user["faculty_id"], old):
                st.error("Current PIN is wrong.")
            elif len(new) < 4:
                st.error("New PIN is too short.")
            else:
                db.set_pin(user["faculty_id"], new)
                st.success("PIN changed.")


# --------------------------------------------------------------------- main
if "user" not in st.session_state:
    login_screen()
    st.stop()

user = db.get_user(st.session_state.user["faculty_id"])
pages = {"💬 Ask the Bot": page_bot, "🏠 Dashboard": page_dashboard, "🔗 Resource Hub": page_hub,
         "📅 Timetable": page_timetable, "➕ New Request": page_new,
         "📍 Track Request": page_track}
if user["role"] in APPROVER_ROLES:
    pages["✅ Approvals"] = page_approvals
pages["🗂 Records"] = page_records
if user["role"] in MGMT_ROLES:
    pages["⚙️ Admin"] = page_admin
else:
    pages["🔑 My PIN"] = lambda u: (st.header("🔑 Change PIN"), pin_tab(u))

with st.sidebar:
    st.title("🎓 Faculty Portal")
    st.write(f"**{user['name']}**")
    st.caption(f"{user['role']} • {user['department']}")
    if "nav" not in st.session_state or st.session_state.nav not in pages:
        st.session_state.nav = "🏠 Dashboard"
    st.text_input("🔎 Search everything", key="gsearch", placeholder="LMS, NAAC form, circular, IQAC…")
    st.radio("Go to", list(pages), key="nav", label_visibility="collapsed",
             on_change=lambda: st.session_state.update(gsearch=""))
    if user["role"] in APPROVER_ROLES:
        n_wait = len(db.pending_for(user))
        if n_wait:
            st.warning(f"{n_wait} request(s) waiting for you")
    if st.button("Sign out"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

gq = (st.session_state.get("gsearch") or "").strip()
if gq:
    page_search(user, gq)
else:
    pages[st.session_state.nav](user)
