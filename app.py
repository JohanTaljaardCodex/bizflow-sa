from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for

from database import get_connection, create_database
from bizflow_operator import ask_operator


app = Flask(__name__)


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
# DATABASE HELPERS
# =========================================================

def ensure_operator_status_table():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
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


def log_activity(action, details):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO activity (
            action,
            details
        )
        VALUES (?, ?)
    """, (
        action,
        details
    ))

    conn.commit()
    conn.close()


# =========================================================
# OPERATOR STATUS
# =========================================================

def get_time_ago(date_value):
    if not date_value:
        return "Never connected"

    difference = datetime.now() - date_value
    seconds = int(difference.total_seconds())

    if seconds < 60:
        return "Just now"

    minutes = seconds // 60

    if minutes < 60:
        if minutes == 1:
            return "1 minute ago"

        return f"{minutes} minutes ago"

    hours = minutes // 60

    if hours < 24:
        if hours == 1:
            return "1 hour ago"

        return f"{hours} hours ago"

    days = hours // 24

    if days == 1:
        return "1 day ago"

    return f"{days} days ago"


def get_operator_status():
    ensure_operator_status_table()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            status,
            last_heartbeat,
            last_cycle_started,
            last_cycle_completed,
            last_error
        FROM operator_status
        WHERE id = 1
    """)

    row = cursor.fetchone()

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

    stored_status = row[0] or "Offline"
    last_heartbeat = row[1]
    last_cycle_started = row[2]
    last_cycle_completed = row[3]
    last_error = row[4]

    heartbeat_date = None

    if last_heartbeat:
        try:
            heartbeat_date = datetime.fromisoformat(
                last_heartbeat
            )
        except ValueError:
            pass

    current_status = stored_status
    status_class = "online"

    if stored_status == "Stopped":

        current_status = "Offline"
        status_class = "offline"

    elif stored_status == "Error":

        current_status = "Error"
        status_class = "error"

    elif heartbeat_date:

        age = datetime.now() - heartbeat_date

        if age > timedelta(minutes=75):

            current_status = "Offline"
            status_class = "offline"

        elif stored_status == "Running":

            current_status = "Running"
            status_class = "running"

        else:

            current_status = "Online"
            status_class = "online"

    else:

        current_status = "Offline"
        status_class = "offline"

    return {
        "status": current_status,
        "status_class": status_class,
        "last_heartbeat": last_heartbeat,
        "last_cycle_started": last_cycle_started,
        "last_cycle_completed": last_cycle_completed,
        "last_error": last_error,
        "last_seen_text": get_time_ago(
            heartbeat_date
        )
    }


# =========================================================
# GLOBAL TEMPLATE DATA
# =========================================================

@app.context_processor
def inject_global_data():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE status != 'Completed'
    """)

    nav_task_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM content_queue
        WHERE status = 'Pending Approval'
    """)

    content_approvals = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM leads
        WHERE followup_status = 'Pending Approval'
    """)

    lead_approvals = cursor.fetchone()[0]

    nav_approval_count = (
        content_approvals
        + lead_approvals
    )

    cursor.execute("""
        SELECT
            next_followup,
            pipeline_stage
        FROM leads
        WHERE next_followup IS NOT NULL
        AND next_followup != ''
    """)

    followups = cursor.fetchall()

    conn.close()

    nav_overdue_count = 0
    now = datetime.now()

    for followup in followups:

        followup_value = followup[0]
        stage = followup[1]

        if stage in (
            "Won",
            "Lost"
        ):
            continue

        try:
            followup_date = datetime.fromisoformat(
                followup_value
            )

            if followup_date <= now:
                nav_overdue_count += 1

        except ValueError:
            continue

    return {
        "nav_task_count":
            nav_task_count,

        "nav_approval_count":
            nav_approval_count,

        "nav_overdue_count":
            nav_overdue_count,

        "operator":
            get_operator_status()
    }


# =========================================================
# DATA HELPERS
# =========================================================

def get_leads():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            email,
            phone,
            source,
            status,
            created_at,
            followup_draft,
            followup_status,
            pipeline_stage,
            lead_value,
            next_followup,
            notes,
            created_at,
            lead_score
        FROM leads
        ORDER BY id DESC
    """)

    rows = cursor.fetchall()

    conn.close()

    return rows


def get_lead(lead_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            email,
            phone,
            source,
            status,
            created_at,
            followup_draft,
            followup_status,
            pipeline_stage,
            lead_value,
            next_followup,
            notes,
            created_at,
            lead_score
        FROM leads
        WHERE id = ?
    """, (
        lead_id,
    ))

    row = cursor.fetchone()

    conn.close()

    return row


def get_tasks():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            title,
            description,
            status,
            created_at,
            priority,
            due_date
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

    rows = cursor.fetchall()

    conn.close()

    return rows


def get_customers():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            email,
            phone,
            created_at
        FROM customers
        ORDER BY id DESC
    """)

    rows = cursor.fetchall()

    conn.close()

    return rows


def get_content():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            title,
            content,
            status,
            platform,
            scheduled_for,
            created_at
        FROM content_queue
        ORDER BY id DESC
    """)

    rows = cursor.fetchall()

    conn.close()

    return rows


def get_activity(limit=50):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            action,
            details,
            created_at
        FROM activity
        ORDER BY id DESC
        LIMIT ?
    """, (
        limit,
    ))

    rows = cursor.fetchall()

    conn.close()

    return rows


def get_pipeline_counts():
    conn = get_connection()
    cursor = conn.cursor()

    counts = {}

    for stage in PIPELINE_STAGES:

        cursor.execute("""
            SELECT COUNT(*)
            FROM leads
            WHERE pipeline_stage = ?
        """, (
            stage,
        ))

        counts[stage] = cursor.fetchone()[0]

    conn.close()

    return counts


def get_pipeline_value():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COALESCE(
            SUM(lead_value),
            0
        )
        FROM leads
        WHERE pipeline_stage NOT IN (
            'Won',
            'Lost'
        )
    """)

    value = cursor.fetchone()[0]

    conn.close()

    return value


def get_won_value():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COALESCE(
            SUM(lead_value),
            0
        )
        FROM leads
        WHERE pipeline_stage = 'Won'
    """)

    value = cursor.fetchone()[0]

    conn.close()

    return value


def get_hot_leads():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            email,
            phone,
            source,
            status,
            created_at,
            followup_draft,
            followup_status,
            pipeline_stage,
            lead_value,
            next_followup,
            notes,
            created_at,
            lead_score
        FROM leads
        WHERE lead_score >= 70
        AND pipeline_stage NOT IN (
            'Won',
            'Lost'
        )
        ORDER BY
            lead_score DESC,
            lead_value DESC
        LIMIT 5
    """)

    rows = cursor.fetchall()

    conn.close()

    return rows


def get_overdue_leads():
    leads = get_leads()

    overdue = []
    now = datetime.now()

    for lead in leads:

        next_followup = lead[11]
        stage = lead[9]

        if not next_followup:
            continue

        if stage in (
            "Won",
            "Lost"
        ):
            continue

        try:

            followup_date = datetime.fromisoformat(
                next_followup
            )

            if followup_date <= now:
                overdue.append(
                    lead
                )

        except ValueError:
            continue

    return overdue


def get_dashboard_counts():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE status != 'Completed'
    """)

    task_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM leads
        WHERE lead_score >= 70
        AND pipeline_stage NOT IN (
            'Won',
            'Lost'
        )
    """)

    hot_lead_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM customers
    """)

    customer_count = cursor.fetchone()[0]

    conn.close()

    return (
        task_count,
        hot_lead_count,
        customer_count
    )


def render_dashboard(priorities=None):
    (
        task_count,
        hot_lead_count,
        customer_count
    ) = get_dashboard_counts()

    return render_template(
        "dashboard.html",

        task_count=
            task_count,

        hot_lead_count=
            hot_lead_count,

        customer_count=
            customer_count,

        pipeline_value=
            get_pipeline_value(),

        won_value=
            get_won_value(),

        hot_leads=
            get_hot_leads(),

        overdue_leads=
            get_overdue_leads(),

        activity=
            get_activity(10),

        priorities=
            priorities
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/")
def dashboard():
    return render_dashboard()


# =========================================================
# DAILY PRIORITIES
# =========================================================

@app.route(
    "/daily-priorities",
    methods=["POST"]
)
def daily_priorities():
    hot_leads = get_hot_leads()

    open_tasks = [
        task
        for task in get_tasks()
        if task[3] != "Completed"
    ]

    overdue_leads = get_overdue_leads()

    lead_summary = "\n".join([
        (
            f"- {lead[1]} | "
            f"Stage: {lead[9]} | "
            f"Score: {lead[14]} | "
            f"Value: R{lead[10] or 0}"
        )
        for lead in hot_leads
    ])

    task_summary = "\n".join([
        (
            f"- {task[1]} | "
            f"Priority: "
            f"{task[5] or 'Normal'}"
        )
        for task
        in open_tasks[:10]
    ])

    overdue_summary = "\n".join([
        (
            f"- {lead[1]} | "
            f"Follow-up due: "
            f"{lead[11]}"
        )
        for lead
        in overdue_leads
    ])

    prompt = f"""
You are BizFlow Operator.

Create today's business priorities for BizFlow SA.

HOT LEADS:
{lead_summary or "None"}

OPEN TASKS:
{task_summary or "None"}

OVERDUE FOLLOW-UPS:
{overdue_summary or "None"}

ACTIVE PIPELINE:
R{get_pipeline_value():.2f}

WON REVENUE:
R{get_won_value():.2f}

Create a short practical priority list.

Focus on:
- Sales
- Revenue
- Follow-ups
- Marketing
- Urgent tasks

Maximum 6 priorities.
"""

    try:

        priorities = ask_operator(
            prompt
        )

        log_activity(
            "Daily Priorities",
            (
                "AI generated today's "
                "business priorities."
            )
        )

    except Exception as error:

        priorities = (
            "Unable to generate "
            f"priorities: {error}"
        )

        log_activity(
            "Operator Error",
            str(error)
        )

    return render_dashboard(
        priorities=priorities
    )


# =========================================================
# LEADS
# =========================================================

@app.route("/leads")
def leads_page():
    return render_template(
        "leads.html",

        leads=
            get_leads(),

        pipeline_counts=
            get_pipeline_counts()
    )


@app.route(
    "/lead/<int:lead_id>"
)
def lead_detail(
    lead_id
):
    lead = get_lead(
        lead_id
    )

    if not lead:

        return redirect(
            url_for(
                "leads_page"
            )
        )

    return render_template(
        "lead_detail.html",

        lead=
            lead,

        stages=
            PIPELINE_STAGES
    )


@app.route(
    "/lead/add",
    methods=["POST"]
)
def add_lead():
    name = request.form.get(
        "name"
    )

    email = request.form.get(
        "email"
    )

    phone = request.form.get(
        "phone"
    )

    source = request.form.get(
        "source"
    )

    lead_value = (
        request.form.get(
            "lead_value"
        )
        or 0
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO leads (
            name,
            email,
            phone,
            source,
            status,
            followup_status,
            pipeline_stage,
            lead_value,
            lead_score
        )
        VALUES (
            ?, ?, ?, ?,
            'New',
            'Not Drafted',
            'New Lead',
            ?,
            20
        )
    """, (
        name,
        email,
        phone,
        source,
        lead_value
    ))

    lead_id = (
        cursor.lastrowid
    )

    conn.commit()
    conn.close()

    log_activity(
        "Lead Added",
        (
            f"Lead #{lead_id} "
            f"added: {name}"
        )
    )

    return redirect(
        url_for(
            "leads_page"
        )
    )


# =========================================================
# CONTACT FORM
# =========================================================

@app.route(
    "/contact",
    methods=[
        "GET",
        "POST"
    ]
)
def contact_page():

    if request.method == "GET":

        return render_template(
            "contact.html",
            success=False
        )

    name = request.form.get(
        "name"
    )

    email = request.form.get(
        "email"
    )

    phone = request.form.get(
        "phone"
    )

    message = request.form.get(
        "message"
    )

    if not name:

        return render_template(
            "contact.html",
            success=False
        )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
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
        message
    ))

    lead_id = (
        cursor.lastrowid
    )

    conn.commit()
    conn.close()

    log_activity(
        "Website Lead",
        (
            f"New website lead "
            f"#{lead_id}: {name}"
        )
    )

    print(
        f"Website lead created: "
        f"#{lead_id} - {name}"
    )

    return render_template(
        "contact.html",
        success=True
    )


# =========================================================
# UPDATE LEAD
# =========================================================

@app.route(
    "/lead/<int:lead_id>/update",
    methods=["POST"]
)
def update_lead(
    lead_id
):
    notes = request.form.get(
        "notes"
    )

    lead_value = (
        request.form.get(
            "lead_value"
        )
        or 0
    )

    next_followup = (
        request.form.get(
            "next_followup"
        )
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE leads
        SET
            notes = ?,
            lead_value = ?,
            next_followup = ?
        WHERE id = ?
    """, (
        notes,
        lead_value,
        next_followup,
        lead_id
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Lead Updated",
        (
            f"Lead #{lead_id} "
            "updated."
        )
    )

    return redirect(
        url_for(
            "lead_detail",
            lead_id=lead_id
        )
    )


# =========================================================
# PIPELINE STAGE
# =========================================================

@app.route(
    "/lead/<int:lead_id>/stage/<stage>",
    methods=["POST"]
)
def move_lead_stage(
    lead_id,
    stage
):
    if stage not in PIPELINE_STAGES:

        return redirect(
            url_for(
                "lead_detail",
                lead_id=lead_id
            )
        )

    score_map = {
        "New Lead": 20,
        "Follow Up": 30,
        "Contacted": 40,
        "Interested": 65,
        "Proposal": 85,
        "Won": 100,
        "Lost": 0
    }

    score = score_map.get(
        stage,
        20
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE leads
        SET
            pipeline_stage = ?,
            lead_score = ?
        WHERE id = ?
    """, (
        stage,
        score,
        lead_id
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Pipeline Updated",
        (
            f"Lead #{lead_id} "
            f"moved to {stage}."
        )
    )

    return redirect(
        url_for(
            "lead_detail",
            lead_id=lead_id
        )
    )


# =========================================================
# FOLLOW-UP
# =========================================================

@app.route(
    "/lead/<int:lead_id>/approve-followup",
    methods=["POST"]
)
def approve_followup(
    lead_id
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE leads
        SET followup_status = 'Approved'
        WHERE id = ?
    """, (
        lead_id,
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Follow-Up Approved",
        (
            "Follow-up approved "
            f"for lead #{lead_id}."
        )
    )

    return redirect(
        request.referrer
        or url_for(
            "leads_page"
        )
    )


@app.route(
    "/lead/<int:lead_id>/regenerate-followup",
    methods=["POST"]
)
def regenerate_followup(
    lead_id
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE leads
        SET
            followup_draft = NULL,
            followup_status = 'Not Drafted',
            status = 'Follow Up Required',
            pipeline_stage = 'Follow Up'
        WHERE id = ?
    """, (
        lead_id,
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Follow-Up Regeneration Requested",
        (
            f"Lead #{lead_id} "
            "queued for a new follow-up."
        )
    )

    return redirect(
        request.referrer
        or url_for(
            "leads_page"
        )
    )


@app.route(
    "/lead/<int:lead_id>/contacted",
    methods=["POST"]
)
def mark_lead_contacted(
    lead_id
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE leads
        SET
            status = 'Contacted',
            pipeline_stage = 'Contacted',
            lead_score = 40
        WHERE id = ?
    """, (
        lead_id,
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Lead Contacted",
        (
            f"Lead #{lead_id} "
            "marked as contacted."
        )
    )

    return redirect(
        request.referrer
        or url_for(
            "leads_page"
        )
    )


# =========================================================
# CONVERT LEAD
# =========================================================

@app.route(
    "/lead/<int:lead_id>/convert",
    methods=["POST"]
)
def convert_lead(
    lead_id
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            name,
            email,
            phone
        FROM leads
        WHERE id = ?
    """, (
        lead_id,
    ))

    lead = cursor.fetchone()

    if not lead:

        conn.close()

        return redirect(
            url_for(
                "leads_page"
            )
        )

    customer_exists = 0

    if lead[1]:

        cursor.execute("""
            SELECT COUNT(*)
            FROM customers
            WHERE email = ?
        """, (
            lead[1],
        ))

        customer_exists = (
            cursor.fetchone()[0]
        )

    if customer_exists == 0:

        cursor.execute("""
            INSERT INTO customers (
                name,
                email,
                phone
            )
            VALUES (?, ?, ?)
        """, (
            lead[0],
            lead[1],
            lead[2]
        ))

    cursor.execute("""
        UPDATE leads
        SET
            status = 'Converted',
            pipeline_stage = 'Won',
            lead_score = 100
        WHERE id = ?
    """, (
        lead_id,
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Lead Won",
        (
            f"Lead #{lead_id} "
            "converted to customer."
        )
    )

    return redirect(
        url_for(
            "leads_page"
        )
    )


# =========================================================
# CUSTOMERS
# =========================================================

@app.route("/customers")
def customers_page():

    return render_template(
        "customers.html",

        customers=
            get_customers()
    )


# =========================================================
# TASKS
# =========================================================

@app.route("/tasks")
def tasks_page():

    return render_template(
        "tasks.html",

        tasks=
            get_tasks()
    )


@app.route(
    "/task/<int:task_id>/complete",
    methods=["POST"]
)
def complete_task(
    task_id
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tasks
        SET status = 'Completed'
        WHERE id = ?
    """, (
        task_id,
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Task Completed",
        (
            f"Task #{task_id} "
            "completed."
        )
    )

    return redirect(
        url_for(
            "tasks_page"
        )
    )


# =========================================================
# CONTENT
# =========================================================

@app.route("/content")
def content_page():

    return render_template(
        "content.html",

        content=
            get_content()
    )


@app.route(
    "/generate-post",
    methods=["POST"]
)
def generate_post():

    platform = (
        request.form.get(
            "platform",
            "Instagram"
        )
    )

    topic = (
        request.form.get(
            "topic",
            "BizFlow SA"
        )
    )

    prompt = f"""
Create one strong {platform} marketing post for BizFlow SA.

Target:
South African small business owners.

Topic:
{topic}

Requirements:
- Strong hook
- Professional
- Friendly
- Useful
- Clear CTA
- No unrealistic claims

Return only the post.
"""

    try:

        post = ask_operator(
            prompt
        )

    except Exception as error:

        log_activity(
            "Content Error",
            str(error)
        )

        return redirect(
            url_for(
                "content_page"
            )
        )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO content_queue (
            title,
            content,
            status,
            platform
        )
        VALUES (?, ?, ?, ?)
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
        (
            f"Generated {platform} "
            f"content for {topic}."
        )
    )

    return redirect(
        url_for(
            "content_page"
        )
    )


@app.route(
    "/content/<int:content_id>/approve",
    methods=["POST"]
)
def approve_content(
    content_id
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE content_queue
        SET status = 'Approved'
        WHERE id = ?
    """, (
        content_id,
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Content Approved",
        (
            f"Content #{content_id} "
            "approved."
        )
    )

    return redirect(
        request.referrer
        or url_for(
            "content_page"
        )
    )


@app.route(
    "/content/<int:content_id>/reject",
    methods=["POST"]
)
def reject_content(
    content_id
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE content_queue
        SET status = 'Rejected'
        WHERE id = ?
    """, (
        content_id,
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Content Rejected",
        (
            f"Content #{content_id} "
            "rejected."
        )
    )

    return redirect(
        request.referrer
        or url_for(
            "content_page"
        )
    )


@app.route(
    "/content/<int:content_id>/schedule",
    methods=["POST"]
)
def schedule_content(
    content_id
):
    scheduled_for = (
        request.form.get(
            "scheduled_for"
        )
    )

    if not scheduled_for:

        return redirect(
            url_for(
                "content_page"
            )
        )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE content_queue
        SET
            status = 'Scheduled',
            scheduled_for = ?
        WHERE id = ?
    """, (
        scheduled_for,
        content_id
    ))

    conn.commit()
    conn.close()

    log_activity(
        "Content Scheduled",
        (
            f"Content #{content_id} "
            f"scheduled for "
            f"{scheduled_for}."
        )
    )

    return redirect(
        url_for(
            "content_page"
        )
    )


# =========================================================
# APPROVALS
# =========================================================

@app.route("/approvals")
def approvals_page():

    content_approvals = [
        item
        for item in get_content()
        if item[3]
        == "Pending Approval"
    ]

    lead_approvals = [
        lead
        for lead in get_leads()
        if lead[8]
        == "Pending Approval"
    ]

    return render_template(
        "approvals.html",

        approvals=
            content_approvals,

        lead_approvals=
            lead_approvals
    )


# =========================================================
# ACTIVITY
# =========================================================

@app.route("/activity")
def activity_page():

    return render_template(
        "activity.html",

        activity=
            get_activity(100)
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