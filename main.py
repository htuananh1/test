import os, json, time, zipfile, subprocess, atexit, sys, requests, re, hashlib
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime

VMESS_CFG = {
    "host": "idcecopro.yunagrp.pro",
    "obfsParam": "m.youtube.com",
    "uuid": "205144a4-65f-b4e-0a2-1d2ae88afa1",
    "path": "/yunagrp.com",
    "port": 443,
    "password": "c4178b6b-14e6-488b-8bd3-73f2d2d0d830"
}

def _valid_uuid(u: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", u or ""))

VMESS_ID = VMESS_CFG["uuid"] if _valid_uuid(VMESS_CFG.get("uuid","")) else VMESS_CFG.get("password","")
if not VMESS_ID:
    print("Missing VMESS_ID"); sys.exit(1)

XRAY_DIR = "xray-bin"
XRAY_ZIP = "xray.zip"
XRAY_EXE = os.path.join(XRAY_DIR, "xray")
XRAY_CONF = os.path.join(XRAY_DIR, "client.json")

def ensure_xray():
    if os.path.exists(XRAY_EXE): return
    os.makedirs(XRAY_DIR, exist_ok=True)
    url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(XRAY_ZIP, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk: f.write(chunk)
    with zipfile.ZipFile(XRAY_ZIP, "r") as z: z.extractall(XRAY_DIR)
    os.remove(XRAY_ZIP)
    os.chmod(XRAY_EXE, 0o755)

def write_xray_config():
    cfg = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {"listen":"127.0.0.1","port":1080,"protocol":"socks","settings":{"udp":True}},
            {"listen":"127.0.0.1","port":8080,"protocol":"http"}
        ],
        "outbounds": [{
            "protocol":"vmess",
            "settings":{
                "vnext":[{
                    "address": VMESS_CFG["host"],
                    "port": VMESS_CFG["port"],
                    "users":[{"id": VMESS_ID, "alterId":0, "security":"auto"}]
                }]
            },
            "streamSettings":{
                "network":"ws","security":"tls",
                "tlsSettings":{"serverName": VMESS_CFG["obfsParam"],"allowInsecure":False},
                "wsSettings":{"path": VMESS_CFG["path"], "headers":{"Host": VMESS_CFG["obfsParam"]}}
            }
        }]
    }
    with open(XRAY_CONF, "w") as f: json.dump(cfg, f, indent=2)

xray_proc = None
def start_xray():
    global xray_proc
    xray_proc = subprocess.Popen([XRAY_EXE,"-c",XRAY_CONF], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    t0 = time.time()
    while time.time()-t0 < 3:
        if xray_proc.poll() is not None: raise RuntimeError("Xray exited")
        line = xray_proc.stdout.readline().strip()
        if line: print("[xray]", line)
        time.sleep(0.1)

def stop_xray():
    if xray_proc and xray_proc.poll() is None: xray_proc.terminate()
atexit.register(stop_xray)

session = requests.Session()
session.headers.update({
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language":"vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer":"https://www.google.com/"
})
PROXIES = {"http":"http://127.0.0.1:8080","https":"http://127.0.0.1:8080"}

def get(url, **kw):
    kw.setdefault("timeout", 25)
    kw.setdefault("proxies", PROXIES)
    return session.get(url, **kw)

BASE = "https://animevietsub.cam"

def get_max_page():
    r = get(BASE); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    cand = []
    for sel in ("ul.pagination a",".pagination a","a.page-numbers"):
        for a in soup.select(sel):
            t = a.get_text(strip=True)
            if t.isdigit(): cand.append(int(t))
    return max(cand) if cand else 1

def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(".MovieList .TPostMv") or []
    out = []
    for it in items:
        a = it.select_one("a[href]"); 
        if not a: continue
        url = urljoin(BASE, a["href"])
        title = it.select_one(".Title").get_text(strip=True) if it.select_one(".Title") else ""
        eps = it.select_one(".mli-eps i").get_text(strip=True) if it.select_one(".mli-eps i") else ""
        img = it.select_one("img")
        img_url = ""
        if img:
            img_url = img.get("data-cfsrc") or img.get("data-src") or img.get("src") or ""
            if img_url and not img_url.startswith("http"): img_url = urljoin(BASE, img_url)
        out.append({
            "id": hashlib.md5(url.encode()).hexdigest()[:10],
            "name": title, "url": url, "image": img_url,
            "episodes": eps, "scraped_at": datetime.now().isoformat()
        })
    return out

def scrape_all(delay_sec=3):
    total = []
    maxp = get_max_page()
    print("pages:", maxp)
    for p in range(1, maxp+1):
        url = BASE if p==1 else f"{BASE}/page/{p}"
        print(f"{p}/{maxp} -> {url}")
        try:
            r = get(url)
            if r.status_code in (403,429,503):
                time.sleep(6); r = get(url)
            r.raise_for_status()
        except Exception as e:
            print("err:", e); continue
        total.extend(parse_list(r.text))
        time.sleep(delay_sec)
    print("total_anime:", len(total))
    return total

def build_output(anime_list):
    return {
        "name":"ANIMEVIETSUB","id":"avietsub-pvd","url":BASE,"color":"#FF6B00",
        "image":{"url":f"{BASE}/logo.png","display":"cover","shape":"square"},
        "description":"AnimeVietsub.cam - Xem anime online miễn phí chất lượng cao",
        "org_metadata":{"description":"AnimeVietsub.cam - Xem anime online miễn phí chất lượng cao","title":"ANIMEVIETSUB","image":f"{BASE}/orgthumb.jpg"},
        "share":{"url":BASE},
        "notice":{"id":"notice-1","link":BASE,"icon":f"{BASE}/icon.png","closeable":True},
        "sorts":[{"text":"Mới nhất","type":"radio","url":f"{BASE}/anime-moi"},{"text":"Phổ biến","type":"radio","url":f"{BASE}/anime-hot"}],
        "total_anime":len(anime_list),"last_updated":datetime.now().isoformat(),"anime_list":anime_list
    }

def save_local(data: dict, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
    print("saved:", path)

def save_github(data: dict, repo_full: str, out_path: str, token: str):
    try:
        from github import Github
    except Exception:
        return save_local(data, out_path)
    try:
        g = Github(token); repo = g.get_repo(repo_full)
        content = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            file = repo.get_contents(out_path)
            repo.update_file(out_path, f"Update {out_path} {datetime.now().isoformat()}", content, file.sha)
        except Exception:
            repo.create_file(out_path, f"Add {out_path} {datetime.now().isoformat()}", content)
        print("pushed:", out_path)
    except Exception as e:
        print("gh_err:", e); save_local(data, out_path)

def main():
    ensure_xray(); write_xray_config(); start_xray()
    try:
        print("ip:", get("https://api.ipify.org?format=json").json())
    except Exception as e:
        print("ip_err:", e)
    try:
        data = scrape_all(delay_sec=3)
        output = build_output(data)
        GITHUB_TOKEN = os.getenv("GITHUB_TOKEN","").strip()
        GH_REPO = os.getenv("GH_REPO","htuananh1/Data-manager").strip()
        OUT_DATA = os.getenv("OUT_DATA_PATH","animevsub/animevsub_data.json").strip()
        OUT_SUM  = os.getenv("OUT_SUM_PATH","animevsub/animevsub_summary.json").strip()
        summary = {"last_update": datetime.now().isoformat(),"total_anime": len(output["anime_list"]),"new_anime_added": len(data)}
        if GITHUB_TOKEN:
            save_github(output, GH_REPO, OUT_DATA, GITHUB_TOKEN)
            save_github(summary, GH_REPO, OUT_SUM, GITHUB_TOKEN)
        else:
            save_local(output, OUT_DATA)
            save_local(summary, OUT_SUM)
    finally:
        stop_xray()

if __name__ == "__main__":
    main()
