#!/usr/bin/env python3
"""
Scrapes HackerNews, arXiv, lobste.rs, and DEV.to for topics:
compilers, cloud computing, devops, PLs, AI/ML systems
Summarizes using free Hugging Face inference API
Generates a static index.html
"""

import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from html import escape

# ── topics ──────────────────────────────────────────────────────────────────
TOPICS = ["compiler", "cloud computing", "devops", "kubernetes", "llvm",
          "programming language", "mlops", "rust", "wasm", "linker",
          "systems programming", "infrastructure", "containerization"]

TOPIC_LABELS = {
    "compiler": "Compilers & PLs",
    "llvm": "Compilers & PLs",
    "linker": "Compilers & PLs",
    "programming language": "Compilers & PLs",
    "rust": "Compilers & PLs",
    "wasm": "Compilers & PLs",
    "cloud computing": "Cloud & Infra",
    "kubernetes": "Cloud & Infra",
    "infrastructure": "Cloud & Infra",
    "containerization": "Cloud & Infra",
    "devops": "DevOps & MLOps",
    "mlops": "DevOps & MLOps",
    "systems programming": "Systems",
    "llm": "AI/ML Systems",
    "ml": "AI/ML Systems",
}

CATEGORIES = ["Compilers & PLs", "Cloud & Infra", "DevOps & MLOps", "Systems", "AI/ML Systems", "Other"]

# ── helpers ──────────────────────────────────────────────────────────────────
def fetch_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 tech-news-aggregator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def fetch_text(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 tech-news-aggregator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(errors="replace")

def classify(title, text=""):
    combined = (title + " " + text).lower()
    for kw, label in TOPIC_LABELS.items():
        if kw in combined:
            return label
    return "Other"

def naive_summarize(title, text, max_words=40):
    """Fallback: first N words of the text, or just title."""
    if not text or len(text.strip()) < 30:
        return title
    words = text.split()
    snippet = " ".join(words[:max_words])
    if len(words) > max_words:
        snippet += "…"
    return snippet

def hf_summarize(text, max_len=80):
    """Free Hugging Face inference API — no key required for small usage."""
    if len(text.split()) < 30:
        return text
    payload = json.dumps({
        "inputs": text[:1000],
        "parameters": {"max_length": max_len, "min_length": 20, "do_sample": False}
    }).encode()
    url = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
            if isinstance(data, list) and data:
                return data[0].get("summary_text", text[:200])
    except Exception:
        pass
    return naive_summarize("", text)

# ── scrapers ─────────────────────────────────────────────────────────────────
def fetch_hackernews(limit=60):
    print("  → HackerNews...")
    items = []
    try:
        top = fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")[:limit]
        for story_id in top:
            try:
                s = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
                if not s or s.get("type") != "story":
                    continue
                title = s.get("title", "")
                url   = s.get("url", f"https://news.ycombinator.com/item?id={story_id}")
                text  = s.get("text", "")
                cat   = classify(title, text)
                if cat == "Other":
                    # filter: only keep if at least loosely related
                    combined = (title + text).lower()
                    if not any(kw in combined for kw in [
                        "program", "software", "server", "deploy", "build",
                        "docker", "git", "ci", "system", "database", "api",
                        "performance", "memory", "cpu", "gpu", "network"
                    ]):
                        continue
                items.append({
                    "source": "HackerNews",
                    "title": title,
                    "url": url,
                    "text": text,
                    "category": cat,
                    "score": s.get("score", 0),
                    "ts": s.get("time", 0),
                })
            except Exception:
                continue
            time.sleep(0.05)
    except Exception as e:
        print(f"    HN error: {e}")
    print(f"    {len(items)} items")
    return items

def fetch_arxiv():
    print("  → arXiv...")
    items = []
    queries = [
        "compiler optimization", "cloud computing systems",
        "devops automation", "large language model systems",
        "programming languages", "distributed systems"
    ]
    for q in queries:
        try:
            enc = urllib.parse.quote(q)
            url = (f"http://export.arxiv.org/api/query?search_query=all:{enc}"
                   f"&start=0&max_results=5&sortBy=submittedDate&sortOrder=descending")
            xml = fetch_text(url)
            entries = re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL)
            for e in entries:
                title_m = re.search(r"<title>(.*?)</title>", e, re.DOTALL)
                link_m  = re.search(r'<id>(.*?)</id>', e)
                summ_m  = re.search(r"<summary>(.*?)</summary>", e, re.DOTALL)
                if not title_m:
                    continue
                title = re.sub(r'\s+', ' ', title_m.group(1)).strip()
                link  = link_m.group(1).strip() if link_m else ""
                summ  = re.sub(r'\s+', ' ', summ_m.group(1)).strip() if summ_m else ""
                items.append({
                    "source": "arXiv",
                    "title": title,
                    "url": link,
                    "text": summ,
                    "category": classify(title, summ),
                    "score": 0,
                    "ts": 0,
                })
            time.sleep(0.3)
        except Exception as e:
            print(f"    arXiv error ({q}): {e}")
    print(f"    {len(items)} items")
    return items

def fetch_lobsters():
    print("  → lobste.rs...")
    items = []
    try:
        data = fetch_json("https://lobste.rs/hottest.json")
        for s in data:
            title = s.get("title", "")
            tags  = " ".join(s.get("tags", []))
            cat   = classify(title, tags)
            items.append({
                "source": "lobste.rs",
                "title": title,
                "url": s.get("url") or s.get("short_id_url", ""),
                "text": tags,
                "category": cat,
                "score": s.get("score", 0),
                "ts": 0,
            })
    except Exception as e:
        print(f"    lobste.rs error: {e}")
    print(f"    {len(items)} items")
    return items

def fetch_devto():
    print("  → DEV.to...")
    items = []
    tags = ["devops", "cloud", "rust", "compiler", "kubernetes", "mlops"]
    for tag in tags:
        try:
            url = f"https://dev.to/api/articles?tag={tag}&per_page=5&top=7"
            data = fetch_json(url)
            for a in data:
                title = a.get("title", "")
                desc  = a.get("description", "")
                items.append({
                    "source": "DEV.to",
                    "title": title,
                    "url": a.get("url", ""),
                    "text": desc,
                    "category": classify(title, desc),
                    "score": a.get("positive_reactions_count", 0),
                    "ts": 0,
                })
            time.sleep(0.2)
        except Exception as e:
            print(f"    DEV.to error ({tag}): {e}")
    print(f"    {len(items)} items")
    return items

# ── dedup & summarize ────────────────────────────────────────────────────────
def dedup(items):
    seen, out = set(), []
    for it in items:
        key = it["title"].lower()[:60]
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out

def add_summaries(items):
    print("  → Summarizing (HuggingFace BART)...")
    for i, it in enumerate(items):
        raw = it["text"].strip()
        if raw and len(raw.split()) >= 30:
            it["summary"] = hf_summarize(raw)
        else:
            it["summary"] = naive_summarize(it["title"], raw)
        if i % 10 == 0:
            print(f"    {i}/{len(items)}")
        time.sleep(0.1)
    return items

# ── HTML builder ─────────────────────────────────────────────────────────────
def build_html(items):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    by_cat = {c: [] for c in CATEGORIES}
    for it in items:
        cat = it["category"] if it["category"] in by_cat else "Other"
        by_cat[cat].append(it)

    # build category tabs
    tab_btns = ""
    tab_panels = ""
    all_items_html = ""

    for cat in CATEGORIES:
        its = by_cat[cat]
        if not its:
            continue
        cid = cat.replace(" ", "_").replace("/", "_").replace("&", "n")
        tab_btns += f'<button class="tab-btn" data-cat="{cid}">{escape(cat)} <span class="count">{len(its)}</span></button>\n'
        cards = ""
        for it in its:
            src_cls = it["source"].replace(".", "").replace(" ", "")
            cards += f'''
<article class="card">
  <div class="card-meta">
    <span class="badge {src_cls}">{escape(it["source"])}</span>
    {"<span class='score'>▲ " + str(it["score"]) + "</span>" if it["score"] else ""}
  </div>
  <h3><a href="{escape(it["url"])}" target="_blank" rel="noopener">{escape(it["title"])}</a></h3>
  <p class="summary">{escape(it["summary"])}</p>
</article>'''
        tab_panels += f'<section class="tab-panel" id="panel_{cid}">{cards}</section>\n'
        all_items_html += cards

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>techfeed // {now}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600&family=Space+Grotesk:wght@300;500;700&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: #000;
  --bg1: #0a0a0a;
  --bg2: #111;
  --bg3: #1a1a1a;
  --border: #222;
  --border2: #333;
  --text: #e8e8e8;
  --text2: #888;
  --text3: #555;
  --accent: #e8ff00;
  --accent2: #00ff9d;
  --hn: #ff6600;
  --arxiv: #b31b1b;
  --lobsters: #ac130d;
  --devto: #3b49df;
  --mono: 'JetBrains Mono', monospace;
  --sans: 'Space Grotesk', sans-serif;
}}

*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  font-size: 15px;
  line-height: 1.6;
  min-height: 100vh;
}}

/* scanline overlay */
body::before {{
  content: '';
  position: fixed;
  inset: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(255,255,255,.012) 2px,
    rgba(255,255,255,.012) 4px
  );
  pointer-events: none;
  z-index: 9999;
}}

header {{
  border-bottom: 1px solid var(--border);
  padding: 2rem 2rem 1.5rem;
  position: sticky;
  top: 0;
  background: rgba(0,0,0,.92);
  backdrop-filter: blur(8px);
  z-index: 100;
  display: flex;
  align-items: baseline;
  gap: 2rem;
  flex-wrap: wrap;
}}

.logo {{
  font-family: var(--mono);
  font-size: 1.4rem;
  font-weight: 600;
  color: var(--accent);
  letter-spacing: -0.02em;
}}

.logo span {{ color: var(--text3); }}

.meta {{
  font-family: var(--mono);
  font-size: .7rem;
  color: var(--text3);
  margin-left: auto;
}}

.tabs {{
  display: flex;
  gap: 0;
  padding: 0 2rem;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  scrollbar-width: none;
  background: var(--bg1);
}}

.tab-btn {{
  font-family: var(--mono);
  font-size: .72rem;
  font-weight: 400;
  color: var(--text3);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: .9rem 1.2rem;
  cursor: pointer;
  white-space: nowrap;
  transition: color .15s, border-color .15s;
  text-transform: uppercase;
  letter-spacing: .05em;
}}

.tab-btn:hover {{ color: var(--text); }}
.tab-btn.active {{
  color: var(--accent);
  border-bottom-color: var(--accent);
}}

.tab-btn .count {{
  display: inline-block;
  background: var(--bg3);
  color: var(--text3);
  border-radius: 2px;
  font-size: .6rem;
  padding: .05rem .3rem;
  margin-left: .4rem;
}}

.tab-btn.active .count {{
  background: var(--accent);
  color: #000;
}}

main {{
  max-width: 1100px;
  margin: 0 auto;
  padding: 2rem;
}}

.tab-panel {{ display: none; }}
.tab-panel.active {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1px; }}

.card {{
  background: var(--bg1);
  border: 1px solid var(--border);
  padding: 1.2rem 1.4rem;
  transition: border-color .15s, background .15s;
  position: relative;
}}

.card:hover {{
  border-color: var(--border2);
  background: var(--bg2);
}}

.card::before {{
  content: '';
  position: absolute;
  top: 0; left: 0;
  width: 2px; height: 0;
  background: var(--accent);
  transition: height .2s;
}}
.card:hover::before {{ height: 100%; }}

.card-meta {{
  display: flex;
  align-items: center;
  gap: .6rem;
  margin-bottom: .7rem;
}}

.badge {{
  font-family: var(--mono);
  font-size: .65rem;
  font-weight: 600;
  padding: .15rem .45rem;
  border-radius: 2px;
  text-transform: uppercase;
  letter-spacing: .04em;
}}

.HackerNews {{ background: #1a0d00; color: var(--hn); border: 1px solid #3d1f00; }}
.arXiv      {{ background: #1a0000; color: #ff6b6b;  border: 1px solid #3d0000; }}
.lobsters   {{ background: #1a0000; color: #ff4444;  border: 1px solid #3d0000; }}
.DEVto      {{ background: #00001a; color: #6b7cff;  border: 1px solid #00003d; }}

.score {{
  font-family: var(--mono);
  font-size: .65rem;
  color: var(--text3);
  margin-left: auto;
}}

.card h3 {{
  font-size: .92rem;
  font-weight: 500;
  line-height: 1.4;
  margin-bottom: .6rem;
}}

.card h3 a {{
  color: var(--text);
  text-decoration: none;
  transition: color .15s;
}}

.card h3 a:hover {{ color: var(--accent); }}

.summary {{
  font-size: .8rem;
  color: var(--text2);
  line-height: 1.5;
  font-family: var(--mono);
  font-weight: 300;
}}

#all-panel {{
  display: none;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 1px;
}}
#all-panel.active {{ display: grid; }}

footer {{
  border-top: 1px solid var(--border);
  padding: 1.5rem 2rem;
  font-family: var(--mono);
  font-size: .7rem;
  color: var(--text3);
  text-align: center;
}}

@media (max-width: 600px) {{
  header {{ padding: 1rem; gap: 1rem; }}
  .tabs {{ padding: 0 1rem; }}
  main {{ padding: 1rem; }}
  .tab-panel.active, #all-panel.active {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<header>
  <div class="logo">tech<span>/</span>feed</div>
  <div class="meta">updated {now} &nbsp;·&nbsp; {len(items)} articles</div>
</header>

<nav class="tabs">
  <button class="tab-btn active" data-cat="ALL">All <span class="count">{len(items)}</span></button>
  {tab_btns}
</nav>

<main>
  <div id="all-panel" class="tab-panel active">
    {all_items_html}
  </div>
  {tab_panels}
</main>

<footer>techfeed — auto-generated · sources: hackernews · arxiv · lobste.rs · dev.to</footer>

<script>
const btns = document.querySelectorAll('.tab-btn');
const allPanel = document.getElementById('all-panel');
const panels = document.querySelectorAll('.tab-panel[id^="panel_"]');

btns.forEach(btn => {{
  btn.addEventListener('click', () => {{
    btns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const cat = btn.dataset.cat;
    if (cat === 'ALL') {{
      allPanel.classList.add('active');
      panels.forEach(p => p.classList.remove('active'));
    }} else {{
      allPanel.classList.remove('active');
      panels.forEach(p => {{
        p.classList.toggle('active', p.id === 'panel_' + cat);
      }});
    }}
  }});
}});
</script>
</body>
</html>"""
    return html

# ── main ─────────────────────────────────────────────────────────────────────
def main():
    print("=== techfeed scraper ===")
    print("Fetching sources...")
    all_items = []
    all_items += fetch_hackernews()
    all_items += fetch_arxiv()
    all_items += fetch_lobsters()
    all_items += fetch_devto()

    print(f"Total before dedup: {len(all_items)}")
    all_items = dedup(all_items)
    print(f"After dedup: {len(all_items)}")

    # sort by score desc, then title
    all_items.sort(key=lambda x: -x["score"])

    print("Summarizing...")
    all_items = add_summaries(all_items)

    print("Building HTML...")
    html = build_html(all_items)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✓ index.html written")

if __name__ == "__main__":
    main()
