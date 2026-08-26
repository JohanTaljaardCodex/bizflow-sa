from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for
from database import get_connection, create_database
from bizflow_operator import ask_operator

app = Flask(__name__)
PIPELINE_STAGES = ["New Lead", "Follow Up", "Contacted", "Interested", "Proposal", "Won", "Lost"]


def log_activity(action, details):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO activity (action, details) VALUES (?, ?)", (action, details))
    conn.commit(); conn.close()


def ensure_operator_status_table():
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS operator_status (
        id INTEGER PRIMARY KEY, status TEXT, last_heartbeat TEXT,
        last_cycle_started TEXT, last_cycle_completed TEXT, last_error TEXT)""")
    conn.commit(); conn.close()


def get_time_ago(value):
    if not value: return "Never connected"
    diff = datetime.now() - value
    seconds = max(0, int(diff.total_seconds()))
    if seconds < 60: return "Just now"
    mins = seconds // 60
    if mins < 60: return "1 minute ago" if mins == 1 else f"{mins} minutes ago"
    hours = mins // 60
    if hours < 24: return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    days = hours // 24
    return "1 day ago" if days == 1 else f"{days} days ago"


def get_operator_status():
    ensure_operator_status_table()
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT status,last_heartbeat,last_cycle_started,last_cycle_completed,last_error FROM operator_status WHERE id=1")
    row = cur.fetchone(); conn.close()
    if not row:
        return {"status":"Offline","status_class":"offline","last_heartbeat":None,"last_cycle_started":None,"last_cycle_completed":None,"last_error":None,"last_seen_text":"Never connected"}
    stored, hb, started, completed, err = row
    hb_dt = None
    if hb:
        try: hb_dt = datetime.fromisoformat(hb)
        except ValueError: pass
    status, cls = stored or "Offline", "online"
    if stored == "Stopped": status, cls = "Offline", "offline"
    elif stored == "Error": status, cls = "Error", "error"
    elif hb_dt and datetime.now() - hb_dt > timedelta(minutes=75): status, cls = "Offline", "offline"
    elif stored == "Running": status, cls = "Running", "running"
    elif hb_dt: status, cls = "Online", "online"
    else: status, cls = "Offline", "offline"
    return {"status":status,"status_class":cls,"last_heartbeat":hb,"last_cycle_started":started,"last_cycle_completed":completed,"last_error":err,"last_seen_text":get_time_ago(hb_dt)}


@app.context_processor
def inject_global_data():
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tasks WHERE status != 'Completed'"); tasks = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM content_queue WHERE status='Pending Approval'"); ca = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE followup_status='Pending Approval'"); la = cur.fetchone()[0]
    cur.execute("SELECT next_followup,pipeline_stage FROM leads WHERE next_followup IS NOT NULL AND next_followup != ''"); rows = cur.fetchall()
    conn.close()
    overdue = 0; now = datetime.now()
    for v, stage in rows:
        if stage in ("Won","Lost"): continue
        try:
            if datetime.fromisoformat(v) <= now: overdue += 1
        except ValueError: pass
    return {"nav_task_count":tasks,"nav_approval_count":ca+la,"nav_overdue_count":overdue,"operator":get_operator_status()}


def fetchall(sql, params=()):
    conn = get_connection(); cur = conn.cursor(); cur.execute(sql, params); rows = cur.fetchall(); conn.close(); return rows


def fetchone(sql, params=()):
    conn = get_connection(); cur = conn.cursor(); cur.execute(sql, params); row = cur.fetchone(); conn.close(); return row


def get_leads():
    return fetchall("""SELECT id,name,email,phone,source,status,created_at,followup_draft,followup_status,pipeline_stage,lead_value,next_followup,notes,created_at,lead_score FROM leads ORDER BY id DESC""")


def get_lead(lead_id):
    return fetchone("""SELECT id,name,email,phone,source,status,created_at,followup_draft,followup_status,pipeline_stage,lead_value,next_followup,notes,created_at,lead_score FROM leads WHERE id=?""", (lead_id,))


def get_tasks():
    return fetchall("""SELECT id,title,description,status,created_at,priority,due_date FROM tasks ORDER BY CASE priority WHEN 'Urgent' THEN 1 WHEN 'High' THEN 2 WHEN 'Normal' THEN 3 ELSE 4 END,id DESC""")


def get_customers(): return fetchall("SELECT id,name,email,phone,created_at FROM customers ORDER BY id DESC")
def get_content(): return fetchall("SELECT id,title,content,status,platform,scheduled_for,created_at FROM content_queue ORDER BY id DESC")
def get_activity(limit=50): return fetchall("SELECT action,details,created_at FROM activity ORDER BY id DESC LIMIT ?", (limit,))


def get_pipeline_counts():
    return {stage: fetchone("SELECT COUNT(*) FROM leads WHERE pipeline_stage=?", (stage,))[0] for stage in PIPELINE_STAGES}


def get_pipeline_value(): return fetchone("SELECT COALESCE(SUM(lead_value),0) FROM leads WHERE pipeline_stage NOT IN ('Won','Lost')")[0]
def get_won_value(): return fetchone("SELECT COALESCE(SUM(lead_value),0) FROM leads WHERE pipeline_stage='Won'")[0]


def get_hot_leads():
    return fetchall("""SELECT id,name,email,phone,source,status,created_at,followup_draft,followup_status,pipeline_stage,lead_value,next_followup,notes,created_at,lead_score FROM leads WHERE lead_score>=70 AND pipeline_stage NOT IN ('Won','Lost') ORDER BY lead_score DESC,lead_value DESC LIMIT 5""")


def get_overdue_leads():
    now = datetime.now(); out=[]
    for lead in get_leads():
        if not lead[11] or lead[9] in ("Won","Lost"): continue
        try:
            if datetime.fromisoformat(lead[11]) <= now: out.append(lead)
        except ValueError: pass
    return out


def render_dashboard(priorities=None):
    task_count = fetchone("SELECT COUNT(*) FROM tasks WHERE status!='Completed'")[0]
    hot_count = fetchone("SELECT COUNT(*) FROM leads WHERE lead_score>=70 AND pipeline_stage NOT IN ('Won','Lost')")[0]
    customer_count = fetchone("SELECT COUNT(*) FROM customers")[0]
    return render_template("dashboard.html", task_count=task_count, hot_lead_count=hot_count, customer_count=customer_count,
                           pipeline_value=get_pipeline_value(), won_value=get_won_value(), hot_leads=get_hot_leads(),
                           overdue_leads=get_overdue_leads(), activity=get_activity(10), priorities=priorities)


@app.route("/")
def dashboard(): return render_dashboard()


@app.route("/daily-priorities", methods=["POST"])
def daily_priorities():
    hot = get_hot_leads(); tasks=[t for t in get_tasks() if t[3] != "Completed"]; overdue=get_overdue_leads()
    prompt = f"""You are BizFlow Operator. Create today's business priorities for BizFlow SA.
HOT LEADS:\n""" + "\n".join([f"- {l[1]} | Stage {l[9]} | Score {l[14]} | Value R{l[10] or 0}" for l in hot]) + \
    "\nOPEN TASKS:\n" + "\n".join([f"- {t[1]} | Priority {t[5] or 'Normal'}" for t in tasks[:10]]) + \
    "\nOVERDUE FOLLOW-UPS:\n" + "\n".join([f"- {l[1]} | Due {l[11]}" for l in overdue]) + \
    f"\nACTIVE PIPELINE: R{get_pipeline_value():.2f}\nWON REVENUE: R{get_won_value():.2f}\nMaximum 6 concise practical priorities."
    try:
        priorities = ask_operator(prompt); log_activity("Daily Priorities", "AI generated today's business priorities.")
    except Exception as e:
        priorities = f"Unable to generate priorities: {e}"; log_activity("Operator Error", str(e))
    return render_dashboard(priorities)


@app.route("/leads")
def leads_page(): return render_template("leads.html", leads=get_leads(), pipeline_counts=get_pipeline_counts())

@app.route("/lead/<int:lead_id>")
def lead_detail(lead_id):
    lead=get_lead(lead_id)
    return render_template("lead_detail.html", lead=lead, stages=PIPELINE_STAGES) if lead else redirect(url_for("leads_page"))

@app.route("/lead/add", methods=["POST"])
def add_lead():
    vals=(request.form.get("name"),request.form.get("email"),request.form.get("phone"),request.form.get("source"),request.form.get("lead_value") or 0)
    conn=get_connection(); cur=conn.cursor(); cur.execute("""INSERT INTO leads (name,email,phone,source,status,followup_status,pipeline_stage,lead_value,lead_score) VALUES (?,?,?,?,'New','Not Drafted','New Lead',?,20)""", vals); lid=cur.lastrowid; conn.commit(); conn.close(); log_activity("Lead Added", f"Lead #{lid} added: {vals[0]}"); return redirect(url_for("leads_page"))

@app.route("/contact", methods=["GET","POST"])
def contact_page():
    if request.method == "GET": return render_template("contact.html", success=False)
    name=request.form.get("name"); email=request.form.get("email"); phone=request.form.get("phone"); message=request.form.get("message")
    if not name: return render_template("contact.html", success=False)
    conn=get_connection(); cur=conn.cursor(); cur.execute("""INSERT INTO leads (name,email,phone,source,status,followup_status,pipeline_stage,lead_value,notes,lead_score) VALUES (?,?,?,'Website','New','Not Drafted','New Lead',0,?,20)""", (name,email,phone,message)); lid=cur.lastrowid; conn.commit(); conn.close(); log_activity("Website Lead", f"New website lead #{lid}: {name}"); return render_template("contact.html", success=True)

@app.route("/lead/<int:lead_id>/update", methods=["POST"])
def update_lead(lead_id):
    conn=get_connection(); cur=conn.cursor(); cur.execute("UPDATE leads SET notes=?,lead_value=?,next_followup=? WHERE id=?", (request.form.get("notes"),request.form.get("lead_value") or 0,request.form.get("next_followup"),lead_id)); conn.commit(); conn.close(); log_activity("Lead Updated", f"Lead #{lead_id} updated."); return redirect(url_for("lead_detail", lead_id=lead_id))

@app.route("/lead/<int:lead_id>/stage/<stage>", methods=["POST"])
def move_lead_stage(lead_id, stage):
    if stage not in PIPELINE_STAGES: return redirect(url_for("lead_detail", lead_id=lead_id))
    score={"New Lead":20,"Follow Up":30,"Contacted":40,"Interested":65,"Proposal":85,"Won":100,"Lost":0}[stage]
    conn=get_connection(); cur=conn.cursor(); cur.execute("UPDATE leads SET pipeline_stage=?,lead_score=? WHERE id=?", (stage,score,lead_id)); conn.commit(); conn.close(); log_activity("Pipeline Updated", f"Lead #{lead_id} moved to {stage}."); return redirect(url_for("lead_detail", lead_id=lead_id))

@app.route("/lead/<int:lead_id>/approve-followup", methods=["POST"])
def approve_followup(lead_id):
    conn=get_connection(); conn.execute("UPDATE leads SET followup_status='Approved' WHERE id=?", (lead_id,)); conn.commit(); conn.close(); log_activity("Follow-Up Approved", f"Follow-up approved for lead #{lead_id}."); return redirect(request.referrer or url_for("leads_page"))

@app.route("/lead/<int:lead_id>/regenerate-followup", methods=["POST"])
def regenerate_followup(lead_id):
    conn=get_connection(); conn.execute("UPDATE leads SET followup_draft=NULL,followup_status='Not Drafted',status='Follow Up Required',pipeline_stage='Follow Up' WHERE id=?", (lead_id,)); conn.commit(); conn.close(); log_activity("Follow-Up Regeneration Requested", f"Lead #{lead_id} queued for a new follow-up."); return redirect(request.referrer or url_for("leads_page"))

@app.route("/lead/<int:lead_id>/contacted", methods=["POST"])
def mark_lead_contacted(lead_id):
    conn=get_connection(); conn.execute("UPDATE leads SET status='Contacted',pipeline_stage='Contacted',lead_score=40 WHERE id=?", (lead_id,)); conn.commit(); conn.close(); log_activity("Lead Contacted", f"Lead #{lead_id} marked as contacted."); return redirect(request.referrer or url_for("leads_page"))

@app.route("/lead/<int:lead_id>/convert", methods=["POST"])
def convert_lead(lead_id):
    lead=fetchone("SELECT name,email,phone FROM leads WHERE id=?", (lead_id,))
    if not lead: return redirect(url_for("leads_page"))
    conn=get_connection(); cur=conn.cursor(); exists=0
    if lead[1]: cur.execute("SELECT COUNT(*) FROM customers WHERE email=?", (lead[1],)); exists=cur.fetchone()[0]
    if exists == 0: cur.execute("INSERT INTO customers (name,email,phone) VALUES (?,?,?)", lead)
    cur.execute("UPDATE leads SET status='Converted',pipeline_stage='Won',lead_score=100 WHERE id=?", (lead_id,)); conn.commit(); conn.close(); log_activity("Lead Won", f"Lead #{lead_id} converted to customer."); return redirect(url_for("leads_page"))

@app.route("/customers")
def customers_page(): return render_template("customers.html", customers=get_customers())

@app.route("/tasks")
def tasks_page(): return render_template("tasks.html", tasks=get_tasks())

@app.route("/task/<int:task_id>/complete", methods=["POST"])
def complete_task(task_id):
    conn=get_connection(); conn.execute("UPDATE tasks SET status='Completed' WHERE id=?", (task_id,)); conn.commit(); conn.close(); log_activity("Task Completed", f"Task #{task_id} completed."); return redirect(url_for("tasks_page"))

@app.route("/content")
def content_page(): return render_template("content.html", content=get_content())

@app.route("/generate-post", methods=["POST"])
def generate_post():
    platform=request.form.get("platform","Instagram"); topic=request.form.get("topic","BizFlow SA")
    try: post=ask_operator(f"Create one strong {platform} marketing post for BizFlow SA for South African small business owners. Topic: {topic}. Strong hook, professional, friendly, useful, clear CTA, no unrealistic claims. Return only the post.")
    except Exception as e: log_activity("Content Error", str(e)); return redirect(url_for("content_page"))
    conn=get_connection(); conn.execute("INSERT INTO content_queue (title,content,status,platform) VALUES (?,?,?,?)", (f"{platform} Marketing Post",post,"Pending Approval",platform)); conn.commit(); conn.close(); log_activity("Content Generated", f"Generated {platform} content for {topic}."); return redirect(url_for("content_page"))

@app.route("/content/<int:content_id>/approve", methods=["POST"])
def approve_content(content_id):
    conn=get_connection(); conn.execute("UPDATE content_queue SET status='Approved' WHERE id=?", (content_id,)); conn.commit(); conn.close(); log_activity("Content Approved", f"Content #{content_id} approved."); return redirect(request.referrer or url_for("content_page"))

@app.route("/content/<int:content_id>/reject", methods=["POST"])
def reject_content(content_id):
    conn=get_connection(); conn.execute("UPDATE content_queue SET status='Rejected' WHERE id=?", (content_id,)); conn.commit(); conn.close(); log_activity("Content Rejected", f"Content #{content_id} rejected."); return redirect(request.referrer or url_for("content_page"))

@app.route("/content/<int:content_id>/schedule", methods=["POST"])
def schedule_content(content_id):
    scheduled=request.form.get("scheduled_for")
    if not scheduled: return redirect(url_for("content_page"))
    conn=get_connection(); conn.execute("UPDATE content_queue SET status='Scheduled',scheduled_for=? WHERE id=?", (scheduled,content_id)); conn.commit(); conn.close(); log_activity("Content Scheduled", f"Content #{content_id} scheduled for {scheduled}."); return redirect(url_for("content_page"))

@app.route("/approvals")
def approvals_page(): return render_template("approvals.html", approvals=[i for i in get_content() if i[3]=="Pending Approval"], lead_approvals=[l for l in get_leads() if l[8]=="Pending Approval"])

@app.route("/activity")
def activity_page(): return render_template("activity.html", activity=get_activity(100))

if __name__ == "__main__":
    create_database(); ensure_operator_status_table(); app.run(debug=True)
