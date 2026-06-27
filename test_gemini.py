import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
print("Key starts with:", api_key[:10])

genai.configure(api_key=api_key)

try:
    models = genai.list_models()
    print("Available models:")
    for m in models:
        if 'generateContent' in m.supported_generation_methods:
            print(m.name)
            
    print("\nTrying to generate content with gemini-2.5-flash:")
    model = genai.GenerativeModel('gemini-2.5-flash')
    response = model.generate_content("Hello")
    print(response.text)
except Exception as e:
    print("Error:", str(e))
