import os, db, seed
if not os.path.exists(db.DB_PATH): seed.run()
from streamlit.testing.v1 import AppTest
import db, datetime as dt
users = {u["role"]: u for u in db.all_users()}
def run(user, page, setup=None):
    at = AppTest.from_file("app.py", default_timeout=60)
    at.session_state["user"] = user
    at.session_state["nav"] = page
    if setup: setup(at)
    at.run()
    assert not at.exception, (user["role"], page, [e.value for e in at.exception])
    return at
at = AppTest.from_file("app.py"); at.run(); assert not at.exception; print("login ok")
for role in ["Faculty","HOD","HR","Admin","Accounts","Security"]:
    u = users[role]
    pages = ["🏠 Dashboard","🔗 Resource Hub","📅 Timetable","➕ New Request","📍 Track Request","🗂 Records","💬 Ask the Bot"]
    if role in {"HOD","HR","Admin","Accounts","Security"}: pages.append("✅ Approvals")
    if role in {"HR","Admin"}: pages.append("⚙️ Admin")
    for p in pages: run(u,p)
    print(role,"pages ok")
# each request type form renders
for t in db.WORKFLOWS:
    at = run(users["Faculty"], "➕ New Request", lambda a: a.session_state.__setitem__("new_type", t))
    print(t,"form ok")
# submit a leave through UI
at = run(users["Faculty"], "➕ New Request", lambda a: a.session_state.__setitem__("new_type","Leave"))
at.text_area[0].input("Family function"); at.button[0].click().run()
print("after submit:", [e.value for e in at.exception], at.session_state.get("track_ref"))
# chatbot
at = run(users["Faculty"], "💬 Ask the Bot")
for q in ["how many CL left?","I want to book conference room","what is the notice period","status of LV-2026-0001","where is IT cell"]:
    at.chat_input[0].set_value(q).run(); assert not at.exception
    print("Q:",q,"->",at.chat_message[-1].markdown[0].value[:110].replace("\n"," "))
