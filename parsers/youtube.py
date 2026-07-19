import asyncio
import urllib.parse
import logging
import re

YOUTUBE_AVATAR_CACHE = {}

class YouTubeParser:
    INPUT_TYPE = "url"
    EVENTS = ["chat_message", "paid_message", "sticker_message", "member_message", "gift_message"]

async def get_youtube_channel_avatar(session, video_url):
    if not video_url: return None
    if video_url in YOUTUBE_AVATAR_CACHE: return YOUTUBE_AVATAR_CACHE[video_url]
    
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get(video_url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                html = await resp.text()
                m = re.search(r'\"videoOwnerRenderer\"\:\{\"thumbnail\"\:\{\"thumbnails\"\:\[\{\"url\"\:\"([^\"]+)\"', html)
                if m:
                    url = m.group(1).replace("\\u0026", "&")
                    url = re.sub(r'=s\d+-', '=s88-', url)
                    YOUTUBE_AVATAR_CACHE[video_url] = url
                    return url
    except Exception:
        pass
    return None

async def monitor_youtube_pytchat(input_url, event_queue):
    logging.getLogger("pytchat").setLevel(logging.CRITICAL)
    try:
        import pytchat
    except ImportError:
        print("[YouTube] pytchat not installed. YouTube support disabled.")
        return

    target_id = None
    try:
        parsed = urllib.parse.urlparse(input_url)
        if "v" in urllib.parse.parse_qs(parsed.query):
            target_id = urllib.parse.parse_qs(parsed.query)["v"][0]
    except:
        pass
    
    if not target_id: return 
    
    try:
        chat = pytchat.create(video_id=target_id, interruptable=False)
        print(f"[Chat] YouTube chat monitoring connected for '{input_url}'")
    except Exception:
        return
    
    while True:
        try:
            if not chat.is_alive():
                await asyncio.sleep(5)
                continue

            data = await asyncio.to_thread(chat.get)
            items = data.items if hasattr(data, "items") else data
            
            for c in items:
                if c.amountString:
                    ek = "paid_message"
                    trigger = f"Super Chat: {c.amountString}"
                    if c.type == "superSticker":
                        ek = "sticker_message"
                        trigger = f"Super Sticker: {c.amountString}"
                    
                    event_queue.put(("YouTubeParser", input_url, ek, trigger, {
                        "author": c.author.name,
                        "amount": c.amountString,
                        "message": c.message,
                        "image": c.author.imageUrl
                    }))
                    continue
                
                if c.type == "newSponsor":
                     event_queue.put(("YouTubeParser", input_url, "member_message", "New Member!", {
                         "author": c.author.name
                     }))
                     continue

                final_message = c.message
                if hasattr(c, 'messageEx') and c.messageEx:
                    try:
                        final_message = ""
                        for fragment in c.messageEx:
                            if isinstance(fragment, str):
                                final_message += fragment
                            elif isinstance(fragment, dict):
                                if 'url' in fragment:
                                    final_message += f"[yt_emoji:{fragment['url']}]"
                                else:
                                    final_message += str(fragment.get('txt', ''))
                    except Exception:
                        final_message = c.message

                event_queue.put(("YouTubeParser", input_url, "chat_message", "YouTube Chat", {
                    "username": c.author.name,
                    "author": c.author.name,
                    "user_id": getattr(c.author, "channelId", ""),
                    "message": final_message,
                    "badges": getattr(c.author, "badgeUrl", ""),
                    "image": getattr(c.author, "imageUrl", ""),
                    "id": getattr(c, "id", ""),
                    "subscriber": getattr(c.author, "isChatSponsor", False),
                    "mod": getattr(c.author, "isChatOwner", False) or getattr(c.author, "isChatModerator", False),
                    "vip": getattr(c.author, "isVerified", False)
                }))

            await asyncio.sleep(0.5)
        except Exception:
            await asyncio.sleep(5)
