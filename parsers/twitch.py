import json
import asyncio
import aiohttp
import random
import string
import datetime
import urllib.request
import threading
from config import BADGE_DB

class TwitchParser:
    INPUT_TYPE = "username"
    
    @staticmethod
    def parse_frame(line):
        if line.strip().startswith("{"):
            try:
                data = json.loads(line)
                def find_event(obj, target_type):
                    if isinstance(obj, dict):
                        if obj.get("type") == target_type: return obj.get("data") or obj
                        if "notification" in obj:
                            notif = obj["notification"]
                            if isinstance(notif, dict) and "pubsub" in notif:
                                return find_event(notif["pubsub"], target_type)
                        if "message" in obj and isinstance(obj["message"], str):
                            try:
                                inner = json.loads(obj["message"])
                                res = find_event(inner, target_type)
                                if res: return res
                            except: pass
                        for k, v in obj.items():
                            res = find_event(v, target_type)
                            if res: return res
                    elif isinstance(obj, list):
                        for item in obj:
                            res = find_event(item, target_type)
                            if res: return res
                    elif isinstance(obj, str):
                        s = obj.strip()
                        if s.startswith("{") and s.endswith("}"):
                            try:
                                inner = json.loads(s)
                                res = find_event(inner, target_type)
                                if res: return res
                            except: pass
                    return None

                redemption_data = find_event(data, "reward-redeemed")
                if redemption_data:
                    redemption = redemption_data.get("redemption") or redemption_data
                    user_obj = redemption.get("user") or {}
                    rew = redemption.get("reward") or {}
                    img_obj = rew.get("image") or {}
                    def_img_obj = rew.get("default_image") or rew.get("defaultImage") or {}
                    final_image = img_obj.get("url_4x") or def_img_obj.get("url_4x")

                    return "Twitch redeem (pubsub)", {
                        "trigger": f"Twitch redeem {rew.get('title', 'Unknown')}",
                        "customData": {
                            "reward_id": rew.get("id"),
                            "reward_title": rew.get("title", "Unknown"),
                            "cost": rew.get("cost"),
                            "user_id": user_obj.get("id"),
                            "username": user_obj.get("login"),
                            "display_name": user_obj.get("display_name") or user_obj.get("displayName"),
                            "message": redemption.get("user_input") or redemption.get("userInput", ""),
                            "image": final_image
                        }
                    }
                
                hype_train_data = find_event(data, "hype-train-progression") or find_event(data, "hype-train-start") or find_event(data, "hype-train-end")
                if hype_train_data:
                    sources = [hype_train_data, data]
                    if isinstance(hype_train_data.get("progress"), dict):
                        sources.append(hype_train_data["progress"])
                        if isinstance(hype_train_data["progress"].get("level"), dict):
                            sources.append(hype_train_data["progress"]["level"])
                    if isinstance(hype_train_data.get("level"), dict):
                        sources.append(hype_train_data["level"])

                    level = 0
                    for source in sources:
                        if isinstance(source, dict) and "level" in source:
                            lvl_data = source["level"]
                            if isinstance(lvl_data, dict): level = lvl_data.get("value", 0)
                            elif isinstance(lvl_data, int): level = lvl_data
                            if level: break
                    progress = 0
                    for source in sources:
                        if isinstance(source, dict) and "progress" in source:
                            prog_data = source["progress"]
                            if isinstance(prog_data, dict): progress = prog_data.get("value", 0)
                            elif isinstance(prog_data, int): progress = prog_data
                            if progress: break
                    goal = 0
                    for source in sources:
                        if isinstance(source, dict) and "goal" in source:
                            goal_data = source["goal"]
                            if isinstance(goal_data, dict): goal = goal_data.get("value", 0)
                            elif isinstance(goal_data, int): goal = goal_data
                            if goal: break
                    total = hype_train_data.get("total", 0)
                    
                    return "Twitch hype train", {
                        "trigger": f"Twitch hype train {level}",
                        "customData": {
                            "level": level, "progress": progress, "goal": goal, "total": total
                        }
                    }
                return None
            except Exception:
                pass

        def parse_irc_tags(tag_str):
            tags = {}
            if not tag_str: return tags
            for part in tag_str.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    v = v.replace(r"\:", ";").replace(r"\s", " ").replace(r"\\", "\\").replace(r"\r", "\r").replace(r"\n", "\n")
                    tags[k] = v
                else: tags[part] = True
            return tags

        rest = line.strip()
        if not rest or rest.startswith("PING"): return None

        tags = {}
        prefix = None
        if rest.startswith("@"):
            i = rest.find(" ")
            tags = parse_irc_tags(rest[1:i])
            rest = rest[i+1:].lstrip()

        if rest.startswith(":"):
            i = rest.find(" ")
            prefix = rest[1:i]
            rest = rest[i+1:].lstrip()

        def get_best_name(tags_dict, prefix_str):
            dn = tags_dict.get("display-name")
            if dn: return dn
            if prefix_str: return prefix_str.split("!")[0]
            return "Unknown"

        ti = rest.find(" :")
        text = None
        if ti != -1:
            text = rest[ti+2:]
            rest = rest[:ti].strip()
        
        parts = rest.split()
        if not parts: return None
        command = parts[0]

        room_id = tags.get("room-id")
        source_room_id = tags.get("source-room-id")
        is_shared_chat = (room_id and source_room_id and room_id != source_room_id)
        
        base_custom_data = {
            "room_id": room_id,
            "source_room_id": source_room_id,
            "is_shared_chat": is_shared_chat,
            "user_id": tags.get("user-id")
        }

        if command == "PRIVMSG":
            channel = parts[1]
            raw_badges = tags.get("badges", "")
            final_badges = process_twitch_badges(raw_badges)
            final_user = get_best_name(tags, prefix)
            raw_emotes = tags.get("emotes")
            text = process_twitch_emotes(text, raw_emotes)
            
            subscriber_flag = ("subscriber" in raw_badges or "founder" in raw_badges or tags.get("subscriber") == "1")
            is_mod = tags.get("mod") == "1" or "moderator" in raw_badges or "broadcaster" in raw_badges
            is_vip = "vip" in raw_badges

            reward_id = tags.get("custom-reward-id")
            if reward_id:
                return "Twitch redeem (irc)", {
                    "trigger": f"Twitch redeem {reward_id[:8]}...",
                    "customData": {
                        "reward_id": reward_id, "username": final_user, "user": final_user, "message": text,
                        "badges_html": final_badges, "subscriber": subscriber_flag, "mod": is_mod, "vip": is_vip, **base_custom_data
                    }
                }
            bits = tags.get("bits")
            if bits:
                return "Twitch cheer", {
                    "trigger": f"Twitch cheer {bits} bits",
                    "customData": {
                        "bits": bits, "username": final_user, "user": final_user, "message": text,
                        "badges_html": final_badges, "subscriber": subscriber_flag, "mod": is_mod, "vip": is_vip, **base_custom_data
                    }
                }

            return "Twitch chat", {
                "trigger": "Twitch chat",
                "customData": {
                    "username": final_user, "user": final_user, "message": text, "badges_html": final_badges,
                    "color": tags.get("color", "#FFFFFF"), "subscriber": subscriber_flag, "mod": is_mod, "vip": is_vip, **base_custom_data
                }
            }
        elif command == "USERNOTICE":
            msg_id = tags.get("msg-id", "")
            username = tags.get("display-name") or tags.get("login")
            if msg_id == "sharedchatnotice": msg_id = tags.get("source-msg-id", msg_id)
            if msg_id in ["sub", "resub", "subgift", "anonsubgift", "giftpaidupgrade", "submysterygift"]:
                plan = tags.get("msg-param-sub-plan", "")
                return "Twitch sub", {
                    "trigger": "Twitch sub",
                    "customData": {"username": username, "type": msg_id, "plan": plan, "message": text, **base_custom_data}
                }
            elif msg_id == "raid":
                count = tags.get("msg-param-viewerCount", "0")
                raider = tags.get("msg-param-login", username)
                return "Twitch raid", {
                    "trigger": "Twitch raid",
                    "customData": {"username": raider, "viewers": count, **base_custom_data}
                }
        elif command == "CLEARCHAT":
            target_user = parts[1] if len(parts) > 1 else ""
            if "ban-duration" in tags:
                return "Twitch timeout", { "trigger": "Twitch timeout", "customData": {"username": target_user, "duration": tags["ban-duration"], **base_custom_data} }
            else:
                return "Twitch ban", { "trigger": "Twitch ban", "customData": {"username": target_user, **base_custom_data} }

        noisy_commands = {"JOIN", "PART", "PING", "PONG", "CAP", "HOSTTARGET", "RECONNECT", 
                          "353", "366", "001", "002", "003", "004", "375", "372", "376", 
                          "USERSTATE", "ROOMSTATE", "GLOBALUSERSTATE"}
        if command in noisy_commands:
            return None

        return "Twitch other", {
            "trigger": f"Twitch other ({command})",
            "customData": {"command": command, "raw": line, **base_custom_data}
        }

def fetch_twitch_badges_gql():
    gql_url = "https://gql.twitch.tv/gql"
    query = {"query": "query GetGlobalBadges { badges { setID version imageURL } }"}
    headers = {"Client-Id": "kimne78kx3ncx6brgo4mv6wki5h1ko", "User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(gql_url, data=json.dumps(query).encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req) as resp:
            data = json.load(resp)
            badges = data.get("data", {}).get("badges", [])
            for b in badges:
                sid, ver, url_1x = b.get("setID"), b.get("version"), b.get("imageURL")
                url = url_1x
                if url and url.endswith("/1"): url = url[:-2] + "/2"
                if sid and ver and url:
                    if sid not in BADGE_DB: BADGE_DB[sid] = {}
                    BADGE_DB[sid][ver] = url
    except Exception: pass

def load_badges():
    t = threading.Thread(target=fetch_twitch_badges_gql, daemon=True)
    t.start()

def process_twitch_badges(badges_str):
    if not badges_str: return ""
    html = ""
    KEY_MAP = {"subscriber": "SUB", "broadcaster": "BROADCASTER", "moderator": "MOD", "vip": "VIP", "founder": "FOUNDER"}
    for item in badges_str.split(","):
        if "/" in item:
            key, val = item.split("/", 1)
            url = BADGE_DB.get(key, {}).get(val)
            if not url: url = f"https://static-cdn.jtvnw.net/badges/v1/{val}/2" if key in ["broadcaster", "moderator"] else ""
            if url: html += f'[badge:{url}:{key}]'
            else: html += f'[{KEY_MAP.get(key, key.upper())}]'
    return html

def process_twitch_emotes(text, emotes_tag):
    if not emotes_tag or not text: return text
    replacements = []
    try:
        for emote_group in emotes_tag.split("/"):
            if ":" not in emote_group: continue
            eid, positions = emote_group.split(":")
            for pos in positions.split(","):
                if "-" not in pos: continue
                start, end = map(int, pos.split("-"))
                replacements.append((start, end + 1, eid))
    except: return text
    replacements.sort(key=lambda x: x[0], reverse=True)
    for start, end, eid in replacements:
        if start < 0 or end > len(text): continue
        text = text[:start] + f"[twitch_emote:{eid}]" + text[end:]
    return text

AVATAR_CACHE = {}
async def get_twitch_user_avatar_from_id(session, user_id):
    if not user_id: return None, None
    if user_id in AVATAR_CACHE: return AVATAR_CACHE[user_id]
    client_id = "kimne78kx3ncx6brgo4mv6wki5h1ko"
    gql_url = "https://gql.twitch.tv/gql"
    query = {"query": "query($id: ID!) { user(id: $id) { login profileImageURL(width: 70) } }", "variables": {"id": user_id}}
    try:
        headers = {"Client-Id": client_id}
        async with session.post(gql_url, json=query, headers=headers, timeout=5) as resp:
            if resp.status == 200:
                data = await resp.json()
                user_data = data.get("data", {}).get("user")
                if user_data:
                    login, url = user_data.get("login"), user_data.get("profileImageURL")
                    if login and url:
                        AVATAR_CACHE[user_id] = (login, url)
                        return login, url
    except Exception: pass
    return None, None

async def get_twitch_channel_id(session, username):
    client_id = "kimne78kx3ncx6brgo4mv6wki5h1ko"
    gql_url = "https://gql.twitch.tv/gql"
    query = {"query": "query($login: String!) { user(login: $login) { id } }", "variables": {"login": username}}
    try:
        headers = {"Client-Id": client_id}
        async with session.post(gql_url, json=query, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("data", {}).get("user", {}).get("id"):
                    return data['data']['user']['id']
    except Exception: pass
    return None

async def get_reward_title_gql(session, channel_id, reward_id):
    client_id = "kimne78kx3ncx6brgo4mv6wki5h1ko"
    gql_url = "https://gql.twitch.tv/gql"
    query = {"query": "query GetChannelRewards($channelID: ID!) { channel(id: $channelID) { communityPointsSettings { customRewards { id title } } } }", "variables": {"channelID": channel_id}}
    try:
        headers = {"Client-Id": client_id}
        async with session.post(gql_url, json=query, headers=headers, timeout=5) as resp:
            if resp.status == 200:
                data = await resp.json()
                rewards = data.get("data", {}).get("channel", {}).get("communityPointsSettings", {}).get("customRewards", [])
                for r in rewards:
                    if r.get("id") == reward_id: return r.get("title")
    except: pass
    return "Unknown"

async def monitor_twitch_pubsub(session, channel_name, channel_id, event_queue):
    client_id = "kimne78kx3ncx6brgo4mv6wki5h1ko"
    ws_url = f"wss://hermes.twitch.tv/v1?clientId={client_id}"
    topics = [f"community-points-channel-v1.{channel_id}", f"video-playback-by-id.{channel_id}", f"raid.{channel_id}", f"polls.{channel_id}", f"predictions-channel-v1.{channel_id}", f"hype-train-events-v1.{channel_id}"]

    def generate_nonce(length=22):
        chars = string.ascii_letters + string.digits + "_-"
        return ''.join(random.choice(chars) for _ in range(length))

    backoff = 1
    while True:
        try:
            headers = {"Origin": "https://www.twitch.tv", "User-Agent": "Mozilla/5.0"}
            async with session.ws_connect(ws_url, headers=headers, heartbeat=15) as ws:
                for topic in topics:
                    sub_msg = {"type": "subscribe", "id": generate_nonce(), "subscribe": {"id": generate_nonce(), "type": "pubsub", "pubsub": {"topic": topic}}, "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + "Z"}
                    await ws.send_json(sub_msg)
                    await asyncio.sleep(0.1)
                print(f"[Chat] Twitch PubSub connected and subscribed for '{channel_name}'")
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try: data = json.loads(msg.data)
                        except: continue
                        res = TwitchParser.parse_frame(json.dumps(data))
                        if res:
                            ek, fmt = res
                            if ek == "Twitch redeem (pubsub)" and fmt["customData"].get("reward_title") == "Unknown":
                                rid = fmt["customData"].get("reward_id")
                                if rid:
                                    rt = await get_reward_title_gql(session, channel_id, rid)
                                    if rt != "Unknown":
                                        fmt["customData"]["reward_title"] = rt
                                        fmt["trigger"] = f"Twitch redeem {rt}"
                            event_queue.put(("TwitchParser", channel_name, ek, fmt["trigger"], fmt["customData"]))
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

async def monitor_twitch_irc(channel, event_queue):
    host = "irc.chat.twitch.tv"
    port = 6667
    nick = "justinfan123456"
    pwd = "oauth:123123123"
    
    backoff = 1
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.write(b"CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
            writer.write(f"CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership\r\n".encode())
            writer.write(f"PASS {pwd}\r\n".encode())
            writer.write(f"NICK {nick}\r\n".encode())
            writer.write(f"JOIN #{channel}\r\n".encode())
            await writer.drain()
            print(f"[Chat] Twitch IRC connected for '{channel}'")
            backoff = 1

            while True:
                line_bytes = await reader.readline()
                if not line_bytes: break
                line = line_bytes.decode("utf-8", errors="ignore").strip()
                if line.startswith("PING"):
                    writer.write(b"PONG :tmi.twitch.tv\r\n")
                    await writer.drain()
                    continue

                if "WHISPER" in line:
                    try:
                        raw_msg = line
                        tags = {}
                        if raw_msg.startswith("@"):
                            parts = raw_msg.split(" ", 1)
                            tag_str = parts[0][1:]
                            raw_msg = parts[1]
                            for t in tag_str.split(";"):
                                k, v = t.split("=", 1) if "=" in t else (t, "")
                                tags[k] = v
                        parts = raw_msg.split(" WHISPER ", 1)
                        if len(parts) > 1:
                            user_str = parts[0]
                            sender = user_str.split("!", 1)[0]
                            if sender.startswith(":"): sender = sender[1:]
                            rest = parts[1]
                            target, message = rest.split(" :", 1) if " :" in rest else (rest, "")
                            event_queue.put(("TwitchParser", target.strip(), "Twitch whisper", f"Whisper from {sender}", {
                                "username": sender, "message": message, "type": "whisper", "badges_html": "", "color": tags.get("color", "#FF0000")
                            }))
                    except: pass
                
                res = TwitchParser.parse_frame(line)
                if res:
                    ek, fmt = res
                    event_queue.put(("TwitchParser", channel, ek, fmt["trigger"], fmt["customData"]))
        except Exception:
             await asyncio.sleep(backoff)
             backoff = min(backoff * 2, 60)
