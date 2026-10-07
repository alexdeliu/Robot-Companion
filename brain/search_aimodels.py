import os
import google.generativeai as genai
from dotenv import load_dotenv

# Ne conectăm cu cheia ta
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

print("M-am conectat la Google! Caut modelele permise pentru contul tău...")
print("-" * 40)

# Întrebăm serverul ce modele suportă generare de text
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)
        
print("-" * 40)