import os
import json
import time
import pandas as pd
import xgboost as xgb
from google import genai
from google.genai import types
import chromadb
from chromadb.utils import embedding_functions
from config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME, EMBEDDING_MODEL
from pathlib import Path

# Suppress warnings
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

BASE_DIR = Path(__file__).resolve().parent

# --- Global Loaders ---
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

ranker_model = xgb.XGBClassifier()
try:
    # Load the V2 model we just trained
    ranker_model.load_model(str(BASE_DIR.parent / "train" / "xgboost_ranker_v2.json"))
except Exception as e:
    print(f"Warning: Could not load XGBoost Ranker: {e}")

# --- Helper Functions ---
def clean_json_response(raw_text):
    text = raw_text.strip()
    # Using string multiplication to prevent UI markdown parser glitches
    json_prefix = "`" * 3 + "json"
    bt_prefix = "`" * 3
    
    if text.startswith(json_prefix):
        text = text[7:]
    if text.startswith(bt_prefix):
        text = text[3:]
    if text.endswith(bt_prefix):
        text = text[:-3]
    return text.strip()

def safe_gemini_call(client, model, contents, config=None, retries=3):
    """Wrapper to handle 503 and 429 rate limit errors."""
    for attempt in range(retries):
        try:
            return client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as e:
            if "503" in str(e) or "429" in str(e):
                if attempt < retries - 1:
                    sleep_time = 2 ** attempt
                    time.sleep(sleep_time)
                    continue
            raise e

def get_target_rating(user_profile):
    avg_rating = int(user_profile.get("avg_rating", 1200))
    curr_rating = int(user_profile.get("current_rating", 0))
    return avg_rating if curr_rating == 0 else int((avg_rating + curr_rating) / 2)

def get_weakest_domain(metrics):
    if not metrics: return "arrays logic"
    domains = {
        "math": metrics.get("math_pref", 1),
        "dynamic programming": metrics.get("dp_pref", 1),
        "graphs and trees": metrics.get("graph_pref", 1),
        "binary search": metrics.get("binary_pref", 1),
        "data structures": metrics.get("datastruct_pref", 1)
    }
    return min(domains, key=domains.get)

# --- Main Engine ---
def fetch_practice_problem(user_profile: dict):
    """Straight-line execution: Build Query -> Fetch Candidates -> Rank -> Present."""
    
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    
    system_prompt = user_profile.get("system_prompt", "You are an AI competitive programming coach.")
    question_rating = get_target_rating(user_profile)
    weakness_fallback = get_weakest_domain(user_profile.get("metrics", {}))

    # =====================================================================
    # STEP 1: QUERY BUILDER (LLM) - NO INTENT ROUTING NEEDED
    # =====================================================================
    query_builder_prompt = f"""
    {system_prompt}
    
    TASK: Generate a database search query to find the perfect practice problem for this user.
    Target their specific algorithmic weaknesses based on their ML Profile.
    
    You MUST respond with ONLY a valid JSON object. Do not add markdown or text.
    Format:
    {{"search_query": "specific algorithmic keywords", "min_rating": {max(800, question_rating - 100)}, "max_rating": {question_rating + 200}}}
    """
    
    try:
        router_res = safe_gemini_call(
            client=client,
            model='gemini-2.5-flash',
            contents=query_builder_prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        parsed_intent = json.loads(clean_json_response(router_res.text))
    except Exception as e:
        print(f"[*] Query Builder failed, using ML fallback. Error: {e}")
        parsed_intent = {
            "search_query": weakness_fallback,
            "min_rating": max(800, question_rating - 100),
            "max_rating": question_rating + 200
        }
    
    # =====================================================================
    # STEP 2: CANDIDATE GENERATION (ChromaDB)
    # =====================================================================
    search_query = parsed_intent.get("search_query", weakness_fallback)
    min_rating = int(parsed_intent.get("min_rating", max(800, question_rating - 100)))
    max_rating = int(parsed_intent.get("max_rating", question_rating + 200))
    
    col = get_chroma_collection()
    context_str = ""
    problem_details = None
    
    if col:
        try:
            # Over-fetch 50 problems to give XGBoost plenty of options
            results = col.query(
                query_texts=[search_query],
                n_results=50, 
                where={"$and": [{"rating": {"$gte": min_rating}}, {"rating": {"$lte": max_rating}}]}
            )
            
            raw_candidates = results.get("metadatas", [[]])[0]
            raw_docs = results.get("documents", [[]])[0]
            
            # =====================================================================
            # STEP 3: NEGATIVE PRUNING & FEATURE ASSEMBLY
            # =====================================================================
            attempted_set = set(user_profile.get("attempted_problems", []))
            metrics = user_profile.get("metrics", {})
            scoring_data = []
            fresh_candidates = []
            fresh_docs = []
            
            for idx, meta in enumerate(raw_candidates):
                # Only process problems the user has NEVER submitted code for
                if meta.get("problem_id") not in attempted_set:
                    fresh_candidates.append(meta)
                    fresh_docs.append(raw_docs[idx])
                    
                    tags = meta.get("tags", "").lower()
                    rating = int(meta.get("rating", 0))
                    
                    # Compute Binary Tags
                    is_dp = 1 if "dp" in tags else 0
                    is_math = 1 if any(t in tags for t in ["math", "number theory", "combinatorics"]) else 0
                    is_graph = 1 if any(t in tags for t in ["graphs", "trees", "dfs"]) else 0
                    is_brute = 1 if any(t in tags for t in ["brute force", "implementation", "hashing"]) else 0
                    is_greedy = 1 if any(t in tags for t in ["greedy", "two pointers", "sortings"]) else 0
                    is_binary = 1 if "binary search" in tags else 0
                    is_cons = 1 if any(t in tags for t in ["constructive", "strings", "interactive"]) else 0
                    is_datastruct = 1 if any(t in tags for t in ["data structures", "dsu"]) else 0

                    # Assemble the exact 20-feature row for XGBoost
                    row = {
                        'accuracy': metrics.get('accuracy', 0.5),
                        'optimization_struggle': metrics.get('optimization_struggle', 0),
                        'avg_solved_rating': metrics.get('avg_solved_rating', 1200),
                        'abandonment_rate': metrics.get('abandonment_rate', 0),
                        'one_shot_rate': metrics.get('one_shot_rate', 0),
                        'tilt_speed_seconds': metrics.get('tilt_speed_seconds', 900),
                        'recent_win_rate': metrics.get('recent_win_rate', 0.5),
                        'persistence_index': metrics.get('persistence_index', 1.0),
                        'problem_rating': rating,
                        'global_solve_rate': meta.get('global_solve_rate', 0.45), # Safe default
                        'avg_attempts_per_user': meta.get('avg_attempts_per_user', 2.0), # Safe default
                        'rating_delta': rating - metrics.get('avg_solved_rating', 1200),
                        'dp_synergy': is_dp * metrics.get('dp_pref', 0),
                        'math_synergy': is_math * metrics.get('math_pref', 0),
                        'graph_synergy': is_graph * metrics.get('graph_pref', 0),
                        'brute_synergy': is_brute * metrics.get('brute_pref', 0),
                        'greedy_synergy': is_greedy * metrics.get('greedy_pref', 0),
                        'binary_synergy': is_binary * metrics.get('binary_pref', 0),
                        'cons_synergy': is_cons * metrics.get('cons_pref', 0),
                        'datastruct_synergy': is_datastruct * metrics.get('datastruct_pref', 0)
                    }
                    scoring_data.append(row)
            
            # =====================================================================
            # STEP 4: XGBOOST RANKING
            # =====================================================================
            if not fresh_candidates:
                context_str = "Error: User has solved all matching problems in this bracket."
            else:
                df_scoring = pd.DataFrame(scoring_data)
                
                # Enforce exact column order from training
                ordered_features = ['accuracy', 'optimization_struggle', 'avg_solved_rating', 'abandonment_rate', 'one_shot_rate', 'tilt_speed_seconds', 'recent_win_rate', 'persistence_index', 'problem_rating', 'global_solve_rate', 'avg_attempts_per_user', 'rating_delta', 'dp_synergy', 'math_synergy', 'graph_synergy', 'brute_synergy', 'greedy_synergy', 'binary_synergy', 'cons_synergy', 'datastruct_synergy']
                df_scoring = df_scoring[ordered_features]
                
                # Predict probability of success (y=1)
                probabilities = ranker_model.predict_proba(df_scoring)[:, 1]
                
                for i in range(len(fresh_candidates)):
                    fresh_candidates[i]["xgb_score"] = float(probabilities[i])
                    fresh_candidates[i]["doc_text"] = fresh_docs[i]
                    
                ranked_candidates = sorted(fresh_candidates, key=lambda x: x["xgb_score"], reverse=True)
                winning_problem = ranked_candidates[0]
                
                problem_details = winning_problem
                doc = winning_problem.pop("doc_text")
                score = winning_problem.pop("xgb_score")
                
                print(f"[+] XGBoost selected {problem_details.get('name')} (Confidence Score: {score:.3f})")
                context_str = f"**Problem Retrieved from Database:** {problem_details.get('name', 'Unknown')}\n**Rating:** {problem_details.get('rating', 'Unrated')}\n**Tags:** {problem_details.get('tags', '')}\n\n**Problem Description:**\n{doc}"

        except Exception as e:
            print(f"Chroma/XGBoost Pipeline Error: {e}")
            context_str = "Database connection or ranking error."

    # =====================================================================
    # STEP 5: THE COACH'S PRESENTATION (LLM)
    # =====================================================================
    if not problem_details:
        return {"message": "I couldn't find a fresh problem for your specific constraints. Try broadening your practice!", "problem_details": None}

    presentation_prompt = f"""
    {system_prompt}
    
    You are presenting this freshly retrieved Codeforces problem to the user:
    {context_str}
    
    INSTRUCTION: Introduce this problem perfectly in your persona's character. 
    Explain exactly WHY you chose this specific problem based on their ML profile weaknesses. 
    Do not give them the solution. Be concise and format nicely with markdown.
    """
    
    try:
        final_response = safe_gemini_call(
            client=client,
            model='gemini-2.5-flash',
            contents=presentation_prompt
        )
        return {"message": final_response.text, "problem_details": problem_details}
    except Exception as e:
        print(f"Presentation LLM Error: {e}")
        fallback_msg = f"**I found a problem for you: {problem_details.get('name')}**\n\n*(Your AI Coach is experiencing server load, but here is the raw problem)*\n\n{context_str}"
        return {"message": fallback_msg, "problem_details": problem_details}