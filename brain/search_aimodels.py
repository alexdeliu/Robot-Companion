import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print("Modele disponibile pentru cheia ta API:")
print("-" * 45)
for m in client.models.list():
    print(m.name)
print("-" * 45)