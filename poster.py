"""
Assistify — Multi-Platform Daily Poster
Posts 1 video per day at 19:00 Berlin to Instagram + Facebook + TikTok
Railway hosted, Cloudinary queue
"""

import os
import time
import json
import threading
import requests
from datetime import datetime
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import cloudinary
import cloudinary.api
import cloudinary.uploader

app = Flask(__name__)
BERLIN = pytz.timezone("Europe/Berlin")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
IG_TOKEN          = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
IG_USER_ID        = os.environ.get("INSTAGRAM_USER_ID", "26327994056810336")
FB_PAGE_TOKEN     = os.environ.get("FB_PAGE_ACCESS_TOKEN", "")   # Facebook Page Token
FB_PAGE_ID        = os.environ.get("FB_PAGE_ID", "61579625669890")
TIKTOK_TOKEN      = os.environ.get("TIKTOK_ACCESS_TOKEN", "")    # TikTok Token
LOCATION_ID       = "107681779263786"   # Freiburg im Breisgau

CLOUDINARY_CLOUD  = os.environ.get("CLOUDINARY_CLOUD_NAME", "dlv8ebddq")
CLOUDINARY_KEY    = os.environ.get("CLOUDINARY_API_KEY", "837591974475139")
CLOUDINARY_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "1wHQz08D45SYbFg7vuecfVMaOac")

CAPTION_IG = """We handle your entire content production and product marketing – from idea to high-performing videos 🎬

If you're interested in how to create similar videos, comment "AI" and I'll send you a step-by-step PDF showing how you can create similar videos yourself.

📍 Freiburg im Breisgau
🌐 assistifyai-official.netlify.app
📩 Waitlist: assistifyai-official.netlify.app/#waitlist

#aivideo #marketingestrategico #contentcreators #ugc #brandingtips"""

CAPTION_FB = CAPTION_IG  # Same caption for Facebook

CAPTION_TT = """We handle your entire content production and product marketing 🎬

Comment "AI" for a free step-by-step PDF on how to create similar videos!

🌐 assistifyai-official.netlify.app

#aivideo #contentcreators #ugc #brandingtips #marketingdigital"""
# ──────────────────────────────────────────────────────────────────────────────

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD,
    api_key=CLOUDINARY_KEY,
    api_secret=CLOUDINARY_SECRET,
)

def get_next_video():
    try:
        result = cloudinary.api.resources_by_tag(
            "ig_queue", resource_type="video", context=True, max_results=100
        )
        assets = result.get("resources", [])
        unposted = [
            a for a in assets
            if a.get("context", {}).get("custom", {}).get("ig_posted") == "false"
        ]
        if not unposted:
            return None
        unposted.sort(key=lambda x: int(x.get("context", {}).get("custom", {}).get("post_order", 999)))
        return unposted[0]
    except Exception as e:
        print(f"Cloudinary Fehler: {e}")
        return None

def post_instagram(video_url: str) -> bool:
    if not IG_TOKEN:
        print("Instagram: kein Token")
        return False

    base = f"https://graph.instagram.com/v21.0/{IG_USER_ID}"
    print("Instagram: Erstelle Container...")

    r = requests.post(f"{base}/media", data={
        "video_url":     video_url,
        "media_type":    "REELS",
        "caption":       CAPTION_IG,
        "share_to_feed": "true",
        "access_token":  IG_TOKEN,
    })
    if r.status_code != 200:
        print(f"Instagram Container-Fehler: {r.text}")
        return False

    container_id = r.json().get("id")
    print(f"Instagram Container: {container_id} — warte auf Verarbeitung...")

    for attempt in range(20):
        time.sleep(15)
        s = requests.get(
            f"https://graph.instagram.com/v21.0/{container_id}",
            params={"fields": "status_code", "access_token": IG_TOKEN}
        ).json().get("status_code", "")
        print(f"  Status: {s} ({attempt+1}/20)")
        if s == "FINISHED":
            break
        if s == "ERROR":
            print("Instagram: Verarbeitung fehlgeschlagen")
            return False

    pub = requests.post(f"{base}/media_publish", data={
        "creation_id": container_id,
        "access_token": IG_TOKEN,
    })
    if pub.status_code == 200:
        print(f"Instagram: Gepostet! ID: {pub.json().get('id')}")
        return True
    print(f"Instagram Publish-Fehler: {pub.text}")
    return False

def post_facebook(video_url: str) -> bool:
    if not FB_PAGE_TOKEN:
        print("Facebook: kein Page Token — übersprungen")
        return False

    print("Facebook: Poste Reel...")
    r = requests.post(
        f"https://graph-video.facebook.com/v21.0/{FB_PAGE_ID}/videos",
        data={
            "file_url":    video_url,
            "description": CAPTION_FB,
            "access_token": FB_PAGE_TOKEN,
        }
    )
    if r.status_code == 200:
        print(f"Facebook: Gepostet! ID: {r.json().get('id')}")
        return True
    print(f"Facebook Fehler: {r.text}")
    return False

def post_tiktok(video_url: str) -> bool:
    if not TIKTOK_TOKEN:
        print("TikTok: kein Token — übersprungen")
        return False

    print("TikTok: Poste Video...")
    # TikTok Content Posting API v2
    r = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers={
            "Authorization": f"Bearer {TIKTOK_TOKEN}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={
            "post_info": {
                "title": CAPTION_TT[:150],
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            }
        }
    )
    if r.status_code == 200:
        print(f"TikTok: Upload gestartet! {r.json()}")
        return True
    print(f"TikTok Fehler: {r.text}")
    return False

def mark_as_posted(public_id: str):
    try:
        cloudinary.uploader.explicit(
            public_id, type="upload", resource_type="video",
            context=f"ig_posted=true|posted_at={datetime.now(BERLIN).strftime('%Y-%m-%d %H:%M')}",
        )
    except Exception as e:
        print(f"Marking-Fehler: {e}")

def daily_post():
    now = datetime.now(BERLIN)
    print(f"\n{'='*50}")
    print(f"Daily Post: {now.strftime('%d.%m.%Y %H:%M')} Berlin")
    print(f"{'='*50}")

    video = get_next_video()
    if not video:
        print("Queue leer — keine Videos mehr!")
        return

    video_url = video.get("secure_url")
    public_id = video.get("public_id")
    order = video.get("context", {}).get("custom", {}).get("post_order", "?")
    print(f"Video #{order}: {public_id}\n")

    ig_ok = post_instagram(video_url)
    time.sleep(5)
    fb_ok = post_facebook(video_url)
    time.sleep(5)
    tt_ok = post_tiktok(video_url)

    print(f"\nErgebnis: Instagram={'✓' if ig_ok else '✗'} | Facebook={'✓' if fb_ok else '✗'} | TikTok={'✓' if tt_ok else '✗'}")

    if ig_ok or fb_ok or tt_ok:
        mark_as_posted(public_id)

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return jsonify({"status": "running", "service": "Assistify Multi-Platform Poster"})

@app.route("/post_now")
def post_now():
    threading.Thread(target=daily_post, daemon=True).start()
    return jsonify({"status": "started — check logs"})

@app.route("/test_facebook")
def test_facebook():
    def run():
        video = get_next_video()
        if not video:
            print("Queue leer")
            return
        video_url = video.get("secure_url")
        print(f"Facebook Test mit: {video_url}")
        post_facebook(video_url)
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "Facebook Test gestartet — check logs"})

@app.route("/find_location")
def find_location():
    token = FB_PAGE_TOKEN or IG_TOKEN
    if not token:
        return jsonify({"error": "Kein Token verfügbar"})
    q = "Freiburg im Breisgau"
    r = requests.get(
        "https://graph.facebook.com/v21.0/search",
        params={"type": "place", "q": q, "fields": "id,name,location", "access_token": token}
    )
    return jsonify(r.json())

@app.route("/queue")
def queue_status():
    try:
        result = cloudinary.api.resources_by_tag("ig_queue", resource_type="video", context=True, max_results=100)
        assets = result.get("resources", [])
        unposted = [a for a in assets if a.get("context", {}).get("custom", {}).get("ig_posted") == "false"]
        posted = [a for a in assets if a.get("context", {}).get("custom", {}).get("ig_posted") == "true"]
        return jsonify({"total": len(assets), "noch_ausstehend": len(unposted), "gepostet": len(posted)})
    except Exception as e:
        return jsonify({"error": str(e)})

# ─── Scheduler ────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone=BERLIN)
scheduler.add_job(daily_post, CronTrigger(hour=19, minute=0, timezone=BERLIN))
scheduler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Multi-Platform Poster läuft | Port {port} | täglich 19:00 Berlin")
    app.run(host="0.0.0.0", port=port)
