BIZFLOW SA - COMPLETE LOCAL MVP

1. Copy all files into your BizFlow Create folder.
2. Create a .env file beside app.py:
   GEMINI_API_KEY=YOUR_REAL_KEY
3. Activate your virtual environment.
4. Install dependencies:
   pip install -r requirements.txt
5. Initialise/upgrade the database:
   python database.py
6. Start everything:
   python start_bizflow.py
7. Open:
   http://127.0.0.1:5000

IMPORTANT:
- Do not put your real API key into source files.
- Keep .env private.
- This pack is the local MVP. For public deployment we should move the database to a production setup or use a persistent server disk.
