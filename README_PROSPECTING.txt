BIZFLOW REAL PROSPECTING UPGRADE
================================

WHAT THIS ADDS
- Real business discovery using Google Places API (New) Text Search
- Duplicate prevention using Google Place ID
- AI prospect scoring and fit reason
- AI outreach drafts that require approval
- Prospects page in BizFlow
- Convert a qualified prospect into the existing Leads pipeline
- Daily low-volume prospecting from GitHub Actions
- Works with SQLite locally and PostgreSQL on Render

FILES
Copy these files over the matching files in your current bizflow-sa project.

NEW GITHUB SECRET
GOOGLE_PLACES_API_KEY

GitHub Actions DATABASE_URL must remain your Render EXTERNAL database URL.
Render Web Service DATABASE_URL should remain your Render INTERNAL database URL.

GOOGLE SETUP
1. Create/open a Google Cloud project.
2. Enable Places API (New).
3. Enable billing. Google currently provides monthly free usage caps by SKU.
4. Create an API key and restrict it to Places API (New).
5. Add the key to GitHub repository Actions secrets as GOOGLE_PLACES_API_KEY.
6. Set a conservative Google Cloud quota/budget alert before enabling automated discovery.

COST CONTROL
The workflow defaults to only 2 Text Search requests per daily prospecting cycle, 5 results each.
The operator runs hourly, but prospecting.py records the day in system_state and skips prospecting after the first successful run each day.

DEPLOY
PowerShell:
  git add .
  git commit -m "Add real business prospecting"
  git push

Then run GitHub Actions > BizFlow Operator > Run workflow once manually.

WHAT V1 DOES NOT DO
- It does NOT automatically send cold email/messages yet.
- Approved outreach is kept for review. Sending will be added after we connect a proper outbound channel and opt-out/rate-limit controls.
- It does not scrape private personal information.
