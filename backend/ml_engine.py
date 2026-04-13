import pandas as pd
import requests
import joblib
from pathlib import Path
from persona_prompts import PERSONA_MAP

# Setup paths based on project structure
BASE_DIR = Path(__file__).resolve().parent
TRAIN_DIR = BASE_DIR.parent / "train"

SCALER_PATH = TRAIN_DIR / "persona_scaler.pkl"
MODEL_PATH = TRAIN_DIR / "persona_gmm_model.pkl"

# Load ML artifacts globally
try:
    scaler = joblib.load(SCALER_PATH)
    gmm_model = joblib.load(MODEL_PATH)
except Exception as e:
    print(f"Warning: Could not load ML artifacts: {e}")
    scaler, gmm_model = None, None

def analyze_user_profile(handle: str):
    """Fetches submissions, calculates features, and returns the LLM Persona Prompt."""
    
    # 1. Fetch Submissions (user.status)
    status_url = f"https://codeforces.com/api/user.status?handle={handle}"
    try:
        response = requests.get(status_url, timeout=15).json()
        if response.get("status") != "OK":
            return {"error": f"CF API Error: {response.get('comment')}"}
    except Exception as e:
        return {"error": f"Failed to connect to Codeforces: {str(e)}"}

    subs = response["result"]
    if not subs:
        return {"error": "No submissions found for this handle."}

    # 2. Fetch Current Rating (user.info)
    info_url = f"https://codeforces.com/api/user.info?handles={handle}"
    current_rating = 0  # Default to 0 if unrated or if the API call fails
    try:
        info_response = requests.get(info_url, timeout=15).json()
        if info_response.get("status") == "OK":
            user_info = info_response["result"][0]
            current_rating = user_info.get("rating", 0)  # Use .get() to safely handle unrated users
    except Exception as e:
        print(f"Warning: Could not fetch current rating for {handle}: {e}")

    # --- Data Extraction ---
    user_subs_data = []
    for sub in subs:
        tags_list = sub.get("problem", {}).get("tags", [])
        tags_str = "|".join(tags_list)
        user_subs_data.append({
            "problem_id": f"{sub['problem'].get('contestId', '')}{sub['problem'].get('index', '')}",
            "rating": sub["problem"].get("rating", 0),
            "verdict": sub.get("verdict", "UNKNOWN"),
            "tags": tags_str,
            "creation_time": sub.get("creationTimeSeconds", 0)
        })
    
    df = pd.DataFrame(user_subs_data)
    df = df.sort_values(by=["problem_id", "creation_time"])
    
    total_subs = len(df)
    if total_subs < 10:
        return {"error": "Not enough submissions to build an ML profile."}

    # --- Feature Engineering ---
    ok_subs = len(df[df["verdict"] == "OK"])
    accuracy = ok_subs / total_subs
    tle_subs = len(df[df["verdict"] == "TIME_LIMIT_EXCEEDED"])
    opt_struggle = tle_subs / total_subs
    
    solved_df = df[(df["verdict"] == "OK") & (df["rating"] > 0)]
    avg_solved_rating = solved_df["rating"].mean() if len(solved_df) > 0 else 0
    
    unique_attempted = df["problem_id"].nunique()
    unique_solved = solved_df["problem_id"].nunique()
    abandonment_rate = (unique_attempted - unique_solved) / unique_attempted if unique_attempted > 0 else 0

    first_attempts = df.drop_duplicates(subset=["problem_id"], keep="first")
    one_shot_rate = len(first_attempts[first_attempts["verdict"] == "OK"]) / unique_attempted if unique_attempted > 0 else 0

    failed_subs = df[df["verdict"] != "OK"].copy()
    failed_subs["time_diff"] = failed_subs.groupby("problem_id")["creation_time"].diff()
    rapid_fails = failed_subs[(failed_subs["time_diff"] > 0) & (failed_subs["time_diff"] < 900)]
    tilt_factor = rapid_fails["time_diff"].mean() if len(rapid_fails) > 0 else 900

    df["tags"] = df["tags"].fillna("")
    def calc_tag_pref(keyword):
        tagged_subs = df[df["tags"].str.contains(keyword, case=False, regex=True)]
        return len(tagged_subs) / total_subs if total_subs > 0 else 0

    features = {
        "accuracy": accuracy,
        "optimization_struggle": opt_struggle,
        "avg_solved_rating": avg_solved_rating,
        "abandonment_rate": abandonment_rate,
        "one_shot_rate": one_shot_rate,
        "tilt_speed_seconds": tilt_factor,
        "math_pref": calc_tag_pref("math|number theory|combinatorics"),
        "dp_pref": calc_tag_pref("dp"),
        "graph_pref": calc_tag_pref("graphs|trees|dfs"),
        "brute_pref": calc_tag_pref("brute force|implementation|hashing"),
        "greedy_pref": calc_tag_pref("greedy|two pointers|sortings"),
        "binary_pref": calc_tag_pref("binary search"),
        "cons_pref": calc_tag_pref("constructive|strings|interactive"),
        "datastruct_pref": calc_tag_pref("data structures|dsu"),
    }

    ordered_cols = [
        "accuracy", "optimization_struggle", "avg_solved_rating", "abandonment_rate", "one_shot_rate",
        "tilt_speed_seconds", "math_pref", "dp_pref", "graph_pref", "brute_pref", "greedy_pref",
        "binary_pref", "cons_pref", "datastruct_pref"
    ]
    x_df = pd.DataFrame([features])[ordered_cols]
    
    if scaler is None or gmm_model is None:
        return {"error": "ML Models not loaded on backend."}

    # --- ML Classification ---
    x_scaled = scaler.transform(x_df)
    cluster = int(gmm_model.predict(x_scaled)[0])
    
    # Grab the exact prompt needed for the LLM
    persona_info = PERSONA_MAP.get(cluster, PERSONA_MAP[0])

    # --- Final Output ---
    return {
        "handle": handle,
        "cluster": cluster,
        "persona_name": persona_info["name"],
        "system_prompt": persona_info["system_prompt"],
        "avg_rating": avg_solved_rating,
        "current_rating": current_rating,  
        "metrics": features
    }