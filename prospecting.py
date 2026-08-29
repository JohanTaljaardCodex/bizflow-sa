import json
import os
import urllib.error
import urllib.request
from datetime import datetime

from database import get_connection
from bizflow_operator import ask_operator


PLACES_URL = "https://places.googleapis.com/v1/places:searchText"

TARGETS = [
    ("accounting firms", "Cape Town"),
    ("bookkeepers", "Johannesburg"),
    ("estate agencies", "Cape Town"),
    ("estate agencies", "Johannesburg"),
    ("plumbers", "Johannesburg"),
    ("electricians", "Cape Town"),
    ("gyms and fitness studios", "Durban"),
    ("salons and barbers", "Pretoria"),
    ("small logistics companies", "Johannesburg"),
    ("business consultants", "Cape Town"),
    ("digital agencies", "Durban"),
    ("cleaning companies", "Johannesburg"),
    ("solar installers", "Pretoria"),
    ("security companies", "Durban"),
    ("auto repair workshops", "Cape Town"),
    ("property maintenance companies", "Johannesburg"),
]


def log_activity(action, details):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO activity (action,details) VALUES (?,?)", (action, details))
    conn.commit()
    conn.close()


def get_state(key):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT state_value FROM system_state WHERE state_key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def set_state(key, value):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM system_state WHERE state_key=?", (key,))
    exists = cur.fetchone()[0]
    now = datetime.now().isoformat(timespec="seconds")
    if exists:
        cur.execute("UPDATE system_state SET state_value=?,updated_at=? WHERE state_key=?", (value, now, key))
    else:
        cur.execute("INSERT INTO system_state (state_key,state_value,updated_at) VALUES (?,?,?)", (key, value, now))
    conn.commit()
    conn.close()


def places_search(text_query, api_key, max_results=5):
    body = json.dumps({
        "textQuery": text_query,
        "pageSize": max(1, min(int(max_results), 20)),
        "languageCode": "en",
        "regionCode": "ZA",
    }).encode("utf-8")

    # Includes contact fields so BizFlow can prepare useful outreach.
    # Keep query volume low because these fields use the higher Places SKU tier.
    field_mask = ",".join([
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.googleMapsUri",
        "places.businessStatus",
        "places.primaryType",
    ])

    request = urllib.request.Request(
        PLACES_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": field_mask,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8")).get("places", [])
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Places HTTP {exc.code}: {details[:500]}") from exc


def save_prospect(place, industry, city):
    place_id = place.get("id")
    display = place.get("displayName") or {}
    business_name = display.get("text") or "Unknown Business"

    if not place_id:
        return False

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM prospects WHERE google_place_id=?", (place_id,))
    existing = cur.fetchone()
    now = datetime.now().isoformat(timespec="seconds")

    if existing:
        cur.execute("UPDATE prospects SET last_seen_at=? WHERE google_place_id=?", (now, place_id))
        conn.commit()
        conn.close()
        return False

    cur.execute("""INSERT INTO prospects (
        google_place_id,business_name,industry,city,address,website,phone,maps_url,
        business_status,source,status,prospect_score,outreach_status,last_seen_at
    ) VALUES (?,?,?,?,?,?,?,?,?,'Google Places','Discovered',0,'Not Drafted',?)""", (
        place_id,
        business_name,
        industry,
        city,
        place.get("formattedAddress"),
        place.get("websiteUri"),
        place.get("nationalPhoneNumber"),
        place.get("googleMapsUri"),
        place.get("businessStatus"),
        now,
    ))
    conn.commit()
    conn.close()
    return True


def get_unqualified_prospects(limit=10):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT id,business_name,industry,city,address,website,phone,maps_url
                   FROM prospects
                   WHERE status='Discovered'
                   ORDER BY id DESC
                   LIMIT ?""", (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


def qualify_prospect(row):
    prospect_id, name, industry, city, address, website, phone, maps_url = row

    prompt = f"""
You are qualifying a real public business prospect for BizFlow SA.

BizFlow SA sells an AI-powered Small Business Growth System that helps small businesses:
- capture and manage leads
- follow up faster
- create marketing content
- automate repetitive work
- improve sales visibility and business growth

Business name: {name}
Industry: {industry}
City: {city}
Address: {address or 'Unknown'}
Website available: {'Yes' if website else 'No'}
Phone available: {'Yes' if phone else 'No'}
Google Maps: {maps_url or 'Unknown'}

Return valid JSON only, with exactly these keys:
{{
  "score": 0-100,
  "fit_reason": "one short factual reason why this business may or may not fit BizFlow",
  "outreach": "a short personalised B2B introduction. Do not claim you inspected information you do not have. Do not make income promises. Ask whether they are open to hearing how BizFlow could help with leads, follow-ups, marketing or admin automation."
}}
"""

    raw = ask_operator(prompt)
    text = str(raw).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        result = json.loads(text)
    except Exception:
        result = {
            "score": 50,
            "fit_reason": "Potential small-business fit; manual review recommended.",
            "outreach": text[:1500],
        }

    score = max(0, min(int(result.get("score", 50)), 100))
    fit_reason = str(result.get("fit_reason", "Manual review recommended."))[:1000]
    outreach = str(result.get("outreach", ""))[:3000]
    status = "Qualified" if score >= 60 else "Low Fit"
    outreach_status = "Pending Approval" if score >= 60 and outreach else "Not Drafted"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""UPDATE prospects
                   SET prospect_score=?,fit_reason=?,outreach_draft=?,outreach_status=?,status=?
                   WHERE id=?""",
                (score, fit_reason, outreach, outreach_status, status, prospect_id))
    conn.commit()
    conn.close()


def run_daily_prospecting():
    enabled = os.getenv("PROSPECTING_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        print("Prospecting disabled.")
        return

    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        print("Prospecting skipped: GOOGLE_PLACES_API_KEY is missing.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    if get_state("last_prospecting_date") == today:
        print("Prospecting already ran today.")
        return

    queries_per_run = max(1, min(int(os.getenv("PROSPECT_QUERIES_PER_RUN", "2")), 4))
    results_per_query = max(1, min(int(os.getenv("PROSPECT_RESULTS_PER_QUERY", "5")), 10))

    # Rotate through target markets so each day covers different industries/cities.
    day_index = datetime.now().toordinal() % len(TARGETS)
    targets = [TARGETS[(day_index + i) % len(TARGETS)] for i in range(queries_per_run)]

    discovered = 0
    for industry, city in targets:
        query = f"{industry} in {city}, South Africa"
        print(f"Prospecting: {query}")
        places = places_search(query, api_key, results_per_query)
        for place in places:
            if place.get("businessStatus") == "CLOSED_PERMANENTLY":
                continue
            if save_prospect(place, industry, city):
                discovered += 1

    qualified = 0
    for row in get_unqualified_prospects(limit=queries_per_run * results_per_query):
        try:
            qualify_prospect(row)
            qualified += 1
        except Exception as exc:
            print(f"Prospect qualification error: {exc}")

    set_state("last_prospecting_date", today)
    log_activity(
        "Prospecting Cycle",
        f"Found {discovered} new real businesses and reviewed {qualified} prospects."
    )
    print(f"Prospecting complete. New: {discovered}. Reviewed: {qualified}.")
