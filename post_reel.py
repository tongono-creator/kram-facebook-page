"""Post (or schedule) a video as a Facebook Reel on the Kram page (manual workflow_dispatch).

env: KRAM_PAGE_ACCESS_TOKEN, VIDEO_URL (public mp4), CAPTION, PUBLISH_AT (optional unix time -> scheduled)
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
PUBLISH_AT = os.environ.get("PUBLISH_AT", "").strip()


def check(resp, step):
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400 or "error" in data:
        sys.exit(f"[{step}] HTTP {resp.status_code}: {data}")
    return data


def report(video_id):
    st = check(requests.get(f"https://graph.facebook.com/{API}/{video_id}",
                            params={"fields": "published,scheduled_publish_time,status,description", "access_token": TOKEN},
                            timeout=30), "report")
    print("REPORT:", video_id, "published=", st.get("published"), "scheduled=", st.get("scheduled_publish_time"),
          "status=", st.get("status", {}).get("video_status"), "caption=", (st.get("description") or "")[:40])


def main():
    if VIDEO_URL.startswith("check:"):        # check:<id>,<id>,... -> just report
        for vid in VIDEO_URL[6:].split(","):
            report(vid.strip())
        return
    reels =f"https://graph.facebook.com/{API}/{PAGE_ID}/video_reels"
    start = check(requests.post(reels, data={"upload_phase": "start", "access_token": TOKEN}, timeout=60), "start")
    video_id = start["video_id"]
    print("video_id:", video_id)

    up = requests.post(f"https://rupload.facebook.com/video-upload/{API}/{video_id}",
                       headers={"Authorization": f"OAuth {TOKEN}", "file_url": VIDEO_URL}, timeout=300)
    print("upload:", check(up, "upload"))

    finish = {"upload_phase": "finish", "video_id": video_id, "description": CAPTION, "access_token": TOKEN}
    if PUBLISH_AT:
        finish.update(video_state="SCHEDULED", scheduled_publish_time=PUBLISH_AT)
    else:
        finish.update(video_state="PUBLISHED")
    print("finish:", check(requests.post(reels, data=finish, timeout=120), "finish"))

    for _ in range(40):
        st = check(requests.get(f"https://graph.facebook.com/{API}/{video_id}",
                                params={"fields": "status,permalink_url", "access_token": TOKEN}, timeout=30), "status")
        status = st.get("status", {})
        vs, pub = status.get("video_status"), status.get("publishing_phase", {}).get("status")
        print("status:", vs, pub)
        if vs == "error":
            sys.exit(f"processing error: {status}")
        if vs == "ready" and PUBLISH_AT:
            print("SCHEDULED:", video_id, "at", PUBLISH_AT)
            report(video_id)
            return
        if vs == "ready" and pub == "complete":
            print("PUBLISHED:", "https://www.facebook.com" + st.get("permalink_url", ""))
            return
        time.sleep(15)
    print("still processing after 10 min — check the page:", video_id)


if __name__ == "__main__":
    main()
