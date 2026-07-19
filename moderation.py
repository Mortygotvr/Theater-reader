import re

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    HAS_VADER = True
    VADER_ANALYZER = SentimentIntensityAnalyzer()
except ImportError:
    HAS_VADER = False
    VADER_ANALYZER = None

async def check_moderation(msg_text, config_state, session):
    is_suspicious = False
    vader_score = None
    ai_reason = None
    
    mod_config = config_state.get("moderation", {})
    
    if msg_text:
        # Regex Fast-Pass
        if mod_config.get("regex_link_enabled", True):
            url_pattern = re.compile(r"(?i)(?:https?://|www\.)|(?:\b[a-z0-9-]+\s*(?:\.|\bdot\b|\(\.\))\s*(?:com|net|org|tv|io|co|me|xyz)\b)")
            if url_pattern.search(msg_text):
                is_suspicious = True
                ai_reason = "Regex Link Filter"
                
        # Vader Checks
        if not is_suspicious and mod_config.get("vader_enabled") and HAS_VADER and VADER_ANALYZER:
            try:
                scores = VADER_ANALYZER.polarity_scores(msg_text)
                threshold = mod_config.get("vader_threshold", -0.5)
                vader_score = scores['compound']
                
                if vader_score <= threshold:
                    is_suspicious = True
                    ai_reason = f"Vader Sentiment ({vader_score})"
            except Exception as e:
                pass
                
        # Ollama Checks
        if not is_suspicious and mod_config.get("ollama_enabled"):
            try:
                ollama_url = mod_config.get("ollama_url", "http://localhost:11434")
                base_url = ollama_url.replace("/api/generate", "")
                ollama_model = mod_config.get("ollama_model", "llama3")
                ollama_prompt = mod_config.get("ollama_prompt", "")
                
                payload = {
                    "model": ollama_model,
                    "prompt": f'Message: "{msg_text}"',
                    "stream": False,
                    "options": {"temperature": 0.1}
                }
                
                if ollama_prompt:
                    payload["system"] = ollama_prompt
                
                async with session.post(f"{base_url}/api/generate", json=payload, timeout=5) as resp:
                    if resp.status == 200:
                        ollama_data = await resp.json()
                        result_text = ollama_data.get("response", "").strip().upper()
                        if "FLAGGED" in result_text:
                            is_suspicious = True
                            ai_reason = "Ollama Flagged"
            except Exception as e:
                pass

    return is_suspicious, vader_score, ai_reason
