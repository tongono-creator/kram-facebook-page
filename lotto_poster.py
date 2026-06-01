# -*- coding: utf-8 -*-
import os
import re
import sys
import io
import time
import requests
from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HISTORY_FILE = "posted_history.txt"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        except Exception:
            return []
    return []

def save_to_history(item):
    items = load_history()
    items.append(item)
    items = items[-300:]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            for it in items:
                f.write(it + "\n")
    except Exception as e:
        print(f"Error saving history: {e}")

def get_page_info():
    path = os.path.abspath(__file__).replace("\\", "/")
    if "chowchow" in path:
        return "102319399434080", "Chow Chow", "โฮ่ง! ผลหวยออกแล้วฮะงวดนี้ มีใครถูกรางวัลบ้างไหมฮะ 🐾"
    elif "somtam" in path:
        return "554501167740603", "พริก 10 เม็ด", "กรี๊ดด ผลหวยออกแล้วค่ะงวดนี้! ใครได้เป็นเศรษฐีบ้างคะ 🌶️"
    elif "kram" in path:
        return "116701184708556", "กรามข้าง", "ผลสลากกินแบ่งรัฐบาลออกแล้วครับงวดนี้! มาตรวจรางวัลกันครับงวดนี้มีใครโชคดีบ้าง 📢"
    else:
        return "111830598532037", "Rocket21", "รายงานผลสลากกินแบ่งรัฐบาลไทยงวดนี้ครับ มีใครถูกรางวัลกันบ้างครับ 📊"

def get_latest_lottery():
    url = "https://news.sanook.com/lotto/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        highlight = soup.find(class_="lotto-highlight")
        if not highlight:
            return None
            
        draw_title = "ตรวจสลากกินแบ่งรัฐบาล"
        title_el = highlight.find(class_="section__title")
        if title_el:
            a_tag = title_el.find("a")
            if a_tag:
                draw_title = a_tag.get_text(strip=True)
                
        cells = highlight.find_all(class_="lotto__cell")
        
        result = {
            "title": draw_title,
            "first_prize": "",
            "front_three": [],
            "last_three": [],
            "last_two": ""
        }
        
        for cell in cells:
            name_el = cell.find(class_="lotto__name")
            if not name_el:
                continue
            name_text = name_el.get_text(strip=True)
            
            num_els = cell.find_all(class_=lambda x: x and "lotto__number" in x)
            nums = [el.get_text(strip=True) for el in num_els]
            
            if "รางวัลที่ 1" in name_text:
                if nums:
                    result["first_prize"] = nums[0]
            elif "เลขหน้า 3 ตัว" in name_text:
                result["front_three"] = nums
            elif "เลขท้าย 3 ตัว" in name_text:
                result["last_three"] = nums
            elif "เลขท้าย 2 ตัว" in name_text:
                if nums:
                    result["last_two"] = nums[0]
                    
        return result
    except Exception as e:
        print(f"Error fetching lottery: {e}")
        return None

def post_facebook(page_id, token, message):
    try:
        api_url = f"https://graph.facebook.com/v21.0/{page_id}/feed"
        resp = requests.post(
            api_url,
            data={
                "message":      message,
                "access_token": token,
            },
            timeout=60,
        )
        result = resp.json()
        if "id" in result:
            print(f"Posted to Facebook page {page_id} successfully: {result['id']}")
            return result["id"]
        else:
            print(f"Post failed: {result}")
            return None
    except Exception as e:
        print(f"Post error: {e}")
        return None

def main():
    print("Checking Thai lottery results...")
    lotto = get_latest_lottery()
    if not lotto:
        print("Failed to fetch lottery results.")
        return

    title = lotto["title"].strip()
    first_prize = lotto.get("first_prize", "")
    front_three = lotto.get("front_three", [])
    last_three = lotto.get("last_three", [])
    last_two = lotto.get("last_two", "")

    # Sanity checks
    if not first_prize or not front_three or not last_three or not last_two:
        print("Lottery results are incomplete. Skipping.")
        return
        
    if not (first_prize.isdigit() and len(first_prize) == 6):
        print(f"First prize '{first_prize}' is not a valid 6-digit number yet. Skipping.")
        return
        
    if not (last_two.isdigit() and len(last_two) == 2):
        print(f"Last two digits '{last_two}' are not a valid 2-digit number yet. Skipping.")
        return
        
    for num in front_three + last_three:
        if not (num.isdigit() and len(num) == 3):
            print(f"Number '{num}' is not a valid 3-digit number yet. Skipping.")
            return

    history = set(load_history())
    if title in history:
        print(f"Lottery results for '{title}' already posted. Skipping.")
        return

    # Get page config
    page_id, page_name, intro = get_page_info()
    
    # Get page token
    token = (
        os.environ.get("PAGE_ACCESS_TOKEN") or
        os.environ.get("KRAM_PAGE_ACCESS_TOKEN") or
        os.environ.get("SOMTAM_PAGE_ACCESS_TOKEN") or
        os.environ.get("CHOWCHOW_PAGE_ACCESS_TOKEN")
    )
    
    if not token:
        print(f"[Warning] No Page Access Token found in environment. Skipping post for {page_name}.")
        return

    front_three_str = ", ".join(front_three)
    last_three_str = ", ".join(last_three)

    post_text = (
        f"{intro}\n\n"
        f"📢 {title}\n"
        f"ผลรางวัลสลากกินแบ่งรัฐบาลไทย\n\n"
        f"🏆 รางวัลที่ 1 : {first_prize}\n"
        f"👉 เลขหน้า 3 ตัว : {front_three_str}\n"
        f"👉 เลขท้าย 3 ตัว : {last_three_str}\n"
        f"👉 เลขท้าย 2 ตัว : {last_two}\n\n"
        f"#ตรวจหวย #ผลสลาก #สลากกินแบ่งรัฐบาล"
    )

    print(f"Posting to {page_name} ({page_id})...")
    post_id = post_facebook(page_id, token, post_text)
    if post_id:
        save_to_history(title)
        print(f"Successfully recorded draw: {title}")

if __name__ == "__main__":
    main()
