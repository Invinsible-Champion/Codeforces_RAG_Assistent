import json
from ml_engine import analyze_user_profile
from chat_engine import generate_chat_response

def test_backend_pipeline():
    print("="*60)
    print("🧪 STAGE 1: VERIFYING ML ENGINE")
    print("="*60)
    
    # 1. Pick a real Codeforces handle to test. 
    # (If you have a personal account, put your handle here!)
    test_handle = "nishchay351" 
    print(f"[*] Fetching API and building ML Profile for: {test_handle}")
    
    profile_result = analyze_user_profile(test_handle)
    
    if "error" in profile_result:
        print(f"[-] ML Engine Failed: {profile_result['error']}")
        return
        
    print("[+] ML Engine Success! Here is the extracted profile:\n")
    
    # Print it beautifully so you can visually verify the metrics
    print(json.dumps({
        "Handle": profile_result["handle"],
        "Cluster": profile_result["cluster"],
        "Persona": profile_result["persona_name"],
        "System Prompt": profile_result["system_prompt"][:100] + "...", # Truncate for terminal
        "Metrics": profile_result["metrics"]
    }, indent=4))
    
    print("\n" + "="*60)
    print("🧪 STAGE 2: VERIFYING AGENTIC CHAT ENGINE (RAG)")
    print("="*60)
    
    # 2. Test a normal conversational message (Should NOT trigger ChromaDB)
    print("[*] Test A: Sending a conceptual chat message...")
    chat_message = "I am struggling to understand when to use Dijkstra vs BFS. Can you explain?"
    print(f'User: "{chat_message}"')
    
    chat_response = generate_chat_response(message=chat_message, user_profile=profile_result)
    print(f"\nAI Coach:\n{chat_response}")
    print("-" * 60)
    
    # 3. Test a problem request (SHOULD trigger the JSON router and ChromaDB)
    print("\n[*] Test B: Sending a problem request...")
    problem_message = "I think I'm ready. Give me a problem to practice my weaknesses."
    print(f'User: "{problem_message}"')
    
    problem_response = generate_chat_response(message=problem_message, user_profile=profile_result)
    print(f"\nAI Coach:\n{problem_response}")
    print("="*60)

if __name__ == "__main__":
    test_backend_pipeline()