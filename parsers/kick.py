import json
import asyncio
import aiohttp
import subprocess

class KickParser:
    INPUT_TYPE = "username"
    EVENTS = [
        "Kick chat", "Kick redeem", "Kick follow", "Kick sub", "Kick gift sub",
        "Kick raid start", "Kick raid end", "Kick ban", "Kick timeout", 
        "Kick stream start", "Kick stream end", "Kick other"
    ]
    TRIGGERS = {
        "Kick chat":         "Kick chat",
        "Kick redeem":       "Kick redeem {title}",
        "Kick follow":       "Kick follow",
        "Kick sub":          "Kick sub",
        "Kick gift sub":     "Kick gift sub",
        "Kick raid start":   "Kick raid start",
        "Kick raid end":     "Kick raid end",
        "Kick ban":          "Kick ban",
        "Kick timeout":      "Kick timeout",
        "Kick stream start": "Kick stream start",
        "Kick stream end":   "Kick stream end",
        "Kick other":        "Kick other ({event})"
    }

    @staticmethod
    def try_json(s):
        try: return json.loads(s)
        except: return None

    @staticmethod
    def detect_event_name(payload_str):
        names = [
            "ChatMessageEvent", "RewardRedeemedEvent", "FollowEvent", "SubscriptionEvent",
            "GiftedSubscriptionEvent", "PinnedMessageEvent", "ReactionCreatedEvent",
            "UserBannedEvent", "UserTimedOutEvent", "StreamStartedEvent", "StreamEndedEvent",
            "HostStartedEvent", "HostEndedEvent", "RaidStartedEvent", "RaidEndedEvent",
            "PollStartedEvent", "PollEndedEvent", "PollVoteEvent", "StreamUpdatedEvent",
            "ChatClearedEvent", "EmoteCreatedEvent", "EmoteDeletedEvent"
        ]
        for n in names:
            if n in payload_str: return n
        return None

    @staticmethod
    def parse_frame(payload_str):
        en = KickParser.detect_event_name(payload_str)
        if not en: return None

        d = KickParser.try_json(payload_str) or {}
        raw_data = d.get("data")
        if isinstance(raw_data, str):
            inner = KickParser.try_json(raw_data)
            if isinstance(inner, dict):
                d["data"] = inner
        
        ek = "Kick other"
        title = ""
        payload = d.get("data", {})
        if not isinstance(payload, dict): payload = {"raw": payload}

        if en == "ChatMessageEvent":
            ek = "Kick chat"
            sender = payload.get("sender", {})
            payload["username"] = sender.get("username", "Unknown")
            payload["user"] = payload["username"]
            payload["message"] = payload.get("content", "")
            payload["color"] = sender.get("identity", {}).get("color", "#CCCCCC")
            
            badges_list = sender.get("identity", {}).get("badges", [])
            badge_str = ""
            is_sub = False
            is_mod = False
            is_vip = False
            
            for b in badges_list:
                b_type = ""
                if isinstance(b, dict) and b.get("active", True): b_type = b.get("type", "")
                elif isinstance(b, str): b_type = b
                
                if b_type:
                    if "broadcaster" in b_type: badge_str += "[BROADCASTER]"; is_mod = True
                    elif "moderator" in b_type: badge_str += "[MOD]"; is_mod = True
                    elif "subscriber" in b_type: badge_str += "[SUB]"; is_sub = True
                    elif "vip" in b_type: badge_str += "[VIP]"; is_vip = True
                    elif "founder" in b_type: badge_str += "[FOUNDER]"; is_sub = True
                    elif "og" in b_type: badge_str += "[OG]"
            
            payload["badges"] = badge_str
            payload["subscriber"] = is_sub
            payload["mod"] = is_mod
            payload["vip"] = is_vip

        elif en == "RewardRedeemedEvent":
            ek = "Kick redeem"
            payload["username"] = payload.get("username", "Unknown")
            payload["user"] = payload["username"]
            payload["message"] = payload.get("user_input", "")
            title = payload.get("reward_title") or (payload.get("reward", {}) or {}).get("title") or payload.get("title") or "Unknown"

        elif en == "FollowEvent":
            ek = "Kick follow"
            payload["username"] = payload.get("username", "Unknown")
            payload["user"] = payload["username"]
            
        elif en == "SubscriptionEvent":
            ek = "Kick sub"
            payload["username"] = payload.get("username", "Unknown")
            payload["user"] = payload["username"]
            
        elif en == "GiftedSubscriptionEvent":
            ek = "Kick gift sub"
            payload["username"] = payload.get("gifter_username", "Unknown")
            payload["user"] = payload["username"]
            
        elif en == "RaidStartedEvent":
            ek = "Kick raid start"
            payload["username"] = payload.get("host_username", "Unknown")
            payload["user"] = payload["username"]
            
        elif en == "RaidEndedEvent":
            ek = "Kick raid end"
            
        elif en == "UserBannedEvent":
            ek = "Kick ban"
            user_data = payload.get("user")
            if isinstance(user_data, dict):
                payload["username"] = user_data.get("username", "Unknown")
            else:
                payload["username"] = payload.get("username", "Unknown")
            payload["user"] = payload["username"]
            
        elif en == "UserTimedOutEvent":
            ek = "Kick timeout"
            user_data = payload.get("user")
            if isinstance(user_data, dict):
                payload["username"] = user_data.get("username", "Unknown")
            else:
                payload["username"] = payload.get("username", "Unknown")
            payload["user"] = payload["username"]
            
        elif en == "StreamStartedEvent": ek = "Kick stream start"
        elif en == "StreamEndedEvent": ek = "Kick stream end"

        if en in ["ReactionCreatedEvent", "PollVoteEvent", "StreamUpdatedEvent"]:
            return None

        trigger = KickParser.TRIGGERS.get(ek, KickParser.TRIGGERS["Kick other"]).format(title=title, event=en)
        return ek, {"trigger": trigger, "customData": payload}


KICK_AVATAR_CACHE = {}

async def get_kick_metadata(username):
    chat_id, chan_id = None, None
    urls = [
        f"https://kick.com/api/v1/channels/{username}",
        f"https://kick.com/api/v2/channels/{username}"
    ]
    
    # 1. Try Windows curl.exe fallback to bypass Cloudflare
    for url in urls:
        try:
            cmd = [
                "curl.exe",
                "-s",
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-H", "Accept-Language: en-US,en;q=0.9",
                "-H", "Referer: https://kick.com/",
                url
            ]
            loop = asyncio.get_event_loop()
            def run_curl():
                return subprocess.run(cmd, capture_output=True, text=True, timeout=10, encoding="utf-8")
                
            res = await loop.run_in_executor(None, run_curl)
            if res.returncode == 0:
                d = json.loads(res.stdout)
                if isinstance(d, dict):
                    chan_id = d.get("id")
                    if "chatroom" in d and isinstance(d["chatroom"], dict):
                        chat_id = d["chatroom"].get("id")
                    if "user" in d and isinstance(d["user"], dict) and "profile_pic" in d["user"]:
                        KICK_AVATAR_CACHE[username] = d["user"]["profile_pic"]
                    if chat_id and chan_id:
                        return chat_id, chan_id
        except Exception:
            pass

    # 2. Traditional aiohttp fallback (using api/v2 and api/v1)
    for url in urls:
        try:
            async with aiohttp.ClientSession() as sess:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://kick.com/"
                }
                async with sess.get(url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        d = await resp.json()
                        if isinstance(d, dict):
                            chan_id = d.get("id")
                            if "chatroom" in d and isinstance(d["chatroom"], dict):
                                chat_id = d["chatroom"].get("id")
                            if "user" in d and isinstance(d["user"], dict) and "profile_pic" in d["user"]:
                                KICK_AVATAR_CACHE[username] = d["user"]["profile_pic"]
                            if chat_id and chan_id:
                                return chat_id, chan_id
        except Exception:
            pass
    return chat_id, chan_id

async def monitor_kick(session, username, event_queue):
    ws_url = "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=8.4.0&flash=false"
    
    backoff = 1
    while True:
        try:
            chat_id, chan_id = await get_kick_metadata(username)
            if not chat_id:
                print(f"[Chat] Could not retrieve Kick metadata for '{username}'. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue

            async with session.ws_connect(ws_url) as ws:
                channels = [
                    f"chatrooms.{chat_id}.v2",
                    f"chatroom_{chat_id}",
                    f"chatrooms.{chat_id}",
                    f"channel.{chan_id}",
                    f"channel_{chan_id}"
                ]
                for c in channels:
                     await ws.send_json({"event": "pusher:subscribe", "data": {"auth": "", "channel": c}})
                print(f"[Chat] Kick chat connected and subscribed for '{username}'")
                backoff = 1  # Reset backoff on successful connection
                
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        # Log raw messages to console for debugging redeems/payloads
                        print(f"[Chat-RAW] Kick WS received: {msg.data}")
                        
                        # Specifically check and log Pusher subscription or connection errors
                        if "pusher:error" in msg.data or "subscription_error" in msg.data:
                            print(f"[Chat-ERROR] Kick Pusher Subscription Error: {msg.data}")
                            
                        res = KickParser.parse_frame(msg.data)
                        if res:
                            ek, fmt = res
                            event_queue.put(("KickParser", username, ek, fmt["trigger"], fmt["customData"]))
        except Exception as e:
            print(f"[Chat] Kick connection error for '{username}': {e}. Retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
