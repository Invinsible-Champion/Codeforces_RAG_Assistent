from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from ml_engine import analyze_user_profile
from chat_engine import fetch_practice_problem
from typing import Dict, Any

app = FastAPI(title="CF Coach API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ProfileRequest(BaseModel):
    handle: str



@app.post("/api/analyze")
def analyze_profile(req: ProfileRequest):
    result = analyze_user_profile(req.handle)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.post("/api/get_problem")
def get_problem(req: ProfileRequest):
    result = analyze_user_profile(req.handle)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    response = fetch_practice_problem(result)
    if "error" in response:
        raise HTTPException(status_code=500, detail=response["error"])
        
    return {
        "message": response["message"], 
        "profile": result, 
        "problem_details": response.get("problem_details")
    }



# Create static directory if it doesn't exist
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)

# Mount it last as a fallback for the frontend
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
