import os
import google.generativeai as genai
from datetime import datetime

# Initialize generation model
model = None

def init_gemini():
    global model
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return False
    genai.configure(api_key=api_key)
    # Using gemini-2.5-flash as it has a much higher quota on this API key than 3.5
    model = genai.GenerativeModel('gemini-2.5-flash')
    return True

def generate_flight_insights(bookings):
    """
    Generate AI insights based on the active bookings.
    Returns a string of insights.
    """
    if not init_gemini():
        return "✨ **AI Insights not configured:** Please add `GEMINI_API_KEY` to your `.env` file to enable smart travel insights."

    if not bookings:
        return "You have no upcoming flights to track. Ready for your next adventure?"

    # Build the prompt
    today_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    prompt = f"You are a helpful and intelligent personal travel assistant. The current date and time is {today_str}. "
    prompt += "Here are your client's upcoming flights:\n\n"
    
    for b in bookings:
        route = b.get('route', 'Unknown')
        date = b.get('flight_date', 'Unknown')
        airline = b.get('airline', 'Unknown')
        status = b.get('status', 'Unknown')
        detail = b.get('status_detail', '')
        prompt += f"- Route: {route} on {date} (Airline: {airline}). Status: {status}. Notes: {detail}\n"
        
    prompt += "\nBased on this information, provide a concise, personalized, and helpful 2-3 sentence summary for the user. "
    prompt += "Highlight any important things (like if they are flying very soon, if they have multiple flights, or if any flight is not confirmed). "
    prompt += "Do not list out the flights again. Keep it punchy, friendly, and actionable."

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota exceeded" in error_msg:
            return "✨ **AI is currently resting:** The high-speed AI tier limits us to 5 queries per minute. Please try refreshing again in about 30 seconds!"
        return f"Could not generate insights right now. Please try again later."
