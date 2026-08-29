import os
from functools import wraps
from datetime import datetime, timedelta

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session
)

from database import get_connection, create_database
from bizflow_operator import ask_operator


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "bizflow-local-secret-change-me")

OPERATOR_PASSWORD = os.getenv("OPERATOR_PASSWORD", "bizflow-local")

PIPELINE_STAGES = [
    "New Lead",
    "Follow Up",
    "Contacted",
    "Interested",
    "Proposal",
    "Won",
    "Lost"
]


# =========================================================
# AUTH
# =========================================================

def operator_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("operator_logged_in"):
            return redirect(url_for("operator_login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/operator/login", methods=["GET", "POST"])
def operator_login():
    error = None

    if request.method == "POST":
        password = request.form.get("password", "")

        if password == OPERATOR_PASSWORD:
            session["operator_logged_in"] = True
            return redirect(url_for("dashboard"))

        error = "Incorrect password."

    return render_template(
        "operator_login.html",
        error=error
    )


@app.route("/operator/logout")
def operator_logout():
    session.clear()
    return redirect(url_for("home"))


# =========================================================
# ACTIVITY
# =========================================================

def log_activity(action, details):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO activity (action, details) VALUES (?, ?)",
        (action, details)
    )

    conn.commit()
    conn.close()


# =========================================================
# OPERATOR STATUS
# =========================================================

def ensure_operator_status_table():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS operator_status (
            id INTEGER PRIMARY KEY,
            status TEXT,
            last_heartbeat TEXT,
            last_cycle_started TEXT,
            last_cycle_completed TEXT,
            last_error TEXT
        )
    """)

    conn.commit()
    conn.close()


def get_time_ago(value):
    if not value:
        return "Never connected"

    diff = datetime.now() - value
    seconds = max(0, int(diff.total_seconds()))

    if seconds < 60:
        return "Just now"

    mins = seconds // 60

    if mins < 60:
        return "1 minute ago" if mins == 1 else f"{mins} minutes ago"

    hours = mins // 60

    if hours < 24:
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"

    days = hours // 24

    return "1 day ago" if days == 1 else f"{days} days ago"


def get_operator_status():
    ensure_operator_status_table()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            status,
            last_heartbeat,
            last_cycle_started,
            last_cycle_completed,
            last_error
        FROM operator_status
        WHERE id = 1
    """)

    row = cur.fetchone()
    conn.close()

    if not row:
        return {
            "status": "Offline",
            "status_class": "offline",
            "last_heartbeat": None,
            "last_cycle_started": None,
            "last_cycle_completed": None,
            "last_error": None,
            "last_seen_text": "Never connected"
        }

    stored, heartbeat, started, completed, error = row

    heartbeat_dt = None

    if heartbeat:
        try:
            heartbeat_dt = datetime.fromisoformat(heartbeat)
        except ValueError:
            pass

    status = stored or "Offline"
    status_class = "online"

    if stored == "Stopped":
        status, status_class = "Offline", "offline"

    elif stored == "Error":
        status, status_class = "Error", "error"

    elif heartbeat_dt and (
        datetime.now() - heartbeat_dt
        > timedelta(minutes=75)
    ):
        status, status_class = "Offline", "offline"

    elif stored == "Running":
        status, status_class = "Running", "running"

    elif heartbeat_dt:
        status, status_class = "Online", "online"

    else:
        status, status_class = "Offline", "offline"

    return {
        "status": status,
        "status_class": status_class,
        "last_heartbeat": heartbeat,
        "last_cycle_started": started,
        "last_cycle_completed": completed,
        "last_error": error,
        "last_seen_text": get_time_ago(heartbeat_dt)
    }


# =========================================================
# GLOBAL OPERATOR TEMPLATE DATA
# =========================================================

@app.context_processor
def inject_global_data():
    # Public pages do not need database-heavy operator navigation counts.
    if not request.path.startswith("/operator") and request.endpoint in {
        "home",
        "growth_system",
        "how_it_works",
        "pricing",
        "contact_page",
        "operator_login",
        "operator_logout",
        "static"
    }:
        return {}

    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*) FROM tasks WHERE status != 'Completed'"
        )
        tasks = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM content_queue WHERE status='Pending Approval'"
        )
        content_approvals = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM leads WHERE followup_status='Pending Approval'"
        )
        lead_approvals = cur.fetchone()[0]

        cur.execute("""
            SELECT next_followup, pipeline_stage
            FROM leads
            WHERE next_followup IS NOT NULL
            AND next_followup != ''
        """)
        followups = cur.fetchall()

        try:
            cur.execute("""
                SELECT COUNT(*)
                FROM prospects
                WHERE status='Qualified'
                AND outreach_status='Pending Approval'
            """)
            prospects = cur.fetchone()[0]
        except Exception:
            prospects = 0

        conn.close()

        overdue = 0
        now = datetime.now()

        for value, stage in followups:
            if stage in ("Won", "Lost"):
                continue

            try:
                if datetime.fromisoformat(value) <= now:
                    overdue += 1
            except ValueError:
                pass

        return {
            "nav_task_count": tasks,
            "nav_approval_count": content_approvals + lead_approvals,
            "nav_overdue_count": overdue,
            "nav_prospect_count": prospects,
            "operator": get_operator_status()
        }

    except Exception:
        return {
            "nav_task_count": 0,
            "nav_approval_count": 0,
            "nav_overdue_count": 0,
            "nav_prospect_count": 0,
            "operator": {
                "status": "Offline",
                "status_class": "offline",
                "last_seen_text": "Unavailable"
            }
        }


# =========================================================
# GENERIC DATABASE HELPERS
# =========================================================

def fetchall(sql, params=()):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def fetchone(sql, params=()):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    return row


# =========================================================
# PUBLIC BIZFLOW SA WEBSITE
# =========================================================

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/growth-system")
def growth_system():
    return render_template("growth_system.html")


@app.route("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


@app.route("/contact", methods=["GET", "POST"])
def contact_page():
    if request.method == "GET":
        return render_template(
            "contact.html",
            success=False
        )

    name = request.form.get("name")
    email = request.form.get("email")
    phone = request.form.get("phone")
    business_name = request.form.get("business_name")
    message = request.form.get("message")

    if not name:
        return render_template(
            "contact.html",
            success=False,
            error="Please enter your name."
        )

    notes = message or ""

    if business_name:
        notes = (
            f"Business: {business_name}\n\n"
            f"{notes}"
        ).strip()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO leads (
            name,
            email,
            phone,
            source,
            status,
            followup_status,
            pipeline_stage,
            lead_value,
            notes,
            lead_score
        )
        VALUES (
            ?, ?, ?,
            'Website',
            'New',
            'Not Drafted',
            'New Lead',
            0,
            ?,
            20
        )
    """, (
        name,
        email,
        phone,
        notes
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Website Lead",
        f"New Growth System enquiry from {name}."
    )

    return render_template(
        "contact.html",
        success=True
    )


# =========================================================
# OPERATOR DATA HELPERS
# =========================================================

def get_leads():
    return fetchall("""
        SELECT
            id,name,email,phone,source,status,created_at,
            followup_draft,followup_status,pipeline_stage,
            lead_value,next_followup,notes,created_at,lead_score
        FROM leads
        ORDER BY id DESC
    """)


def get_lead(lead_id):
    return fetchone("""
        SELECT
            id,name,email,phone,source,status,created_at,
            followup_draft,followup_status,pipeline_stage,
            lead_value,next_followup,notes,created_at,lead_score
        FROM leads
        WHERE id=?
    """, (lead_id,))


def get_tasks():
    return fetchall("""
        SELECT
            id,title,description,status,created_at,priority,due_date
        FROM tasks
        ORDER BY
            CASE priority
                WHEN 'Urgent' THEN 1
                WHEN 'High' THEN 2
                WHEN 'Normal' THEN 3
                ELSE 4
            END,
            id DESC
    """)


def get_customers():
    return fetchall("""
        SELECT id,name,email,phone,created_at
        FROM customers
        ORDER BY id DESC
    """)


def get_content():
    return fetchall("""
        SELECT
            id,title,content,status,platform,scheduled_for,created_at
        FROM content_queue
        ORDER BY id DESC
    """)


def get_activity(limit=50):
    return fetchall("""
        SELECT action,details,created_at
        FROM activity
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))


def get_pipeline_counts():
    return {
        stage: fetchone(
            "SELECT COUNT(*) FROM leads WHERE pipeline_stage=?",
            (stage,)
        )[0]
        for stage in PIPELINE_STAGES
    }


def get_pipeline_value():
    return fetchone("""
        SELECT COALESCE(SUM(lead_value),0)
        FROM leads
        WHERE pipeline_stage NOT IN ('Won','Lost')
    """)[0]


def get_won_value():
    return fetchone("""
        SELECT COALESCE(SUM(lead_value),0)
        FROM leads
        WHERE pipeline_stage='Won'
    """)[0]


def get_hot_leads():
    return fetchall("""
        SELECT
            id,name,email,phone,source,status,created_at,
            followup_draft,followup_status,pipeline_stage,
            lead_value,next_followup,notes,created_at,lead_score
        FROM leads
        WHERE lead_score>=70
        AND pipeline_stage NOT IN ('Won','Lost')
        ORDER BY lead_score DESC,lead_value DESC
        LIMIT 5
    """)


def get_overdue_leads():
    now = datetime.now()
    output = []

    for lead in get_leads():
        if not lead[11] or lead[9] in ("Won", "Lost"):
            continue

        try:
            if datetime.fromisoformat(lead[11]) <= now:
                output.append(lead)
        except ValueError:
            pass

    return output


def render_dashboard(priorities=None):
    task_count = fetchone(
        "SELECT COUNT(*) FROM tasks WHERE status!='Completed'"
    )[0]

    hot_count = fetchone("""
        SELECT COUNT(*)
        FROM leads
        WHERE lead_score>=70
        AND pipeline_stage NOT IN ('Won','Lost')
    """)[0]

    customer_count = fetchone(
        "SELECT COUNT(*) FROM customers"
    )[0]

    return render_template(
        "dashboard.html",
        task_count=task_count,
        hot_lead_count=hot_count,
        customer_count=customer_count,
        pipeline_value=get_pipeline_value(),
        won_value=get_won_value(),
        hot_leads=get_hot_leads(),
        overdue_leads=get_overdue_leads(),
        activity=get_activity(10),
        priorities=priorities
    )


# =========================================================
# PRIVATE OPERATOR
# =========================================================

@app.route("/operator")
@operator_required
def dashboard():
    return render_dashboard()


@app.route("/operator/daily-priorities", methods=["POST"])
@operator_required
def daily_priorities():
    hot = get_hot_leads()
    tasks = [t for t in get_tasks() if t[3] != "Completed"]
    overdue = get_overdue_leads()

    prompt = (
        "You are BizFlow Operator. Create today's business priorities "
        "for BizFlow SA.\nHOT LEADS:\n"
        + "\n".join([
            f"- {lead[1]} | Stage {lead[9]} | "
            f"Score {lead[14]} | Value R{lead[10] or 0}"
            for lead in hot
        ])
        + "\nOPEN TASKS:\n"
        + "\n".join([
            f"- {task[1]} | Priority {task[5] or 'Normal'}"
            for task in tasks[:10]
        ])
        + "\nOVERDUE FOLLOW-UPS:\n"
        + "\n".join([
            f"- {lead[1]} | Due {lead[11]}"
            for lead in overdue
        ])
        + f"\nACTIVE PIPELINE: R{get_pipeline_value():.2f}"
        + f"\nWON REVENUE: R{get_won_value():.2f}"
        + "\nMaximum 6 concise practical priorities."
    )

    try:
        priorities = ask_operator(prompt)
        log_activity(
            "Daily Priorities",
            "AI generated today's business priorities."
        )
    except Exception as error:
        priorities = f"Unable to generate priorities: {error}"
        log_activity("Operator Error", str(error))

    return render_dashboard(priorities)


@app.route("/operator/leads")
@operator_required
def leads_page():
    return render_template(
        "leads.html",
        leads=get_leads(),
        pipeline_counts=get_pipeline_counts()
    )


@app.route("/operator/lead/<int:lead_id>")
@operator_required
def lead_detail(lead_id):
    lead = get_lead(lead_id)

    if not lead:
        return redirect(url_for("leads_page"))

    return render_template(
        "lead_detail.html",
        lead=lead,
        stages=PIPELINE_STAGES
    )


@app.route("/operator/lead/add", methods=["POST"])
@operator_required
def add_lead():
    values = (
        request.form.get("name"),
        request.form.get("email"),
        request.form.get("phone"),
        request.form.get("source"),
        request.form.get("lead_value") or 0
    )

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO leads (
            name,email,phone,source,status,followup_status,
            pipeline_stage,lead_value,lead_score
        )
        VALUES (
            ?,?,?,?,
            'New','Not Drafted','New Lead',?,20
        )
    """, values)

    conn.commit()
    conn.close()

    log_activity(
        "Lead Added",
        f"Lead added: {values[0]}"
    )

    return redirect(url_for("leads_page"))


@app.route("/operator/lead/<int:lead_id>/update", methods=["POST"])
@operator_required
def update_lead(lead_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE leads
        SET
            notes=?,
            lead_value=?,
            next_followup=?
        WHERE id=?
    """, (
        request.form.get("notes"),
        request.form.get("lead_value") or 0,
        request.form.get("next_followup"),
        lead_id
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Lead Updated",
        f"Lead #{lead_id} updated."
    )

    return redirect(
        url_for("lead_detail", lead_id=lead_id)
    )


@app.route("/operator/lead/<int:lead_id>/stage/<stage>", methods=["POST"])
@operator_required
def move_lead_stage(lead_id, stage):
    if stage not in PIPELINE_STAGES:
        return redirect(
            url_for("lead_detail", lead_id=lead_id)
        )

    score = {
        "New Lead": 20,
        "Follow Up": 30,
        "Contacted": 40,
        "Interested": 65,
        "Proposal": 85,
        "Won": 100,
        "Lost": 0
    }[stage]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE leads
        SET pipeline_stage=?, lead_score=?
        WHERE id=?
    """, (
        stage,
        score,
        lead_id
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Pipeline Updated",
        f"Lead #{lead_id} moved to {stage}."
    )

    return redirect(
        url_for("lead_detail", lead_id=lead_id)
    )


@app.route("/operator/lead/<int:lead_id>/approve-followup", methods=["POST"])
@operator_required
def approve_followup(lead_id):
    conn = get_connection()

    conn.execute("""
        UPDATE leads
        SET followup_status='Approved'
        WHERE id=?
    """, (lead_id,))

    conn.commit()
    conn.close()

    log_activity(
        "Follow-Up Approved",
        f"Follow-up approved for lead #{lead_id}."
    )

    return redirect(
        request.referrer
        or url_for("leads_page")
    )


@app.route("/operator/lead/<int:lead_id>/regenerate-followup", methods=["POST"])
@operator_required
def regenerate_followup(lead_id):
    conn = get_connection()

    conn.execute("""
        UPDATE leads
        SET
            followup_draft=NULL,
            followup_status='Not Drafted',
            status='Follow Up Required',
            pipeline_stage='Follow Up'
        WHERE id=?
    """, (lead_id,))

    conn.commit()
    conn.close()

    log_activity(
        "Follow-Up Regeneration Requested",
        f"Lead #{lead_id} queued for a new follow-up."
    )

    return redirect(
        request.referrer
        or url_for("leads_page")
    )


@app.route("/operator/lead/<int:lead_id>/contacted", methods=["POST"])
@operator_required
def mark_lead_contacted(lead_id):
    conn = get_connection()

    conn.execute("""
        UPDATE leads
        SET
            status='Contacted',
            pipeline_stage='Contacted',
            lead_score=40
        WHERE id=?
    """, (lead_id,))

    conn.commit()
    conn.close()

    log_activity(
        "Lead Contacted",
        f"Lead #{lead_id} marked as contacted."
    )

    return redirect(
        request.referrer
        or url_for("leads_page")
    )


@app.route("/operator/lead/<int:lead_id>/convert", methods=["POST"])
@operator_required
def convert_lead(lead_id):
    lead = fetchone(
        "SELECT name,email,phone FROM leads WHERE id=?",
        (lead_id,)
    )

    if not lead:
        return redirect(url_for("leads_page"))

    conn = get_connection()
    cur = conn.cursor()

    exists = 0

    if lead[1]:
        cur.execute(
            "SELECT COUNT(*) FROM customers WHERE email=?",
            (lead[1],)
        )
        exists = cur.fetchone()[0]

    if exists == 0:
        cur.execute("""
            INSERT INTO customers (name,email,phone)
            VALUES (?,?,?)
        """, lead)

    cur.execute("""
        UPDATE leads
        SET
            status='Converted',
            pipeline_stage='Won',
            lead_score=100
        WHERE id=?
    """, (lead_id,))

    conn.commit()
    conn.close()

    log_activity(
        "Lead Won",
        f"Lead #{lead_id} converted to customer."
    )

    return redirect(url_for("leads_page"))


# =========================================================
# PROSPECTS
# =========================================================

def get_prospects():
    try:
        return fetchall("""
            SELECT
                id,business_name,industry,city,address,website,phone,maps_url,
                status,prospect_score,fit_reason,outreach_draft,outreach_status,
                converted_lead_id,created_at
            FROM prospects
            ORDER BY prospect_score DESC,id DESC
        """)
    except Exception:
        return []


@app.route("/operator/prospects")
@operator_required
def prospects_page():
    return render_template(
        "prospects.html",
        prospects=get_prospects()
    )


@app.route("/operator/prospect/<int:prospect_id>/approve", methods=["POST"])
@operator_required
def approve_prospect_outreach(prospect_id):
    conn = get_connection()

    conn.execute("""
        UPDATE prospects
        SET outreach_status='Approved'
        WHERE id=?
    """, (prospect_id,))

    conn.commit()
    conn.close()

    log_activity(
        "Prospect Outreach Approved",
        f"Outreach approved for prospect #{prospect_id}."
    )

    return redirect(url_for("prospects_page"))


@app.route("/operator/prospect/<int:prospect_id>/reject", methods=["POST"])
@operator_required
def reject_prospect(prospect_id):
    conn = get_connection()

    conn.execute("""
        UPDATE prospects
        SET
            outreach_status='Rejected',
            status='Rejected'
        WHERE id=?
    """, (prospect_id,))

    conn.commit()
    conn.close()

    log_activity(
        "Prospect Rejected",
        f"Prospect #{prospect_id} rejected."
    )

    return redirect(url_for("prospects_page"))


@app.route("/operator/prospect/<int:prospect_id>/convert", methods=["POST"])
@operator_required
def convert_prospect_to_lead(prospect_id):
    prospect = fetchone("""
        SELECT
            business_name,phone,industry,city,
            fit_reason,converted_lead_id
        FROM prospects
        WHERE id=?
    """, (prospect_id,))

    if not prospect or prospect[5]:
        return redirect(url_for("prospects_page"))

    name, phone, industry, city, reason, _ = prospect

    notes = (
        f"Prospected by BizFlow. "
        f"Industry: {industry or 'Unknown'}. "
        f"City: {city or 'Unknown'}. "
        f"Fit: {reason or ''}"
    )

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO leads (
            name,email,phone,source,status,
            followup_status,pipeline_stage,
            lead_value,notes,lead_score
        )
        VALUES (
            ?,NULL,?,
            'Prospecting',
            'New',
            'Not Drafted',
            'New Lead',
            0,
            ?,
            60
        )
    """, (
        name,
        phone,
        notes
    ))

    conn.commit()
    conn.close()

    lead = fetchone("""
        SELECT id
        FROM leads
        WHERE name=?
        AND source='Prospecting'
        ORDER BY id DESC
        LIMIT 1
    """, (name,))

    lead_id = lead[0] if lead else None

    conn = get_connection()

    conn.execute("""
        UPDATE prospects
        SET
            status='Converted',
            converted_lead_id=?
        WHERE id=?
    """, (
        lead_id,
        prospect_id
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Prospect Converted",
        f"Prospect #{prospect_id} converted into a BizFlow lead."
    )

    return redirect(url_for("prospects_page"))


# =========================================================
# CUSTOMERS / TASKS / CONTENT / APPROVALS / ACTIVITY
# =========================================================

@app.route("/operator/customers")
@operator_required
def customers_page():
    return render_template(
        "customers.html",
        customers=get_customers()
    )


@app.route("/operator/tasks")
@operator_required
def tasks_page():
    return render_template(
        "tasks.html",
        tasks=get_tasks()
    )


@app.route("/operator/task/<int:task_id>/complete", methods=["POST"])
@operator_required
def complete_task(task_id):
    conn = get_connection()

    conn.execute("""
        UPDATE tasks
        SET status='Completed'
        WHERE id=?
    """, (task_id,))

    conn.commit()
    conn.close()

    log_activity(
        "Task Completed",
        f"Task #{task_id} completed."
    )

    return redirect(url_for("tasks_page"))


@app.route("/operator/content")
@operator_required
def content_page():
    return render_template(
        "content.html",
        content=get_content()
    )


@app.route("/operator/generate-post", methods=["POST"])
@operator_required
def generate_post():
    platform = request.form.get(
        "platform",
        "Instagram"
    )

    topic = request.form.get(
        "topic",
        "BizFlow SA"
    )

    try:
        post = ask_operator(
            f"""
Create one strong {platform} marketing post for BizFlow SA.

BizFlow SA is an AI-powered Small Business Growth System
for South African small businesses.

Topic:
{topic}

Focus on helping businesses:
- find more opportunities
- follow up faster
- save time
- automate repetitive work
- grow sales and revenue

Use a strong hook.
Keep it professional, friendly and useful.
Use a clear call to action.
Do not make unrealistic income claims.
Return only the post.
"""
        )

    except Exception as error:
        log_activity(
            "Content Error",
            str(error)
        )

        return redirect(
            url_for("content_page")
        )

    conn = get_connection()

    conn.execute("""
        INSERT INTO content_queue (
            title,content,status,platform
        )
        VALUES (?,?,?,?)
    """, (
        f"{platform} Marketing Post",
        post,
        "Pending Approval",
        platform
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Content Generated",
        f"Generated {platform} content for {topic}."
    )

    return redirect(
        url_for("content_page")
    )


@app.route("/operator/content/<int:content_id>/approve", methods=["POST"])
@operator_required
def approve_content(content_id):
    conn = get_connection()

    conn.execute("""
        UPDATE content_queue
        SET status='Approved'
        WHERE id=?
    """, (content_id,))

    conn.commit()
    conn.close()

    log_activity(
        "Content Approved",
        f"Content #{content_id} approved."
    )

    return redirect(
        request.referrer
        or url_for("content_page")
    )


@app.route("/operator/content/<int:content_id>/reject", methods=["POST"])
@operator_required
def reject_content(content_id):
    conn = get_connection()

    conn.execute("""
        UPDATE content_queue
        SET status='Rejected'
        WHERE id=?
    """, (content_id,))

    conn.commit()
    conn.close()

    log_activity(
        "Content Rejected",
        f"Content #{content_id} rejected."
    )

    return redirect(
        request.referrer
        or url_for("content_page")
    )


@app.route("/operator/content/<int:content_id>/schedule", methods=["POST"])
@operator_required
def schedule_content(content_id):
    scheduled = request.form.get(
        "scheduled_for"
    )

    if not scheduled:
        return redirect(
            url_for("content_page")
        )

    conn = get_connection()

    conn.execute("""
        UPDATE content_queue
        SET
            status='Scheduled',
            scheduled_for=?
        WHERE id=?
    """, (
        scheduled,
        content_id
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Content Scheduled",
        f"Content #{content_id} scheduled for {scheduled}."
    )

    return redirect(
        url_for("content_page")
    )


@app.route("/operator/approvals")
@operator_required
def approvals_page():
    return render_template(
        "approvals.html",
        approvals=[
            item
            for item in get_content()
            if item[3] == "Pending Approval"
        ],
        lead_approvals=[
            lead
            for lead in get_leads()
            if lead[8] == "Pending Approval"
        ]
    )


@app.route("/operator/activity")
@operator_required
def activity_page():
    return render_template(
        "activity.html",
        activity=get_activity(100)
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    create_database()
    ensure_operator_status_table()

    app.run(
        debug=True
    )
