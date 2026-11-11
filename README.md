# Faculty Portal - HR Chatbot + Online Requests + Approval Tracking

## Run it
    pip install -r requirements.txt
    streamlit run app.py
First launch auto-creates a SAMPLE dataset (32 staff, 70 requests with full approval history,
5 sample policy documents). Demo login: pick any person, PIN = 1234.
Reset sample data any time:  python seed.py --reset

## What is inside
| File | Purpose |
|---|---|
| hub.py | Resource Hub: links, forms, notices, units, timetable, global search |
| app.py | Screens: chatbot, new request, tracker, approvals, records, admin |
| db.py  | Database + approval workflow engine (all rules live here) |
| seed.py | Sample data generator (replace with real data) |
| smoke_test.py | Automated check that every page/role works: `python smoke_test.py` |

## Request types and approval path
| Request | Path |
|---|---|
| Leave | Faculty -> HOD Review -> HR Approval -> Approved (balance deducted) |
| Gate Pass | Faculty -> HOD Approval -> Security Clearance -> Pass Issued |
| Room Booking | Faculty -> Admin Approval -> Confirmed (clash check built in) |
| Salary Update | Faculty -> HR Verification -> Accounts Processing -> Completed |
| Document Update | Faculty -> HR Verification -> Admin Record Update -> Updated |
To change a path, edit WORKFLOWS at the top of db.py.

## Where records are saved
- faculty_portal.db  : all people, requests, stages, remarks, timestamps (SQLite)
- uploads/<ref-no>/  : attached documents
- Records page: search/filter + CSV download. Admin page: full backup download.

## Moving from sample data to real data
1. Admin > Policy documents: upload your real handbook/circulars (delete the sample .md files from docs/).
2. Admin > Staff: add real people (or import a CSV with db.add_user in a small script).
3. Delete faculty_portal.db and uploads/, then add real staff, and change all PINs.

## AI chat (ChatGPT-style answers, free tier)
1. Get a key at aistudio.google.com (Get API key).
2. Either (a) PowerShell, same window you run the app in:
       $env:GEMINI_API_KEY="your-key"
       streamlit run app.py
   or (b) copy .streamlit/secrets.toml.example to .streamlit/secrets.toml and paste the key.
3. Sign in as HR/Admin > Admin > AI status > Test AI connection.
The app asks Google which models your key can use and picks the newest Flash model automatically.
Leave balances and request status are answered locally and are never sent to the AI.
Without a key the bot shows the closest policy sections with source names.

## Hosting note (important)
SQLite is a file. Run the portal on ONE college PC/server and your records are permanent.
Streamlit Community Cloud wipes local files when the app restarts, so do not use it for real records
(use it only for demos, or switch the database to a free hosted one such as Supabase).
Back up faculty_portal.db + uploads/ weekly.

## Known limits of this starter
- PIN login is basic (fine for a pilot, not for a public internet).
- No email/WhatsApp notifications yet.
- Document search is keyword-based (TF-IDF); with a Gemini key answers read naturally.


## Resource Hub (single window for links, notices, forms, timetable)
- Sidebar search bar searches links, forms, notices, unit contacts, policy documents and your requests.
- Dashboard: quick-access tiles, today's classes, latest notices.
- Resource Hub: Links | Notices & Circulars | Forms & Documents | Units & Contacts.
- Each link/notice belongs to a UNIT (IQAC, Training & Placement, Examination Cell, departments...).
  Unit in-charges (Admin > Units & publishers) and HODs publish for their own unit; HR/Admin for all.
- Anyone can press "Report broken/outdated"; owners see it and press "Verified". Links not verified for 90 days are flagged.
- Chatbot returns links, form downloads, notices, unit contacts and today's classes.
- Fill it fast: Admin > Bulk import (links CSV, timetable CSV).
- Already have an older database? Nothing breaks. To add sample hub data: python seed.py --hub
- Student attendance/details stay in your ERP/LMS: the portal links to them (it does not copy student data).
