import os
import re
import json
import time
import random
import requests
from bs4 import BeautifulSoup, Tag, NavigableString
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Configure checkpoints directory
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CHECKPOINT_FILE = os.path.join(DATA_DIR, "scraped_editorials.json")
os.makedirs(DATA_DIR, exist_ok=True)

def load_checkpoint():
    """Load JSON mapping problem_id to tutorial text/errors."""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    return {}

def save_checkpoint(data):
    """Save the current state to prevent duplicate scraping on crash."""
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f, indent=4)

def init_driver():
    """Phase 1: Initialize undetected-chromedriver with robust defaults."""
    options = uc.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,720")
    
    print("Initialize undetected_chromedriver (version_main=146)")
    # Explicit mapping to host machine Chrome version to bypass version block
    driver = uc.Chrome(options=options, version_main=146)
    return driver

def get_problems_to_scrape(limit=300):
    """Fetch base problem metadata from Codeforces to iterate over."""
    url = "https://codeforces.com/api/problemset.problems"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data.get("status") == "OK":
            return data["result"]["problems"][:limit]
    return []

def clean_html_mathjax_artifacts(html_parts):
    """Phase 3: Deep HTML Cleanup and MathJax format preservation."""
    soup = BeautifulSoup("<div>" + "".join(str(p) for p in html_parts) + "</div>", "html.parser")
    
    # Remove C++ Solutions
    for pre in soup.find_all("pre"):
        pre.decompose()

    # Convert MathJax Raw LaTeX into LLM-friendly standard markdown math wraps
    for math in soup.find_all("script", type="math/tex"):
        math_text = math.get_text()
        math.replace_with(f"$ {math_text} $")

    # Remove duplicated visually rendered blocks of the LaTeX
    for el in soup.select(".MathJax"):
        el.decompose()

    # Delete lingering loader text (using string exact matches)
    for tag in soup.find_all(string=re.compile("Tutorial is loading...", re.IGNORECASE)):
        tag.extract()

    # Crucial formatting: Emulate HTML spacing dynamically with raw newlines so it survives `get_text`
    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "ul", "ol", "li", "div"]):
        tag.insert_after("\n")
    for br in soup.find_all("br"):
        br.replace_with("\n")

    return soup

def isolate_problem_editorial(driver, contest_id, index, problem_name):
    """Phase 2: 2-Step scrape utilizing Selenium's wait loops to bypass loader tricks."""
    problem_id = f"{contest_id}{index}"
    
    # STEP 1: Route to statement to fetch native Tutorial URL securely.
    start_url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
    driver.get(start_url)
    
    try:
        # Wait for sidebar materials
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".roundbox"))
        )
    except Exception:
        return {"error": "Timeout waiting for .roundbox materials sidebar"}

    links = driver.find_elements(By.CSS_SELECTOR, ".roundbox a")
    tut_url = None
    for link in links:
        text = link.text.lower()
        if "tutorial" in text or "editorial" in text or "analysis" in text:
            tut_url = link.get_attribute("href")
            break
            
    if not tut_url:
        return {"error": "No sidebar Tutorial link found"}

    # STEP 2: Isolate Blog
    driver.get(tut_url)
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".ttypography"))
        )
    except Exception:
        return {"error": "Timeout waiting for blog content .ttypography"}

    # Execute custom JS to expand hidden elements
    driver.execute_script("document.querySelectorAll('.spoiler-title').forEach(el => el.click());")
    
    # Wait for the network calls to fetch hidden code blocks and spoilers to append to dom
    time.sleep(4)
    
    page_source = driver.page_source
    soup = BeautifulSoup(page_source, "html.parser")
    content = soup.select_one(".ttypography")
    
    if not content:
        return {"error": "Cannot find .ttypography container"}

    # Target Problem Index & Next Index Stop Condition
    idx_upper = index.upper()
    next_idx = chr(ord(idx_upper) + 1) if len(idx_upper) == 1 and idx_upper.isalpha() else ""

    headers = content.find_all(["h1", "h2", "h3", "h4", "h5", "b", "strong", "p"])
    
    name_escaped = re.escape(problem_name)
    idx_escaped = re.escape(idx_upper)
    
    target_matchers = [
        re.compile(rf'^{idx_escaped}[\.\s\-—:]', re.IGNORECASE),
        re.compile(rf'^Problem\s+{idx_escaped}', re.IGNORECASE),
        re.compile(rf'{name_escaped}', re.IGNORECASE)
    ]
    
    stop_regex = re.compile(rf'\b\d{{1,4}}[B-Z]\b', re.IGNORECASE)
    next_problem_stop = re.compile(rf'\b{next_idx}\b', re.IGNORECASE) if next_idx else None

    # Sweep for Target Header
    start_node = None
    for header in headers:
        text = header.get_text(strip=True)
        if any(p.search(text) for p in target_matchers):
            start_node = header
            break

    if not start_node:
        return {"error": "Problem header not found inside blog"}

    # Collect traversing siblings
    elements = []
    current = start_node
    while current:
        current = current.next_sibling
        if current is None:
            break
            
        if isinstance(current, Tag):
            # Evaluate dynamically configured Stop Conditions
            if current.name in ["h1", "h2", "h3", "h4"]:
                break
                
            if current.name == "p" and current.find("b"):
                bold_text = current.find("b").get_text(strip=True)
                if next_problem_stop and next_problem_stop.search(bold_text):
                    break
                    
            text = current.get_text(strip=True)
            if stop_regex.search(text) and text != problem_name:
                break
            if next_problem_stop and next_problem_stop.search(text):
                if current.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'b', 'strong']:
                    break
        elements.append(current)

    # Phase 3: Cleanup the gathered blocks
    cleaned_soup = clean_html_mathjax_artifacts(elements)
    
    # Phase 4: Final textual parsing 
    # Force spaces around block boundaries to prevent merge
    raw_text = cleaned_soup.get_text(separator=' ', strip=True)
    
    # Use re module to cleanup trailing spaces over multi-lines
    formatted_text = re.sub(r' {2,}', ' ', raw_text)
    formatted_text = re.sub(r'\n{3,}', '\n\n', formatted_text)
    formatted_text = formatted_text.strip()
    
    if len(formatted_text) < 10:
        return {"error": "Extracted problem text suspiciously short."}
        
    return {"text": formatted_text, "html": str(cleaned_soup)}


def run_bulk_scraper():
    """Phase 5: Bulk Logic"""
    problems = get_problems_to_scrape(limit=100)
    if not problems:
        print("Scraper Failed: Could not get metadata from Codeforces JSON API")
        return
        
    checkpoint = load_checkpoint()
    
    requests_issued = 0
    driver = None
    
    for prob in problems:
        contest_id = str(prob["contestId"])
        index = prob["index"]
        name = prob.get("name", "")
        pid = f"{contest_id}{index}"
        
        # Deduplication condition
        if pid in checkpoint and ("text" in checkpoint[pid] or checkpoint[pid].get("error") == "No sidebar Tutorial link found"):
            print(f"Skipping {pid}: Already checkpointed.")
            continue
            
        if driver is None:
            print("Waking up scraper driver core...")
            driver = init_driver()
            
        print(f"Scraping -> {pid}: {name}")
        
        # Protected execution isolation
        try:
            result = isolate_problem_editorial(driver, contest_id, index, name)
        except Exception as e:
            result = {"error": f"Internal exception: {str(e)}"}
            
        # Secure the result safely 
        checkpoint[pid] = result
        save_checkpoint(checkpoint)
        
        if "error" in result:
            print(f"  [Error]: {result['error']}")
        else:
            print(f"  [OK]: Extracted {len(result['text'])} characters successfully")
            
        # Stealth human delay loop 
        delay = random.uniform(5, 10)
        print(f"  Sleeping {delay:.2f}s...")
        time.sleep(delay)
        
        requests_issued += 1
        
        # Memory Management: Cyclical resets to curb memory leak from undetected chromedriver
        if requests_issued >= 50:
            print("Loop condition met (~50 req). Tearing down webdriver to dump Chrome RAM...")
            driver.quit()
            driver = None
            requests_issued = 0

    if driver:
        print("Tearing down final driver handle...")
        driver.quit()
        
    print("Background Scraping pipeline finished!")

if __name__ == "__main__":
    run_bulk_scraper()
