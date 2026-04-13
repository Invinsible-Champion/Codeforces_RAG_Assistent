import os
import json
from ml_engine import analyze_user_profile
from chat_engine import fetch_practice_problem

def run_pipeline_test():
    print("\n" + "="*60)
    print("🚀 AI COACH END-TO-END PIPELINE TESTER 🚀")
    print("="*60)

    # Make sure the API key is loaded before we start
    if not os.getenv("GEMINI_API_KEY"):
        print("[-] WARNING: GEMINI_API_KEY is not set in your environment variables!")
        print("[-] Please run: export GEMINI_API_KEY='your_key' before testing.")
        return

    handle = input("Enter a Codeforces Handle (e.g., tourist, jiangly): ").strip()
    if not handle:
        print("[-] Handle cannot be empty. Exiting.")
        return

    # --- STEP 1: ML ENGINE ---
    print(f"\n[1/3] 🔍 Scraping Codeforces & Extracting ML Features for '{handle}'...")
    user_profile = analyze_user_profile(handle)

    if "error" in user_profile:
        print(f"\n❌ Pipeline Failed at ML Engine: {user_profile['error']}")
        return

    print("[+] ML Profile Successfully Built!")
    print(f"    -> Persona: {user_profile['persona_name']} (Cluster {user_profile['cluster']})")
    print(f"    -> Match Confidence: {user_profile.get('cluster_probability', 0.0)*100:.1f}%")
    print(f"    -> User Rating: {user_profile['current_rating']}")
    print(f"    -> Historical Accuracy: {user_profile['metrics']['accuracy']*100:.1f}%")
    print(f"    -> Attempted Problems Filter Loaded: {len(user_profile.get('attempted_problems', []))} problems")

    # --- STEP 2: CHAT ENGINE (RETRIEVAL & RANKING) ---
    print("\n[2/3] 🧠 Executing Two-Stage Recommender (ChromaDB + XGBoost)...")
    try:
        recommendation = fetch_practice_problem(user_profile)
    except Exception as e:
        print(f"\n❌ Pipeline Crashed at Recommendation Engine: {e}")
        return

    if not recommendation.get("problem_details"):
        print("\n⚠️ Warning: The engine could not find a valid problem.")
        print(f"Engine Output: {recommendation.get('message')}")
        return

    print("[+] Problem Successfully Ranked and Selected!")
    print(f"    -> Selected Problem: {recommendation['problem_details'].get('name')}")
    print(f"    -> Target Rating: {recommendation['problem_details'].get('rating')}")

    # --- STEP 3: FINAL PRESENTATION ---
    print("\n[3/3] 🎙️ Gemini Presentation Generation Complete.\n")
    print("="*60)
    print("FINAL LLM OUTPUT TO FRONTEND:")
    print("-" * 60)
    print(recommendation["message"])
    print("="*60)
    
    print("\n✅ Pipeline execution complete. If this looks good, you are ready to plug it into FastAPI!")

if __name__ == "__main__":
    run_pipeline_test()