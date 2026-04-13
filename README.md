# 🏋️ Codeforces Coach — AI-Powered Practice Recommender

An intelligent Codeforces training system that analyzes a user's competitive programming history, classifies them into a behavioral archetype using **Gaussian Mixture Models (GMM)**, and recommends personalized practice problems using a **two-stage retrieval + XGBoost ranking pipeline** — all presented by a persona-driven **Gemini LLM coach**.

---

## ✨ Features

| Feature | Description |
|---|---|
| **ML Profiling** | Scrapes Codeforces API, engineers 16 behavioral features (accuracy, tilt speed, tag preferences, etc.), and classifies users into 1 of 10 archetypes via GMM clustering |
| **Two-Stage Recommender** | ChromaDB semantic retrieval → XGBoost re-ranking with 20 user×problem synergy features |
| **Negative Pruning** | Automatically filters out problems the user has already attempted |
| **Persona-Driven Presentation** | Each archetype has a custom system prompt; Gemini presents the problem in-character |
| **Analytics Dashboard** | View your archetype, accuracy, tilt speed, one-shot rate, strengths & weaknesses |

---

## 🏗️ Architecture

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Frontend   │────▶│  FastAPI     │────▶│  ML Engine   │────▶│  GMM Model  │
│  (HTML/JS)  │     │  (main.py)  │     │ (ml_engine)  │     │  (sklearn)  │
└─────────────┘     └──────┬──────┘     └──────────────┘     └─────────────┘
                           │
                           ▼
                    ┌──────────────┐     ┌──────────────┐     ┌─────────────┐
                    │ Chat Engine  │────▶│  ChromaDB    │────▶│  XGBoost    │
                    │(chat_engine) │     │  (Retrieval) │     │  (Ranking)  │
                    └──────┬──────┘     └──────────────┘     └─────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  Gemini LLM  │
                    │(Presentation)│
                    └──────────────┘
```

---

## 📁 Project Structure

```
cf_coach/
├── backend/
│   ├── main.py                # FastAPI app with /api/analyze and /api/get_problem
│   ├── ml_engine.py           # CF API scraping, feature engineering, GMM classification
│   ├── chat_engine.py         # Query Builder → ChromaDB → XGBoost → Gemini presentation
│   ├── config.py              # Centralized env config (dotenv loader)
│   ├── persona_prompts.py     # 10 archetype persona definitions & system prompts
│   ├── pipeline.py            # ChromaDB data ingestion pipeline
│   ├── models.py              # SQLAlchemy models (if using Postgres)
│   ├── test_pipeline.py       # End-to-end CLI tester
│   ├── requirements.txt       # Python dependencies
│   ├── .env                   # API keys (not tracked)
│   ├── chroma_data/           # ChromaDB vector store (not tracked)
│   └── static/
│       ├── index.html         # Two-tab UI (Practice + Analytics)
│       ├── style.css          # Glassmorphism dark theme
│       └── app.js             # Frontend logic & pipeline step animations
│
├── train/
│   ├── data_extraction.ipynb  # Codeforces bulk data scraping
│   ├── feature_engg.ipynb     # Feature engineering & EDA
│   ├── gmm_train.ipynb        # GMM clustering training
│   ├── t_rank.ipynb           # XGBoost ranker training
│   ├── stats.ipynb            # Statistical analysis
│   ├── persona_gmm_model.pkl  # Trained GMM model (not tracked)
│   ├── persona_scaler.pkl     # StandardScaler (not tracked)
│   └── xgboost_ranker_v2.json # XGBoost weights (not tracked)
│
├── .gitignore
└── README.md
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- A [Google Gemini API Key](https://aistudio.google.com/app/apikey)

### 1. Clone & Install

```bash
git clone https://github.com/<your-username>/cf_coach.git
cd cf_coach/backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

Create `backend/.env`:

```env
GEMINI_API_KEY=your_gemini_api_key_here
CHROMA_COLLECTION_NAME=cf_problems
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

### 3. Prepare Data

You need two things before running:

1. **ChromaDB vector store** — Run the ingestion pipeline:
   ```bash
   python pipeline.py
   ```

2. **ML model weights** — Train from the notebooks in `train/`:
   - `gmm_train.ipynb` → produces `persona_gmm_model.pkl` and `persona_scaler.pkl`
   - `t_rank.ipynb` → produces `xgboost_ranker_v2.json`

### 4. Run the Server

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### 5. Test the Pipeline (CLI)

```bash
python test_pipeline.py
```

---

## 🔧 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/analyze` | Scrape CF handle → ML feature extraction → GMM classification |
| `POST` | `/api/get_problem` | Full pipeline: Analyze → Query Build → Retrieve → Rank → Present |

Both endpoints accept `{"handle": "codeforces_username"}`.

---

## 🧠 How the Recommendation Pipeline Works

1. **ML Profile** (`ml_engine.py`): Scrapes Codeforces API for all user submissions, engineers 16 features (accuracy, TLE rate, tag preferences, tilt speed, etc.), scales them, and classifies into 1 of 10 behavioral archetypes via a pre-trained GMM.

2. **Query Building** (`chat_engine.py` Step 1): Gemini LLM reads the user profile and generates targeted ChromaDB search keywords + rating bounds. Falls back to the user's weakest tag on failure.

3. **Candidate Retrieval** (Step 2): ChromaDB semantic search retrieves 50 candidate problems within the rating window.

4. **Negative Pruning** (Step 3): Filters out every problem the user has already attempted on Codeforces.

5. **XGBoost Ranking** (Step 4): Scores remaining candidates using 20 features (8 user metrics + 3 problem stats + 1 rating delta + 8 tag synergy features). The highest-confidence problem wins.

6. **Presentation** (Step 5): Gemini LLM presents the selected problem in the persona's character, explaining *why* it was chosen for the user.

---

## 📊 Archetypes

| # | Name | Rating Range | Key Trait |
|---|------|-------------|-----------|
| 0 | The Cautious Beginner | ~1090 | High accuracy, weak Data Structures |
| 1 | The Impatient Novice | ~1170 | Over-relies on Greedy, high abandonment |
| 2 | The Persistent Grinder | ~970 | Great grit, lacks theory |
| 3 | The Fickle Advanced | ~1560 | Strong skills, overwhelmed easily |
| 4 | The Stubborn Graph Hacker | ~1665 | Graph expert, panic submitter |
| 5 | The Comfort Zone Camper | ~880 | Pads stats with easy problems |
| 6 | The Methodical Optimizer | ~1190 | Disciplined, ready for next level |
| 7 | The Solid Specialist | ~1420 | DP & Graph focused |
| 8 | The Advanced Precisionist | ~1560 | One-shot accuracy, clean code |
| 9 | The Frustrated Flounderer | ~980 | Guesses often, tilts quickly |

---

## 🛠️ Tech Stack

- **Backend**: FastAPI, Uvicorn
- **ML**: scikit-learn (GMM), XGBoost, Pandas
- **Vector DB**: ChromaDB + SentenceTransformers (all-MiniLM-L6-v2)
- **LLM**: Google Gemini 2.5 Flash
- **Frontend**: Vanilla HTML/CSS/JS with glassmorphism design

---

## 📝 License

This project is for educational purposes.
