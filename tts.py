import os
import sys
import queue
import threading
import subprocess
import tempfile
import math
import struct
import wave
import shutil
from config import BASE_DIR, STOP_EVENT

HAS_TTS = True
tts_queue = queue.Queue()

def _play_audio_stream(file_path, device_name=None, volume=1.0):
    if not os.path.exists(file_path):
        return
        
    vol_val = int(volume * 100)

    if sys.platform == "win32":
        ffplay_path = os.path.join(BASE_DIR, "ffplay.exe")
        if not os.path.exists(ffplay_path):
            ffplay_path = shutil.which("ffplay") or "ffplay"
        cmd = [
            ffplay_path,
            "-nodisp",
            "-autoexit",
            "-vn",
            "-sn",
            "-fast",
            "-analyzeduration", "0",
            "-probesize", "32",
            "-fflags", "nobuffer",
            "-threads", "1"
        ]
        if vol_val != 100:
            cmd.extend(["-volume", str(vol_val)])
        cmd.append(file_path)
        
        env = os.environ.copy()
        if device_name and device_name.lower() != "system default":
            env["SDL_AUDIO_DEVICE_NAME"] = device_name
            env["SDL_AUDIODRIVER"] = ""

        try:
            subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e:
            print(f"[TTS] ffplay Error: {e}")

    elif sys.platform == "darwin":
        subprocess.run(["afplay", "-v", str(volume), file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    else:
        # Linux / Unix
        ffplay_path = os.path.join(BASE_DIR, "ffplay")
        if not os.path.exists(ffplay_path):
            ffplay_path = shutil.which("ffplay")

        if ffplay_path:
            cmd = [
                ffplay_path,
                "-nodisp",
                "-autoexit",
                "-vn",
                "-sn",
                "-fast",
                "-analyzeduration", "0",
                "-probesize", "32",
                "-fflags", "nobuffer",
                "-threads", "1"
            ]
            if vol_val != 100:
                cmd.extend(["-volume", str(vol_val)])
            cmd.append(file_path)

            env = os.environ.copy()
            if device_name and device_name.lower() != "system default":
                sink_name = device_name
                if "[" in device_name and device_name.endswith("]"):
                    sink_name = device_name.rsplit("[", 1)[1].rstrip("]")
                env["PULSE_SINK"] = sink_name
                env["SDL_AUDIO_DEVICE_NAME"] = sink_name

            try:
                subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except Exception as e:
                print(f"[TTS] ffplay Error: {e}")
        else:
            # Fallback audio players for Linux
            player = shutil.which("paplay") or shutil.which("pw-play") or shutil.which("aplay")
            if player:
                cmd = [player]
                env = os.environ.copy()
                if device_name and device_name.lower() != "system default":
                    sink_name = device_name
                    if "[" in device_name and device_name.endswith("]"):
                        sink_name = device_name.rsplit("[", 1)[1].rstrip("]")
                    if "paplay" in player:
                        cmd.extend(["-d", sink_name])
                    else:
                        env["PULSE_SINK"] = sink_name
                cmd.append(file_path)
                try:
                    subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                except Exception as e:
                    print(f"[TTS] Audio Playback Error: {e}")


def _generate_bell_wav(bell_path, output_path):
    if not (bell_path and os.path.isfile(bell_path)):
        duration = 0.2
        f = 800.0
        sample_rate = 44100
        num_samples = int(sample_rate * duration)
        samples = (math.sin(2 * math.pi * k * f / sample_rate) for k in range(num_samples))
        data = b''.join(struct.pack('<h', int(sample * 1.0 * (1.0 - k/num_samples) * 32767)) 
                      for k, sample in enumerate(samples))
        with wave.open(output_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(data)
        return True
    return False

def tts_worker():
    if not HAS_TTS: return

    while not STOP_EVENT.is_set():
        try:
            item = tts_queue.get(timeout=1)
            if item is None: break
            
            if len(item) == 4:
                text, volume, rate, voice_id = item
                device_name = None
            else:
                text, volume, rate, voice_id, device_name = item
                
            try:
                if text == "[BELL]":
                    bell_path = str(voice_id).strip() if voice_id else ""
                    
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as gen_tmp:
                        gen_file = gen_tmp.name
                        
                    is_generated = _generate_bell_wav(bell_path, gen_file)
                    source_file = gen_file if is_generated else bell_path
                    
                    try:
                        _play_audio_stream(source_file, device_name, volume=volume)
                    except Exception as e:
                        print(f"[TTS] Bell Playback Error: {e}")
                    finally:
                        for f in [gen_file]:
                            if f and os.path.exists(f):
                                try: os.remove(f)
                                except: pass
                    continue

                if not voice_id:
                    voice_id = "en_US-lessac-low.onnx"

                model_base_path = os.path.join(BASE_DIR, "piper")

                if not voice_id.endswith(".onnx"):
                    voice_id += ".onnx"
                    
                model_path = os.path.join(model_base_path, voice_id)
                if not os.path.exists(model_path):
                    model_path = os.path.join(model_base_path, "en_US-lessac-low.onnx")

                piper_name = "piper.exe" if sys.platform == "win32" else "piper"
                piper_exe = os.path.join(model_base_path, piper_name)
                
                if not os.path.exists(piper_exe):
                    sys_piper = shutil.which("piper")
                    if sys_piper:
                        piper_exe = sys_piper

                if os.path.exists(piper_exe) and sys.platform != "win32":
                    try:
                        if not os.access(piper_exe, os.X_OK):
                            os.chmod(piper_exe, 0o755)
                    except Exception:
                        pass


                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    temp_filename = tmp.name
                    
                try:
                    process = subprocess.Popen(
                        [piper_exe, "-m", model_path, "-f", temp_filename],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    stdout, stderr = process.communicate(input=text.encode('utf-8'))
                except Exception as e:
                    print(f"[TTS] Piper Error: {e}")
                
                try:
                    _play_audio_stream(temp_filename, device_name, volume=volume)
                except Exception as e:
                    print(f"[TTS] Audio Playback Error: {e}")
                finally:
                    if os.path.exists(temp_filename):
                        try: os.remove(temp_filename)
                        except: pass
                        
            except Exception as e:
                print(f"[TTS] Worker Error: {e}")
                    
            tts_queue.task_done()
        except queue.Empty:
            continue

def start_tts():
    if HAS_TTS:
        threading.Thread(target=tts_worker, daemon=True).start()
