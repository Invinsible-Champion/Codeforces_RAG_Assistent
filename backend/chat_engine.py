import os
import json
import time
from google import genai
from google.genai import types
import chromadb
from chromadb.utils import embedding_functions
from config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME, EMBEDDING_MODEL
from pathlib import Path

# Suppress the HuggingFace Token warning
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

BASE_DIR = Path(__file__).resolve().parent

# --- Initialize ChromaDB ---
collection = None
def get_chroma_collection():
    global collection
    if collection is None:
        try:
            ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
            chroma_client = chromadb.PersistentClient(path=str(BASE_DIR / "chroma_data"))
            collection = chroma_client.get_collection(name=CHROMA_COLLECTION_NAME, embedding_function=ef)
        except Exception as e:
            print(f"Warning: Could not load ChromaDB: {e}")
    return collection

def clean_json_response(raw_text):
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def safe_gemini_call(client, model, contents, config=None, retries=3):
    """Wrapper to handle 503 and 429 rate limit errors with exponential backoff."""
    for attempt in range(retries):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
        except Exception as e:
            error_str = str(e)
            if "503" in error_str or "429" in error_str:
                if attempt < retries - 1:
                    sleep_time = 2 ** attempt  # 1s, 2s, 4s
                    print(f"[*] Gemini API busy (503/429). Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                    continue
            raise e # If it's not a rate limit error, or we ran out of retries, crash.

def get_target_rating(user_profile):
    """Safely calculates the target difficulty, handling unrated users."""
    avg_rating = int(user_profile.get("avg_rating", 1200))
    curr_rating = int(user_profile.get("current_rating", 0))
    
    if curr_rating == 0:
        return avg_rating if avg_rating > 0 else 1000
    return int((avg_rating + curr_rating) / 2)

def get_weakest_domain(metrics):
    """Finds the user's lowest scored tag to use as a fallback query."""
    if not metrics:
        return "arrays logic"
        
    domains = {
        "math": metrics.get("math_pref", 1),
        "dynamic programming": metrics.get("dp_pref", 1),
        "graphs and trees": metrics.get("graph_pref", 1),
        "binary search": metrics.get("binary_pref", 1),
        "data structures": metrics.get("datastruct_pref", 1)
    }
    # Return the key with the minimum value
    return min(domains, key=domains.get)

def fetch_practice_problem(user_profile: dict):
    """Bypasses general chat routing and explicitly forces a search for a tailored problem."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"error": "System Error: GEMINI_API_KEY not configured."}

    client = genai.Client(api_key=api_key)
    
    system_prompt = user_profile.get("system_prompt", "You are an AI competitive programming coach.")
    question_rating = get_target_rating(user_profile)
    weakness_fallback = get_weakest_domain(user_profile.get("metrics", {}))

    router_prompt = f"""
    {system_prompt}
    
    INSTRUCTION: The user is requesting a new Codeforces problem to practice.
    Based on their USER PROFILE, generate a search query for our problem database to target their specific weaknesses.
    You MUST respond with ONLY a valid JSON object.
    
    Output format:
    {{"search_query": "specific algorithmic keywords based on their weakness", "min_rating": {max(800, question_rating - 100)}, "max_rating": {question_rating + 200}}}
    """
    
    try:
        # Use the new retry wrapper!
        router_res = safe_gemini_call(
            client=client,
            model='gemini-2.5-flash',
            contents=router_prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        parsed_intent = json.loads(clean_json_response(router_res.text))
    except Exception as e:
        print(f"Fetch Problem Parse Error: {e} - Falling back to ML Weakness metric.")
        # SMART FALLBACK: Use the ML calculated weakness instead of a generic string
        parsed_intent = {
            "search_query": weakness_fallback,
            "min_rating": max(800, question_rating - 100),
            "max_rating": question_rating + 200
        }
    
    search_query = parsed_intent.get("search_query", weakness_fallback)
    min_rating = int(parsed_intent.get("min_rating", max(800, question_rating - 100)))
    max_rating = int(parsed_intent.get("max_rating", question_rating + 200))
    
    print(f"[*] Dedicated Problem Fetch: '{search_query}' ({min_rating}-{max_rating})")
    
    col = get_chroma_collection()
    context_str = ""
    problem_details = None
    
    if col:
        try:
            results = col.query(
                query_texts=[search_query],
                n_results=1,
                where={"$and": [
                    {"rating": {"$gte": min_rating}},
                    {"rating": {"$lte": max_rating}}
                ]}
            )
            
            if results["documents"] and len(results["documents"][0]) > 0:
                doc = results["documents"][0][0]
                meta = results["metadatas"][0][0]
                context_str = f"**Problem Retrieved from Database:** {meta.get('name', 'Unknown')}\n**Rating:** {meta.get('rating', 'Unrated')}\n**Tags:** {meta.get('tags', '')}\n\n**Problem Description:**\n{doc}"
                problem_details = meta
            else:
                context_str = "No specific problems matched those exact constraints in the database. Please offer a conceptual challenge instead."
        except Exception as e:
            print(f"Chroma Query Error: {e}")
            context_str = "Database connection error."

    presentation_prompt = f"""
    {system_prompt}
    
    The user asked for a problem to train on. You found this in the database:
    {context_str}
    
    INSTRUCTION: Introduce this problem perfectly in your persona's character. 
    Explain exactly WHY you chose this specific problem for them based on their profile. 
    Do not give them the solution. Format it nicely with markdown.
    """
    
    try:
        final_response = safe_gemini_call(
            client=client,
            model='gemini-2.5-flash',
            contents=presentation_prompt
        )
        return {"message": final_response.text, "problem_details": problem_details}
    except Exception as e:
        print(f"Presentation LLM Error: {e} - Falling back to native markdown formatting.")
        if problem_details:
            fallback_message = f"**Problem Retrieved from Database:** {problem_details.get('name', 'Unknown')}\n\n{context_str}\n\n*(Note: Your AI Coach is currently unavailable due to high server demand, but here is your requested problem directly from the database!)*"
        else:
            fallback_message = "*(Note: Your AI Coach is currently unavailable due to high server demand. Additionally, no matching problems were found in the database. Please try again later.)*"
            
        return {"message": fallback_message, "problem_details": problem_details}

def generate_chat_response(message: str, user_profile: dict, history: list = None):
    """Handles general conversational intent."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "System Error: GEMINI_API_KEY not configured."

    client = genai.Client(api_key=api_key)
    system_prompt = user_profile.get("system_prompt", "You are an AI competitive programming coach.")
    question_rating = get_target_rating(user_profile)
    weakness_fallback = get_weakest_domain(user_profile.get("metrics", {}))

    router_prompt = f"""
    {system_prompt}
    
    USER MESSAGE: "{message}"
    
    INSTRUCTION: You must decide if the user is asking for a new problem to solve, OR if they just want to chat/ask for help.
    You MUST respond with ONLY a valid JSON object. Do not add markdown or conversational text.
    
    If they want a problem to practice, output:
    {{"action": "search", "search_query": "specific algorithmic keywords based on their weakness", "min_rating": {max(800, question_rating - 100)}, "max_rating": {question_rating + 200}}}
    
    If they are just chatting or asking a conceptual question, output:
    {{"action": "chat", "response": "Your helpful AI coach response here in character."}}
    """
    
    try:
        router_res = safe_gemini_call(
            client=client,
            model='gemini-2.5-flash',
            contents=router_prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        parsed_intent = json.loads(clean_json_response(router_res.text))
        action = parsed_intent.get("action", "chat")
    except Exception as e:
        print(f"Router Parse Error: {e} - Falling back to standard chat.")
        action = "chat"
        parsed_intent = {"response": "I'm having trouble understanding your request due to server load, but I am here to help you conceptually. What do you want to learn?"}

    if action == "chat":
        return parsed_intent.get("response", "I'm here to help.")

    search_query = parsed_intent.get("search_query", weakness_fallback)
    min_rating = int(parsed_intent.get("min_rating", max(800, question_rating - 100)))
    max_rating = int(parsed_intent.get("max_rating", question_rating + 200))
    
    print(f"[*] Agent executing ChromaDB search: '{search_query}' (Rating: {min_rating}-{max_rating})")
    
    col = get_chroma_collection()
    context_str = ""
    
    if col:
        try:
            results = col.query(
                query_texts=[search_query],
                n_results=1,
                where={"$and": [
                    {"rating": {"$gte": min_rating}},
                    {"rating": {"$lte": max_rating}}
                ]}
            )
            
            if results["documents"] and len(results["documents"][0]) > 0:
                doc = results["documents"][0][0]
                meta = results["metadatas"][0][0]
                context_str = f"**Problem Retrieved from Database:** {meta.get('name', 'Unknown')}\n**Rating:** {meta.get('rating', 'Unrated')}\n**Tags:** {meta.get('tags', '')}\n\n**Problem Description:**\n{doc}"
            else:
                context_str = "No specific problems matched those exact constraints in the database. Please offer a conceptual challenge instead."
        except Exception as e:
            print(f"Chroma Query Error: {e}")
            context_str = "Database connection error."

    presentation_prompt = f"""
    {system_prompt}
    
    The user asked for a problem. You autonomously queried the database and found this:
    {context_str}
    
    INSTRUCTION: Introduce this problem to the user perfectly in your persona's character. 
    Explain exactly WHY you chose this specific problem for them based on their profile. 
    Do not give them the solution. Format it nicely with markdown.
    """
    
    try:
        final_response = safe_gemini_call(
            client=client,
            model='gemini-2.5-flash',
            contents=presentation_prompt
        )
        return final_response.text
    except Exception as e:
        print(f"Presentation LLM Error: {e} - Falling back to native markdown formatting.")
        if context_str and "error" not in context_str.lower():
            fallback_message = f"{context_str}\n\n*(Note: Your AI Coach is currently unavailable due to high server demand, but here is your requested problem directly from the database!)*"
        else:
            fallback_message = "*(Note: Your AI Coach is currently unavailable due to high server demand. Additionally, no matching problems were found in the database. Please try again later.)*"
            
        return fallback_message