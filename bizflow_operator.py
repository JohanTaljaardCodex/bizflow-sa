from google import genai
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY is missing. Add it to your .env file.")

client = genai.Client(api_key=API_KEY)

SYSTEM_PROMPT = """
You are BizFlow Operator, an AI business operator for BizFlow SA.

Your job is to help run BizFlow SA day-to-day.

Main responsibilities:
- Create marketing content
- Create daily business tasks
- Generate Instagram post ideas
- Help manage leads
- Help follow up with customers
- Suggest sales opportunities
- Track business priorities
- Give daily business summaries

Rules:
- Focus on growing BizFlow SA.
- Keep advice practical and action-focused.
- Do not spend money without approval.
- Do not launch paid ads without approval.
- Do not issue refunds without approval.
- Do not make major account changes without approval.
- Routine marketing and admin work may be prepared automatically.
"""


def ask_operator(message):
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=message,
        config={"system_instruction": SYSTEM_PROMPT}
    )
    return response.text


if __name__ == "__main__":
    print("BizFlow Operator online. Type 'exit' to close.")
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit"]:
            break
        try:
            print("\nBizFlow Operator:\n" + ask_operator(user_input) + "\n")
        except Exception as error:
            print("\nERROR:\n", error, "\n")
