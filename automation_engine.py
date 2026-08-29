import os
import time
from datetime import datetime

from database import get_connection, create_database
from bizflow_operator import ask_operator
from prospecting import run_daily_prospecting

RUN_ONCE = os.getenv("RUN_ONCE", "false").strip().lower() in ("1", "true", "yes", "on")


# =========================================================
# ACTIVITY
# =========================================================

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
# OPERATOR HEARTBEAT
# =========================================================

def ensure_operator_status_table():
    conn=get_connection(); cursor=conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS operator_status (
        id INTEGER PRIMARY KEY,status TEXT,last_heartbeat TEXT,last_cycle_started TEXT,
        last_cycle_completed TEXT,last_error TEXT)""")
    conn.commit(); conn.close()


def ensure_operator_status_row():
    ensure_operator_status_table()
    conn=get_connection(); cursor=conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM operator_status WHERE id=1")
    if cursor.fetchone()[0] == 0:
        now=datetime.now().isoformat(timespec="seconds")
        cursor.execute("INSERT INTO operator_status (id,status,last_heartbeat) VALUES (1,'Offline',?)", (now,))
        conn.commit()
    conn.close()


def update_operator_heartbeat(status="Online", error_message=None):
    ensure_operator_status_row(); conn=get_connection(); cursor=conn.cursor(); now=datetime.now().isoformat(timespec="seconds")
    cursor.execute("UPDATE operator_status SET status=?,last_heartbeat=?,last_error=? WHERE id=1", (status,now,error_message))
    conn.commit(); conn.close()


def mark_cycle_started():
    ensure_operator_status_row(); conn=get_connection(); cursor=conn.cursor(); now=datetime.now().isoformat(timespec="seconds")
    cursor.execute("UPDATE operator_status SET status='Running',last_heartbeat=?,last_cycle_started=?,last_error=NULL WHERE id=1", (now,now))
    conn.commit(); conn.close()


def mark_cycle_completed():
    ensure_operator_status_row(); conn=get_connection(); cursor=conn.cursor(); now=datetime.now().isoformat(timespec="seconds")
    cursor.execute("UPDATE operator_status SET status='Online',last_heartbeat=?,last_cycle_completed=?,last_error=NULL WHERE id=1", (now,now))
    conn.commit(); conn.close()


def mark_operator_error(error):
    ensure_operator_status_row(); conn=get_connection(); cursor=conn.cursor(); now=datetime.now().isoformat(timespec="seconds")
    cursor.execute("UPDATE operator_status SET status='Error',last_heartbeat=?,last_error=? WHERE id=1", (now,str(error)))
    conn.commit(); conn.close()


# =========================================================
# TASK CREATION
# =========================================================

def create_task(
    title,
    description,
    priority="Normal",
    due_date=None
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE title = ?
        AND status != 'Completed'
    """, (
        title,
    ))

    exists = cursor.fetchone()[0]

    if exists == 0:

        cursor.execute("""
            INSERT INTO tasks (
                title,
                description,
                status,
                priority,
                due_date
            )
            VALUES (
                ?,
                ?,
                'Pending',
                ?,
                ?
            )
        """, (
            title,
            description,
            priority,
            due_date
        ))

        conn.commit()
        created = True

    else:
        created = False

    conn.close()

    return created


# =========================================================
# LEAD SCORING
# =========================================================

def score_leads():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            pipeline_stage,
            lead_value,
            next_followup,
            email,
            phone,
            source
        FROM leads
        WHERE pipeline_stage NOT IN (
            'Won',
            'Lost'
        )
    """)

    leads = cursor.fetchall()

    conn.close()

    now = datetime.now()

    for lead in leads:

        lead_id = lead[0]
        stage = lead[1] or "New Lead"
        value = lead[2] or 0
        next_followup = lead[3]
        email = lead[4]
        phone = lead[5]
        source = lead[6]

        stage_scores = {
            "New Lead": 20,
            "Follow Up": 30,
            "Contacted": 40,
            "Interested": 65,
            "Proposal": 85
        }

        score = stage_scores.get(
            stage,
            20
        )

        if value >= 5000:
            score += 10

        elif value >= 1000:
            score += 5

        if email:
            score += 3

        if phone:
            score += 3

        if source in (
            "Referral",
            "Website"
        ):
            score += 4

        if next_followup:

            try:
                followup = datetime.fromisoformat(
                    next_followup
                )

                if followup <= now:
                    score += 10

            except ValueError:
                pass

        score = min(
            score,
            100
        )

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE leads
            SET
                lead_score = ?,
                last_scored_at = ?
            WHERE id = ?
        """, (
            score,
            now.isoformat(
                timespec="seconds"
            ),
            lead_id
        ))

        conn.commit()
        conn.close()

    print("Lead scoring completed.")


# =========================================================
# NEW LEADS
# =========================================================

def process_new_leads():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            email,
            phone,
            source
        FROM leads
        WHERE status = 'New'
        ORDER BY id
    """)

    leads = cursor.fetchall()

    # IMPORTANT:
    # close read connection before creating tasks
    # or updating leads
    conn.close()

    if not leads:
        print("No new leads found.")
        return

    print(
        f"{len(leads)} new lead(s) found."
    )

    for lead in leads:

        lead_id = lead[0]
        name = lead[1] or "Unknown Lead"
        email = lead[2] or ""
        phone = lead[3] or ""
        source = lead[4] or "Unknown"

        task_title = (
            f"Follow up lead #{lead_id} - {name}"
        )

        description = f"""
Lead: {name}
Email: {email}
Phone: {phone}
Source: {source}

Contact this lead and establish whether BizFlow SA can help their business.
""".strip()

        created = create_task(
            task_title,
            description,
            "High"
        )

        # Separate short transaction for lead update
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE leads
            SET
                status = 'Follow Up Required',
                pipeline_stage = 'Follow Up'
            WHERE id = ?
        """, (
            lead_id,
        ))

        conn.commit()
        conn.close()

        # Log only AFTER the other write transaction closes
        if created:

            log_activity(
                "New Lead Processed",
                f"Created follow-up work for {name}."
            )

            print(
                f"New lead processed: {name}"
            )


# =========================================================
# FOLLOW-UP DRAFTS
# =========================================================

def draft_followups():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            email,
            phone,
            source
        FROM leads
        WHERE status = 'Follow Up Required'
        AND pipeline_stage NOT IN (
            'Won',
            'Lost'
        )
        AND (
            followup_draft IS NULL
            OR followup_draft = ''
        )
    """)

    leads = cursor.fetchall()

    conn.close()

    for lead in leads:

        lead_id = lead[0]
        name = lead[1] or "Customer"

        prompt = f"""
Create a short customer follow-up for BizFlow SA.

Customer:
{name}

Email:
{lead[2] or ""}

Phone:
{lead[3] or ""}

Source:
{lead[4] or "Unknown"}

Requirements:
- Friendly
- Professional
- Short
- Natural
- South African business tone
- Ask one simple question
- No unrealistic promises

Return only the finished message.
"""

        try:

            message = ask_operator(
                prompt
            )

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE leads
                SET
                    followup_draft = ?,
                    followup_status =
                        'Pending Approval'
                WHERE id = ?
            """, (
                message,
                lead_id
            ))

            conn.commit()
            conn.close()

            log_activity(
                "Follow-Up Drafted",
                f"AI drafted follow-up for {name}."
            )

            print(
                f"Follow-up drafted for {name}."
            )

        except Exception as error:

            print(
                f"Follow-up error for {name}:",
                error
            )

            log_activity(
                "Automation Error",
                f"Follow-up for {name}: {error}"
            )


# =========================================================
# OVERDUE FOLLOW UPS
# =========================================================

def check_overdue_followups():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            next_followup,
            pipeline_stage,
            lead_score
        FROM leads
        WHERE next_followup IS NOT NULL
        AND next_followup != ''
        AND pipeline_stage NOT IN (
            'Won',
            'Lost'
        )
    """)

    leads = cursor.fetchall()

    conn.close()

    now = datetime.now()

    for lead in leads:

        name = lead[1]
        next_followup = lead[2]
        score = lead[4] or 0

        try:

            followup = datetime.fromisoformat(
                next_followup
            )

        except ValueError:
            continue

        if followup > now:
            continue

        priority = (
            "Urgent"
            if score >= 70
            else "High"
        )

        title = (
            f"Overdue follow-up - {name}"
        )

        created = create_task(
            title,
            (
                f"Follow up with {name}. "
                f"This was due {next_followup}."
            ),
            priority,
            next_followup
        )

        if created:

            log_activity(
                "Overdue Follow-Up",
                (
                    f"{priority} follow-up task "
                    f"created for {name}."
                )
            )

            print(
                f"Overdue task created for {name}."
            )


# =========================================================
# DAILY INSTAGRAM CONTENT
# =========================================================

def ensure_daily_content():
    today = datetime.now().strftime(
        "%Y-%m-%d"
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM content_queue
        WHERE DATE(created_at) = ?
        AND platform = 'Instagram'
    """, (
        today,
    ))

    exists = cursor.fetchone()[0]

    conn.close()

    if exists > 0:
        print(
            "Today's Instagram content already exists."
        )
        return

    prompt = """
Create today's Instagram post for BizFlow SA.

Audience:
South African small business owners.

Requirements:
- Useful
- Strong hook
- Professional
- Friendly
- Concise
- Clear call to action
- No unrealistic claims

Return only the finished post.
"""

    try:

        post = ask_operator(
            prompt
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
            VALUES (
                ?,
                ?,
                'Pending Approval',
                'Instagram'
            )
        """, (
            "Daily Instagram Post",
            post
        ))

        conn.commit()
        conn.close()

        log_activity(
            "Daily Content Created",
            (
                "AI created today's "
                "Instagram content."
            )
        )

        print(
            "Daily Instagram content created."
        )

    except Exception as error:

        print(
            "Daily content error:",
            error
        )

        log_activity(
            "Automation Error",
            f"Daily content: {error}"
        )


# =========================================================
# SCHEDULED CONTENT
# =========================================================

def process_scheduled_content():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            title,
            platform,
            scheduled_for
        FROM content_queue
        WHERE status = 'Scheduled'
        AND scheduled_for IS NOT NULL
    """)

    items = cursor.fetchall()

    conn.close()

    now = datetime.now()

    for item in items:

        content_id = item[0]
        title = item[1]
        platform = item[2]
        scheduled_for = item[3]

        try:

            scheduled_time = (
                datetime.fromisoformat(
                    scheduled_for
                )
            )

        except ValueError:
            continue

        if scheduled_time > now:
            continue

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE content_queue
            SET status = 'Ready to Publish'
            WHERE id = ?
        """, (
            content_id,
        ))

        conn.commit()
        conn.close()

        log_activity(
            "Content Ready",
            (
                f"{platform} content "
                f"#{content_id} ({title}) "
                "reached its scheduled time."
            )
        )

        print(
            f"Content #{content_id} "
            "is ready to publish."
        )


# =========================================================
# OVERDUE TASKS
# =========================================================

def update_overdue_tasks():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            due_date
        FROM tasks
        WHERE status != 'Completed'
        AND due_date IS NOT NULL
        AND due_date != ''
    """)

    tasks = cursor.fetchall()

    conn.close()

    now = datetime.now()

    for task in tasks:

        task_id = task[0]
        due_date = task[1]

        try:

            due = datetime.fromisoformat(
                due_date
            )

        except ValueError:
            continue

        if due <= now:

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE tasks
                SET priority = 'Urgent'
                WHERE id = ?
            """, (
                task_id,
            ))

            conn.commit()
            conn.close()


# =========================================================
# BUSINESS SNAPSHOT
# =========================================================

def create_business_snapshot():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM leads
        WHERE pipeline_stage NOT IN (
            'Won',
            'Lost'
        )
    """)
    leads = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM leads
        WHERE lead_score >= 70
        AND pipeline_stage NOT IN (
            'Won',
            'Lost'
        )
    """)
    hot = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE status != 'Completed'
    """)
    tasks = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE status != 'Completed'
        AND priority = 'Urgent'
    """)
    urgent = cursor.fetchone()[0]

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
    pipeline = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM content_queue
        WHERE status = 'Pending Approval'
    """)
    approvals = cursor.fetchone()[0]

    conn.close()

    summary = (
        f"Active leads: {leads}. "
        f"Hot leads: {hot}. "
        f"Open tasks: {tasks}. "
        f"Urgent tasks: {urgent}. "
        f"Pipeline: R{pipeline:.2f}. "
        f"Content waiting approval: "
        f"{approvals}."
    )

    log_activity(
        "Business Snapshot",
        summary
    )

    print(summary)


# =========================================================
# FULL OPERATOR CYCLE
# =========================================================

def run_operator_cycle():
    mark_cycle_started()
    print()
    print(
        "================================"
    )
    print(
        "      BIZFLOW OPERATOR CYCLE"
    )
    print(
        "================================"
    )

    print(
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print()

    score_leads()

    process_new_leads()

    draft_followups()

    check_overdue_followups()

    update_overdue_tasks()

    ensure_daily_content()

    process_scheduled_content()

    run_daily_prospecting()

    create_business_snapshot()

    log_activity(
        "Operator Cycle",
        (
            "BizFlow completed its "
            "automated business cycle."
        )
    )

    mark_cycle_completed()

    print()
    print(
        "Operator cycle complete."
    )
    print()


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    create_database()
    ensure_operator_status_row()

    print()
    print("BizFlow Automation Engine")

    if RUN_ONCE:
        print("Mode: Scheduled cloud cycle")
        print("Running one cycle and exiting.")
        print()
        try:
            run_operator_cycle()
            print("Scheduled operator run complete.")
        except Exception as error:
            print("Operator error:", error)
            try:
                mark_operator_error(error)
                log_activity("Automation Error", str(error))
            except Exception:
                pass
            raise
    else:
        update_operator_heartbeat("Online")
        print("Mode: Continuous local operator")
        print("Checking business every hour.")
        print("Press CTRL+C to stop.")
        print()
        while True:
            try:
                run_operator_cycle()
            except KeyboardInterrupt:
                try:
                    update_operator_heartbeat("Stopped")
                except Exception:
                    pass
                print("BizFlow automation stopped.")
                break
            except Exception as error:
                print("Operator error:", error)
                try:
                    mark_operator_error(error)
                    log_activity("Automation Error", str(error))
                except Exception:
                    pass
            time.sleep(3600)
