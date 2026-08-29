BIZFLOW INSTAGRAM AUTOMATION UPGRADE
====================================

THIS PACK FINISHES THE CODING SIDE WHILE META VERIFICATION IS PENDING.

WHAT IT ADDS
------------
- AI Instagram caption generation
- Approval / rejection queue
- Image URL per post
- Scheduling
- Automatic scheduled publishing once Meta credentials are connected
- Manual Publish Now / Retry Publish
- Published / Failed statuses
- Instagram post ID logging
- Activity log for publishing success/failure
- Safe behavior while Meta verification is incomplete

FILES TO COPY INTO CURRENT BIZFLOW REPO
---------------------------------------
app.py
automation_engine.py
database.py
instagram_publisher.py
requirements.txt
templates/content.html
templates/approvals.html
templates/base.html
static/style.css
.github/workflows/bizflow-operator.yml

DEPLOY NOW
----------
Copy the files, then:

git add .
git commit -m "Add Instagram content automation"
git push

Render will redeploy the website.

The GitHub Action can continue running without Meta credentials. It will print:
Instagram publisher not connected yet - queued posts kept safe.

THAT IS EXPECTED UNTIL META VERIFICATION IS DONE.

AFTER META VERIFICATION
-----------------------
We will add the exact credentials Meta gives us.
The publishing code expects:

META_ACCESS_TOKEN
META_IG_USER_ID

Optional:
META_GRAPH_VERSION
META_GRAPH_BASE_URL

For the scheduled GitHub operator, META_ACCESS_TOKEN and META_IG_USER_ID will be GitHub Actions repository secrets.
For manual Publish Now from the Render website, the same variables must also be added to the Render Web Service Environment.

IMPORTANT ABOUT INSTAGRAM POSTS
-------------------------------
Instagram feed publishing needs media. The current V1 uses a public image URL.
The Content page now has an "Instagram image URL" box.

Later we can add an automatic image-generation/storage stage so BizFlow creates the visual too.

DO NOT ADD META TOKENS YET IF VERIFICATION IS STILL PENDING.
