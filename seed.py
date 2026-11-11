"""Generates a realistic SAMPLE dataset: 32 staff, leave balances, ~70 requests with full
approval history, and sample policy documents for the chatbot.
Replace with real data later (see README). Run:  python seed.py --reset"""
import os, sys, random, datetime as dt
import db, hub

DOCS_DIR = "docs"

DEPTS = {
    "Computer Science": ["Dr. Harpreet Singh", "Dr. Neha Verma", "Prof. Rajesh Kumar", "Prof. Simran Kaur"],
    "Management Studies": ["Dr. Anita Sharma", "Prof. Vikram Malhotra", "Dr. Pooja Arora", "Prof. Gurpreet Bedi"],
    "Commerce": ["Dr. Sunil Mehta", "Prof. Kavita Joshi", "Dr. Manpreet Gill", "Prof. Ravi Chopra"],
    "Mechanical Engineering": ["Dr. Balwinder Sandhu", "Prof. Amit Thakur", "Dr. Deepak Bhatia", "Prof. Jaspreet Dhillon"],
    "English": ["Dr. Meenakshi Kapoor", "Prof. Tarun Bajaj", "Dr. Ritu Saini", "Prof. Navdeep Kaur"],
    "Mathematics": ["Dr. Satnam Grewal", "Prof. Sneha Rani", "Dr. Karan Walia", "Prof. Mandeep Kaur"],
}
STAFF = [  # (name, dept, designation, role)
    ("Ms. Rekha Nanda", "Human Resources", "HR Manager", "HR"),
    ("Mr. Ajay Soni", "Human Resources", "HR Executive", "HR"),
    ("Mr. Harish Tandon", "Administration", "Administrative Officer", "Admin"),
    ("Ms. Parveen Lamba", "Administration", "Office Superintendent", "Admin"),
    ("Mr. Lalit Goyal", "Accounts", "Accounts Officer", "Accounts"),
    ("Ms. Shalini Duggal", "Accounts", "Accountant", "Accounts"),
    ("Mr. Surinder Pal", "Security", "Security Officer", "Security"),
    ("Mr. Baldev Raj", "Security", "Security Supervisor", "Security"),
]
APPROVE_NOTES = ["Approved", "Recommended", "Verified, OK", "Fine, go ahead", "Checked and approved"]
REJECT_NOTES = {
    "Leave": ["Classes/exams scheduled on these dates", "Please apply with 3 days notice"],
    "Gate Pass": ["Invigilation duty at that time", "Not approved, lectures pending"],
    "Room Booking": ["Room reserved for university event", "Overlaps with a scheduled exam"],
    "Salary Update": ["Supporting proof unclear, resubmit", "Details do not match records"],
    "Document Update": ["Scan not readable, please re-upload", "Attested copy required"],
}
LEAVE_REASONS = {
    "CL": ["Family function", "Personal work", "Child's school event", "Bank / government work"],
    "EL": ["Family vacation", "Visiting home town", "Wedding in family"],
    "ML": ["Viral fever, doctor advised rest", "Dental procedure", "Medical check-up and recovery"],
    "Half Day": ["Doctor appointment", "Parent-teacher meeting", "Vehicle service"],
    "OD": ["Attending FDP (Faculty Development Programme)", "Paper presentation at national conference",
           "University examination duty", "Accreditation visit support"],
}
SALARY_ITEMS = [
    ("Bank Account Change", "Please update my salary account to my new bank account.", "A/c ending 4821"),
    ("PAN / Aadhaar Update", "PAN card name correction needed in payroll records.", "PAN updated"),
    ("NPS / PF Contribution Change", "Request to change my NPS contribution percentage.", "10% of Basic"),
    ("Allowance Claim (HRA / Conveyance)", "Submitting rent receipts for HRA claim for this quarter.", ""),
    ("Arrears / Pay Fixation Query", "Pay fixation after promotion not reflecting in payslip.", ""),
]
DOC_ITEMS = [
    ("Qualification Certificate (PhD / NET / SET)", "Adding my latest qualification certificate to service record."),
    ("Experience Certificate", "Experience certificate from previous institute for service book."),
    ("Address Proof", "Updated address proof after change of residence."),
    ("Publication / Research Record", "Adding new journal publications to my research record."),
    ("Identity Proof", "Renewed identity document for personnel file."),
    ("Service Book Entry", "Request for service book entry correction."),
]
ROOM_PURPOSES = ["Department meeting", "Guest lecture", "Viva voce", "Workshop",
                 "Placement drive briefing", "Student orientation"]


def _iso(t):
    return t.isoformat(timespec="seconds")


def write_policy_docs():
    os.makedirs(DOCS_DIR, exist_ok=True)
    if any(f.endswith((".md", ".txt", ".pdf")) for f in os.listdir(DOCS_DIR)):
        return
    docs = {
"leave_policy.md": """# Leave Policy (SAMPLE - replace with your institute's policy)

## Leave entitlement per year
- Casual Leave (CL): 12 days per calendar year. Maximum 3 CL at a stretch. CL cannot be carried forward.
- Earned Leave (EL): 15 days per year. Needs 7 days advance notice. EL can be carried forward up to 60 days.
- Medical Leave (ML): 10 days per year. A medical certificate is required for ML of more than 2 days.
- Half Day leave counts as 0.5 CL. Apply before 10:00 AM on the same day or in advance.
- On Duty (OD): Used for conferences, FDPs, university examination duty and accreditation work. No leave is deducted. OD needs HOD approval and a supporting letter or invitation.

## How to apply
Apply online through the portal: New Request > Leave. The request goes first to your HOD and then to HR. You can track the stage of your application under Track Request. Leave is deducted from your balance only after final approval by HR.

## Rules
- Leave cannot be claimed on exam days or invigilation duty days without prior HOD permission.
- If you are on leave, arrange an alternate for your lectures and inform the HOD.
- Leave taken without approval is treated as Loss of Pay.
""",
"salary_and_benefits.md": """# Salary and Benefits (SAMPLE)

## Salary credit
Salary is credited to your bank account on or before the 5th of the following month. If the 5th is a holiday it is credited on the previous working day.

## Payslip
Download your payslip from the ERP portal: Login > Payroll > Payslips > select month > Download. If a payslip is missing, raise a Salary Update request.

## NPS and PF deductions
- NPS: Employee contribution is 10% of Basic Pay plus DA, deducted monthly. The institute contributes an equal amount for eligible permanent faculty.
- You can request a change in NPS contribution percentage once per financial year through a Salary Update request.
- Provident Fund (PF) is deducted at 12% of Basic for eligible staff.

## Medical claim process
1. Keep all original bills, prescriptions and discharge summary.
2. Submit the claim form with bills to HR within 30 days of treatment.
3. HR verifies and forwards to Accounts. Reimbursement is made with the next salary.
Outpatient claims are limited to Rs. 15,000 per year. Hospitalisation claims are processed as per the group insurance policy.

## Changing bank account or personal details
Raise a Salary Update request with a cancelled cheque or bank passbook copy attached. It is verified by HR and processed by Accounts.
""",
"service_rules.md": """# Service Rules and Code of Conduct (SAMPLE)

## Notice period
- Probation period: 1 month notice from either side.
- Confirmed faculty: 3 months notice or salary in lieu of notice.
- Relieving is subject to clearance from Library, Accounts, IT Cell and HOD.

## Dress code
Faculty are expected to dress formally and decently. Formal Indian or western attire is acceptable. Casual wear such as T-shirts and shorts is not allowed during working hours. On special days the Principal may announce a relaxed dress code.

## Conference and FDP funding
- National conference / FDP: up to Rs. 15,000 per year for registration, travel and stay, if you are presenting a paper.
- International conference: up to Rs. 50,000 once in 3 years, subject to Principal approval and proof of paper acceptance.
- Apply at least 15 days in advance. Submit certificate and bills within 15 days after the event. Attendance during the conference is marked as OD.

## Service book
The service book of every permanent employee is maintained by the HR department. It records joining, promotions, increments, qualifications and leave. To add a qualification or correct an entry raise a Document Update request with proof attached.
""",
"daily_work_sop.md": """# Daily Work SOP (SAMPLE)

## Attendance on LMS
Mark student attendance on the LMS within 24 hours of the lecture. Login > My Courses > select class > Attendance > Mark. Late entries need HOD approval.

## Uploading internal marks
Marks must be uploaded on the LMS (Exam > Internal Marks) before the deadline announced by the Controller of Examinations, normally within 5 days of the test. After the deadline, marks can be changed only with written approval of the HOD and Controller.

## Timetable
The timetable is on the ERP portal under Academics > Timetable and is also pinned in each department office.

## Hostel duty
Hostel duty roster is prepared by the Chief Warden each semester. Duty faculty must reach the hostel by 6:00 PM, do roll call at 9:00 PM and record the night report. Swaps are allowed only with the Warden's permission.

## Booking rooms
- Rooms: Seminar Hall (150), Conference Room A (30), Conference Room B (20), Board Room (12), Computer Lab 1 (60), Smart Classroom 204 (60).
- Book through the portal: New Request > Room Booking. Admin approves. Bookings are possible from 08:00 to 20:00.
- Seminar Hall needs 2 days advance booking. Maximum booking for one event is 4 hours.

## Gate pass
Faculty leaving campus during working hours (9:00 AM to 4:30 PM) for personal work need a gate pass. Apply under New Request > Gate Pass. HOD approves and Security issues the pass. Show the approved pass at the main gate while leaving.
""",
"new_faculty_guide.md": """# New Faculty Guide (SAMPLE)

## First week checklist
1. Report to HR with original certificates and 2 passport size photographs for joining formalities.
2. ID card: collect from the Admin Office, Block A first floor. It takes 3 working days.
3. IT Cell: Block A ground floor, Room G-12. They create your official email, ERP and LMS login. Open 9:30 AM to 5:00 PM.
4. Meet your HOD and your assigned mentor. Your mentor is shown on your portal profile.
5. Library membership: Library counter, ground floor, Block B.
6. Attend the induction programme held on the first Monday of every month.

## Useful contacts
- HR Office: Block A, Room 105, extension 105.
- Admin Office: Block A, first floor, extension 120.
- IT Helpdesk: extension 112. Email: ithelp@institute.example.
- Security Office: Main gate, extension 100.

## Probation
The probation period is 6 months. Confirmation depends on the HOD's report and student feedback.
""",
    }
    for name, text in docs.items():
        with open(os.path.join(DOCS_DIR, name), "w", encoding="utf-8") as f:
            f.write(text)


def _make_request_details(rnd, rtype, base):
    files = []
    if rtype == "Leave":
        lt = rnd.choices(db.LEAVE_TYPES, [50, 15, 8, 15, 12])[0]
        start = base + dt.timedelta(days=rnd.randint(-5, 10))
        n = 1 if lt == "Half Day" else rnd.choice([1, 1, 2, 3]) if lt in ("CL", "OD") else rnd.choice([2, 3, 5])
        d = {"leave_type": lt, "from": str(start), "to": str(start + dt.timedelta(days=n - 1)),
             "reason": rnd.choice(LEAVE_REASONS[lt])}
    elif rtype == "Gate Pass":
        out_h = rnd.randint(11, 15)
        d = {"date": str(base), "out_time": f"{out_h:02d}:00",
             "return_time": f"{out_h + rnd.randint(1, 3):02d}:00",
             "purpose": rnd.choice(["Personal", "Official", "Medical", "Emergency"]),
             "destination": rnd.choice(["Bank", "Hospital", "Passport office", "University office", "Home"]),
             "reason": rnd.choice(["Urgent work", "Appointment", "Family matter", "Official errand"])}
    elif rtype == "Room Booking":
        room = rnd.choice(list(db.ROOMS))
        sh = rnd.randint(9, 15)
        d = {"room": room, "date": str(base + dt.timedelta(days=rnd.randint(1, 10))),
             "start": f"{sh:02d}:00", "end": f"{sh + rnd.randint(1, 3):02d}:00",
             "attendees": rnd.randint(8, min(db.ROOMS[room], 40)),
             "purpose": rnd.choice(ROOM_PURPOSES), "requirements": rnd.choice(["Projector", "Mic + projector", "None"])}
    elif rtype == "Salary Update":
        cat, desc, new = rnd.choice(SALARY_ITEMS)
        d = {"category": cat, "description": desc, "new_value": new}
    else:
        cat, desc = rnd.choice(DOC_ITEMS)
        d = {"category": cat, "description": desc}
        files = [("sample_document.txt", b"Sample attachment generated for the demo dataset.")]
    return d, files


# ----------------------------------------------------------------- hub sample data
E = "https://erp.institute.example"
L = "https://lms.institute.example"
SAMPLE_LINKS = [  # title, url, category, unit, description, tags, pinned
    ("ERP Portal (Login)", f"{E}/login", "IT & Systems", "IT Cell", "Main ERP: payroll, payslips, timetable, academics", "erp login payroll payslip", 1),
    ("LMS: Mark Student Attendance", f"{L}/attendance", "Academic", "Academic Administration", "Mark class attendance within 24 hours of the lecture", "lms attendance students mark", 1),
    ("LMS: Upload Internal Marks", f"{L}/marks", "Examination", "Examination Cell", "Upload internal assessment marks before the deadline", "lms marks upload internal assessment", 1),
    ("Student Attendance Reports", f"{L}/reports/attendance", "Student Services", "Academic Administration", "Class-wise and student-wise attendance and shortage reports (data stays in LMS)", "attendance report students shortage defaulter", 0),
    ("Student Profile and Details", f"{E}/students", "Student Services", "Academic Administration", "Student profile, contact details and mentor-mentee list (ERP login required)", "student details profile mentor mentee", 0),
    ("My Timetable (ERP)", f"{E}/timetable", "Academic", "Academic Administration", "Official class timetable and substitution list", "timetable schedule classes substitution", 0),
    ("Examination Cell Portal", "https://exam.institute.example", "Examination", "Examination Cell", "Exam schedule, invigilation duty, results and revaluation", "exam invigilation duty schedule result revaluation", 1),
    ("Question Paper Submission", "https://exam.institute.example/qp-upload", "Examination", "Examination Cell", "Submit end-semester question papers and scheme of marking", "question paper qp setting upload", 0),
    ("IQAC: AQAR and NAAC Data Templates", "https://iqac.institute.example/aqar", "Research & IQAC", "IQAC", "Annual Quality Assurance Report and NAAC criteria data templates", "naac aqar iqac criteria data template ssr", 1),
    ("IQAC: Faculty Achievements Entry", "https://iqac.institute.example/achievements", "Research & IQAC", "IQAC", "Record FDPs, publications, patents and awards for accreditation", "fdp publication patent award achievements iqac", 0),
    ("Training and Placement Cell", "https://tnp.institute.example", "Placement", "Training & Placement", "Company drives, student registrations and placement statistics", "placement drive recruitment tnp company", 1),
    ("Placement Drive Calendar", "https://tnp.institute.example/calendar", "Placement", "Training & Placement", "Upcoming campus drives and pre-placement talks", "placement calendar drive schedule ppt", 0),
    ("Library Catalogue (OPAC)", "https://library.institute.example/opac", "Library", "Library", "Search books, journals and e-resources", "library books catalogue opac journals", 0),
    ("Library: Request a Book or Journal", "https://library.institute.example/request", "Library", "Library", "Recommend new books and journals for purchase", "library request book journal purchase recommend", 0),
    ("IT Helpdesk: Raise a Ticket", "https://helpdesk.institute.example", "IT & Systems", "IT Cell", "Wi-Fi, email, projector, password reset and software issues", "it helpdesk ticket wifi email password support projector", 1),
    ("Official Email (Webmail)", "https://mail.institute.example", "IT & Systems", "IT Cell", "Institute email login", "email webmail mail login", 0),
    ("Payslip Download", f"{E}/payroll/payslip", "HR & Payroll", "Human Resources", "Download monthly payslips", "payslip salary download payroll", 0),
    ("Form 16 and Tax Documents", f"{E}/payroll/form16", "HR & Payroll", "Accounts", "Annual tax statements and investment declaration", "form16 tax itr investment declaration", 0),
    ("NPS Trust (official)", "https://npstrust.org.in", "External", "Human Resources", "National Pension System information", "nps pension", 0),
    ("EPFO Member Portal", "https://www.epfindia.gov.in", "External", "Human Resources", "Provident fund passbook and claims", "pf epfo provident fund passbook", 0),
    ("UGC", "https://www.ugc.gov.in", "External", "Academic Administration", "University Grants Commission notices and regulations", "ugc regulations notices grants", 0),
    ("NAAC", "https://www.naac.gov.in", "External", "IQAC", "National Assessment and Accreditation Council", "naac accreditation", 0),
    ("NIRF", "https://www.nirfindia.org", "External", "IQAC", "National Institutional Ranking Framework", "nirf ranking", 0),
    ("AICTE", "https://www.aicte-india.org", "External", "Academic Administration", "All India Council for Technical Education", "aicte approval", 0),
    ("SWAYAM", "https://swayam.gov.in", "External", "Academic Administration", "Free online courses with credit transfer", "swayam mooc online courses", 0),
    ("NPTEL", "https://nptel.ac.in", "External", "Academic Administration", "Online courses and FDP certifications", "nptel courses certification", 0),
    ("Shodhganga (PhD theses)", "https://shodhganga.inflibnet.ac.in", "Research & IQAC", "Library", "Repository of Indian PhD theses", "shodhganga thesis phd research repository", 0),
    ("Google Scholar", "https://scholar.google.com", "Research & IQAC", "Library", "Search scholarly literature and track citations", "scholar google citations research papers", 0),
    ("ORCID", "https://orcid.org", "Research & IQAC", "IQAC", "Persistent researcher identifier", "orcid researcher id", 0),
    ("DigiLocker", "https://www.digilocker.gov.in", "External", "Administration", "Digital copies of certificates and documents", "digilocker documents certificates", 0),
]
SAMPLE_FORMS = [  # title, unit, category, description, tags
    ("Medical Reimbursement Claim Form (SAMPLE)", "Human Resources", "Forms", "Attach original bills and prescriptions", "medical claim reimbursement form"),
    ("Conference / FDP Funding Application (SAMPLE)", "Academic Administration", "Forms", "Apply 15 days before the event", "conference fdp funding application travel"),
    ("TA/DA Claim Form (SAMPLE)", "Accounts", "Forms", "Travel and daily allowance claim after duty", "ta da travel allowance claim"),
]
SAMPLE_NOTICES = [  # title, body, category, unit, pinned, days_ago
    ("Internal Assessment-II schedule released", "IA-II will be held from the first week of next month. Question papers must reach the Examination Cell 5 days before the test. Marks upload deadline is 5 days after each test.", "Circular", "Examination Cell", 1, 3),
    ("AQAR data submission: last date", "All departments must submit AQAR data (publications, FDPs attended, research projects) on the IQAC portal by the 25th of this month. Incomplete data will delay the NAAC submission.", "Deadline", "IQAC", 1, 5),
    ("Campus placement drive next week", "A recruitment drive for final-year MBA and BCA students is scheduled next Wednesday. Faculty coordinators from each department should share the final student lists with T&P by Monday.", "Event", "Training & Placement", 0, 2),
    ("Invigilation duty chart for mid-semester exams", "Invigilation duty chart is available on the Examination Cell portal. Duty swaps must be approved by the Controller of Examinations at least one day in advance.", "Notice", "Examination Cell", 0, 8),
    ("LMS scheduled maintenance this Sunday", "The LMS and ERP will be unavailable on Sunday from 2:00 AM to 6:00 AM for maintenance. Please complete attendance and marks entries before Saturday night.", "Notice", "IT Cell", 0, 1),
    ("Form 16 now available", "Form 16 for the last financial year can be downloaded from ERP > Payroll > Form 16. Contact Accounts for corrections.", "Notice", "Accounts", 0, 12),
    ("Holiday list and academic calendar update", "The revised academic calendar and holiday list are available in the Resource Hub. Faculty should plan syllabus completion accordingly.", "Circular", "Academic Administration", 0, 15),
    ("Library: Book Bank for faculty", "Faculty can now borrow up to 10 books for one semester. New arrivals list is on the library catalogue.", "Notice", "Library", 0, 20),
    ("NPS contribution change window", "Request for change in NPS contribution percentage can be raised once per financial year through the portal (New Request > Salary Update).", "Policy Update", "Human Resources", 0, 25),
    ("Department meeting: Computer Science", "Monthly department meeting on Friday at 3:00 PM in Conference Room A. Agenda: syllabus review and lab upgrades.", "Notice", "Computer Science", 0, 4),
]
UNIT_INFO = {  # unit: (head, email, phone, location, description, publisher name)
    "IQAC": ("Dr. Neha Verma", "iqac@institute.example", "ext 215", "Block A, Room 210", "Quality assurance, NAAC/NIRF data, AQAR, feedback analysis", "Dr. Neha Verma"),
    "Training & Placement": ("Prof. Vikram Malhotra", "tnp@institute.example", "ext 230", "Block B, Ground floor", "Campus recruitment, training programmes and industry connect", "Prof. Vikram Malhotra"),
    "Examination Cell": ("Dr. Sunil Mehta", "exam@institute.example", "ext 140", "Block A, Room 120", "Exam scheduling, question papers, results, revaluation", "Dr. Sunil Mehta"),
    "Academic Administration": ("Ms. Parveen Lamba", "academics@institute.example", "ext 125", "Block A, First floor", "Timetable, academic calendar, regulatory bodies", "Ms. Parveen Lamba"),
    "Library": ("Mr. Ajay Soni", "library@institute.example", "ext 150", "Block B, Ground floor", "Books, journals, e-resources, Shodhganga", "Mr. Ajay Soni"),
    "IT Cell": ("Mr. Harish Tandon", "ithelp@institute.example", "ext 112", "Block A, Room G-12", "ERP, LMS, email, Wi-Fi and hardware support", "Mr. Harish Tandon"),
}
SUBJECTS = {
    "Computer Science": ["Data Structures", "DBMS", "Python Lab", "Operating Systems"],
    "Management Studies": ["Marketing Management", "HRM", "Business Analytics", "Financial Management"],
    "Commerce": ["Accounting", "Taxation", "Business Law", "Cost Accounting"],
    "Mechanical Engineering": ["Thermodynamics", "Machine Design", "CAD Lab", "Fluid Mechanics"],
    "English": ["Literature", "Communication Skills", "Linguistics", "Academic Writing"],
    "Mathematics": ["Calculus", "Linear Algebra", "Statistics", "Numerical Methods"],
}
CLASSES = {"Computer Science": ["BCA-1", "BCA-2", "MCA-1"], "Management Studies": ["MBA-1", "MBA-2", "BBA-3"],
           "Commerce": ["B.Com-1", "B.Com-2", "M.Com-1"], "Mechanical Engineering": ["BE-ME-2", "BE-ME-3"],
           "English": ["BA-1", "BA-2", "MA-1"], "Mathematics": ["BSc-1", "BSc-2"]}
SLOTS = [("09:00", "10:00"), ("10:00", "11:00"), ("11:15", "12:15"), ("12:15", "13:15"),
         ("14:00", "15:00"), ("15:00", "16:00")]


def seed_hub(rnd=None):
    """Sample links, forms, notices, unit contacts and timetables (safe to run on a sample database)."""
    rnd = rnd or random.Random(11)
    hub.init_hub()
    hub.sync_units()
    users = {u["name"]: u for u in db.all_users()}
    hr = next((u for u in users.values() if u["role"] == "HR"), None)
    owner = hr["faculty_id"] if hr else None
    for unit, (head, email, phone, loc, desc, pub) in UNIT_INFO.items():
        hub.save_unit(unit, "Central unit", head, email, phone, loc, desc)
        if pub in users:
            hub.add_publisher(unit, users[pub]["faculty_id"])
    for title, url, cat, unit, desc, tags, pin in SAMPLE_LINKS:
        hub.add_resource(title, cat, unit, url, desc, tags, bool(pin), owner)
    for title, unit, cat, desc, tags in SAMPLE_FORMS:
        body = (f"{title}\n{'=' * len(title)}\n\nName: ____________   Employee ID: ________\n"
                f"Department: ____________   Date: ________\n\n(This is a SAMPLE form file for the demo.)\n").encode()
        hub.add_resource(title, cat, unit, "", desc, tags, False, owner, file=(title.split(" (")[0].replace("/", "-") + ".txt", body))
    now = dt.datetime.now()
    for title, body, cat, unit, pin, days in SAMPLE_NOTICES:
        pub = UNIT_INFO.get(unit, (None,) * 6)[5]
        poster = users[pub]["faculty_id"] if pub in users else owner
        hub.add_notice(title, body, cat, unit, poster, bool(pin))
        with db.conn() as c:   # back-date so the board looks lived-in
            c.execute("UPDATE notices SET posted_at=? WHERE id=(SELECT MAX(id) FROM notices)",
                      ((now - dt.timedelta(days=days, hours=rnd.randint(0, 5))).isoformat(timespec="seconds"),))
    # timetable
    rooms = [f"Room {n}" for n in range(101, 121)] + ["Lab 1", "Lab 2"]
    taken, rows = set(), []
    for u in users.values():
        if u["role"] not in ("Faculty", "HOD"):
            continue
        subj, cls = SUBJECTS[u["department"]], CLASSES[u["department"]]
        for day in hub.DAYS[:5]:
            for st_, en in rnd.sample(SLOTS, 3):
                room = rnd.choice(rooms)
                tries = 0
                while (day, st_, room) in taken and tries < 30:
                    room, tries = rnd.choice(rooms), tries + 1
                taken.add((day, st_, room))
                rows.append((u["faculty_id"], day, st_, en, rnd.choice(subj), rnd.choice(cls), room))
    with db.conn() as c:
        c.execute("DELETE FROM timetable")
        c.executemany("INSERT INTO timetable(faculty_id,day,start_time,end_time,subject,class_name,room) "
                      "VALUES (?,?,?,?,?,?,?)", rows)


def run(reset=False, n_requests=70):
    rnd = random.Random(7)
    if reset and os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()
    today = dt.date.today()
    nowdt = dt.datetime.now()

    # ---- people
    ids = {}
    for dept, names in DEPTS.items():
        ids[dept] = []
        for i, name in enumerate(names):
            role = "HOD" if i == 0 else "Faculty"
            desig = ("Professor & HOD" if i == 0 else
                     "Associate Professor" if name.startswith("Dr.") else "Assistant Professor")
            doj = today - dt.timedelta(days=rnd.randint(300, 6000))
            if dept in ("Commerce", "English") and i == 3:      # two brand-new joiners
                doj = today - dt.timedelta(days=12 if dept == "Commerce" else 30)
                desig = "Assistant Professor"
            mentor = None if i == 0 else ids[dept][0 if i == 1 else 1]
            email = name.split(". ")[1].lower().replace(" ", ".") + "@institute.example"
            fid = db.add_user(name, dept, desig, email, f"98{rnd.randint(10000000, 99999999)}",
                              role, str(doj), mentor)
            ids[dept].append(fid)
    for name, dept, desig, role in STAFF:
        email = name.split(". ")[1].lower().replace(" ", ".") + "@institute.example"
        db.add_user(name, dept, desig, email, f"98{rnd.randint(10000000, 99999999)}", role,
                    str(today - dt.timedelta(days=rnd.randint(400, 5000))), None)

    write_policy_docs()

    # ---- historical requests (chronological so balances & refs stay consistent)
    users = db.all_users()
    requesters = [u for u in users if u["role"] in ("Faculty", "HOD")]
    times = sorted(nowdt - dt.timedelta(days=rnd.uniform(0, 75)) for _ in range(n_requests))
    for created in times:
        rtype = rnd.choices(list(db.WORKFLOWS), [40, 20, 15, 10, 15])[0]
        u = rnd.choice(requesters)
        details, files = _make_request_details(rnd, rtype, created.date())
        try:
            ref = db.create_request(u["faculty_id"], rtype, details, files, ts=_iso(created))
        except ValueError:
            continue
        age = (nowdt - created).days
        t = created
        r = db.get_request(ref)
        while r["status"] == "In Progress":
            if rnd.random() < max(0.05, 0.6 - age / 25):
                break                                    # newer requests are still pending
            t = min(nowdt, t + dt.timedelta(hours=rnd.uniform(2, 36)))
            need = db.WORKFLOWS[rtype]["roles"][r["stage_idx"]]
            pool = [x for x in users if x["role"] == need and x["faculty_id"] != u["faculty_id"]
                    and (need != "HOD" or x["department"] == u["department"])]
            if not pool:
                break
            actor = rnd.choice(pool)
            if rnd.random() < 0.08:
                db.act(ref, actor["faculty_id"], "Reject", rnd.choice(REJECT_NOTES[rtype]), ts=_iso(t))
            else:
                db.act(ref, actor["faculty_id"], "Approve", rnd.choice(APPROVE_NOTES), ts=_iso(t))
            r = db.get_request(ref)
    seed_hub(rnd)


if __name__ == "__main__":
    if "--hub" in sys.argv:          # add only the Resource Hub sample data to an existing sample database
        seed_hub()
        print("Resource Hub sample data added.")
        sys.exit(0)
    run(reset="--reset" in sys.argv)
    print("Sample data created in", db.DB_PATH)
