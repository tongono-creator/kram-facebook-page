"""Post a video as a Facebook Reel on the Kram page (manual workflow_dispatch).

env: KRAM_PAGE_ACCESS_TOKEN, VIDEO_URL (public mp4), CAPTION
"""
import os
import sys
import time

import requests

API = "v21.0"
PAGE_ID = "116701184708556"
TOKEN = os.environ["KRAM_PAGE_ACCESS_TOKEN"]
VIDEO_URL = os.environ["VIDEO_URL"]
CAPTION = os.environ.get("CAPTION", "")


def check(resp, step):
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400 or "error" in data:
        sys.exit(f"[{step}] HTTP {resp.status_code}: {data}")
    return data


def main():
    reels = f"https://graph.facebook.com/{API}/{PAGE_ID}/video_reels"
    start = check(requests.post(reels, data={"upload_phase": "start", "access_token": TOKEN}, timeout=60), "start")
    video_id = start["video_id"]
    print("video_id:", video_id)

    up = requests.post(f"https://rupload.facebook.com/video-upload/{API}/{video_id}",
                       headers={"Authorization": f"OAuth {TOKEN}", "file_url": VIDEO_URL}, timeout=300)
    print("upload:", check(up, "upload"))

    fin = check(requests.post(reels, data={
        "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
        "description": CAPTION, "access_token": TOKEN}, timeout=120), "finish")
    print("finish:", fin)

    for _ in range(40):
        st = check(requests.get(f"https://graph.facebook.com/{API}/{video_id}",
                                params={"fields": "status,permalink_url", "access_token": TOKEN}, timeout=30), "status")
        status = st.get("status", {})
        print("status:", status.get("video_status"), status.get("publishing_phase", {}).get("status"))
        if status.get("video_status") == "ready" and status.get("publishing_phase", {}).get("status") == "complete":
            print("PUBLISHED:", "https://www.facebook.com" + st.get("permalink_url", ""))
            return
        if status.get("video_status") == "error":
            sys.exit(f"processing error: {status}")
        time.sleep(15)
    print("still processing after 10 min — check the page:", video_id)


if __name__ == "__main__":
    main()
