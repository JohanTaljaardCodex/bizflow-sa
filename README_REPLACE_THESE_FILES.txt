BIZFLOW FULL UI FIX
===================

This pack fixes the inconsistent operator pages and replaces the whole UI layer.

REPLACE YOUR CURRENT:
templates/
static/style.css

You can copy the entire templates folder over your current templates folder.

IMPORTANT:
This does NOT replace app.py, database.py, automation_engine.py, or any backend logic.

FILES INCLUDED:
templates/public_base.html
templates/home.html
templates/growth_system.html
templates/how_it_works.html
templates/pricing.html
templates/contact.html
templates/operator_login.html
templates/base.html
templates/dashboard.html
templates/leads.html
templates/lead_detail.html
templates/prospects.html
templates/customers.html
templates/tasks.html
templates/content.html
templates/approvals.html
templates/activity.html
static/style.css

DEPLOY:
git add .
git commit -m "Fix full BizFlow website and operator UI"
git push

Then let Render redeploy and hard-refresh the site with CTRL+F5.
