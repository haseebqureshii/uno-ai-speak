"""
Test script for Google Gemini Multimodal Live API (gemini-2.0-flash-exp)

This standalone script tests real-time audio back-and-forth with Gemini Live,
bypassing all app abstractions. It handles cold-start speech generation,
PCM16 audio streaming, and voice activity responses.

Dependencies:
    pip install websockets pyaudio python-dotenv

Environment:
    API key is loaded from .env file. Create one in the project root:
    GEMINI_API_KEY=your-api-key-here
"""

import asyncio
import base64
import json
import os
import sys

import websockets
import pyaudio
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Audio Configuration
SAMPLE_RATE = 24000  # Gemini expects 24kHz
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 1024  # Number of frames per buffer

# Initialize PyAudio
audio = pyaudio.PyAudio()

# Global variables for audio streams
mic_stream = None
speaker_stream = None

# First model audio arrival timestamp
first_audio_time = None


def log(message: str):
    print(f"[{asyncio.get_event_loop().time():.3f}] {message}")


def get_audio_input_devices():
    """List available audio input devices."""
    devices = []
    for i in range(audio.get_device_count()):
        dev = audio.get_device_info_by_index(i)
        if dev['maxInputChannels'] > 0:
            devices.append((i, dev['name']))
    return devices

def get_audio_output_devices():
    """List available audio output devices."""
    devices = []
    for i in range(audio.get_device_count()):
        dev = audio.get_device_info_by_index(i)
        if dev['maxOutputChannels'] > 0:
            devices.append((i, dev['name']))
    return devices

async def send_audio_loop(websocket):
    """Capture microphone audio and send to Gemini."""
    global mic_stream

    # List input devices
    input_devices = get_audio_input_devices()
    if not input_devices:
        log("No audio input devices found. Running in text-trigger fallback mode.")
        return

    log("Available input devices:")
    for idx, name in input_devices:
        log(f"  {idx}: {name}")

    device_index = 0  # Default to first device
    try:
        mic_stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK,
            input_device_index=device_index
        )
        log(f"Microphone stream opened on device {device_index}")
    except Exception as e:
        log(f"Failed to open microphone stream: {e}")
        return

    try:
        while True:
            try:
                data = mic_stream.read(CHUNK, exception_on_overflow=False)
                b64_data = base64.b64encode(data).decode('utf-8')
                
                message = {
                    "realtime_input": {
                        "audio": {
                            "data": b64_data,
                            "mime_type": "audio/pcm;rate=24000"
                        }
                    }
                }
                await websocket.send(json.dumps(message))
                log(f"Sent audio chunk: {len(data)} bytes")
            
            except Exception as e:
                log(f"Error sending audio: {e}")
                break

            await asyncio.sleep(0.01)  # ~100ms chunks

    finally:
        if mic_stream:
            mic_stream.stop_stream()
            mic_stream.close()

async def receive_audio_loop(websocket):
    """Receive audio from Gemini and play through speaker."""
    global speaker_stream, first_audio_time

    # List output devices
    output_devices = get_audio_output_devices()
    if not output_devices:
        log("No audio output devices found.")
        return

    log("Available output devices:")
    for idx, name in output_devices:
        log(f"  {idx}: {name}")

    # Try to find a working output device
    speaker_stream = None
    for idx, name in output_devices:
        try:
            speaker_stream = audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                output=True,
                frames_per_buffer=CHUNK,
                output_device_index=idx
            )
            log(f"Speaker stream opened on device {idx}: {name}")
            break
        except Exception as e:
            log(f"Failed to open speaker stream on device {idx}: {e}")
            continue
    
    if speaker_stream is None:
        log("Failed to open speaker stream on all devices")
        return

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                
                # Look for server audio content
                if 'serverContent' in data:
                    parts = data['serverContent']['modelTurn']['parts']
                    for part in parts:
                        if 'inlineData' in part:
                            inline = part['inlineData']
                            if inline.get('mimeType') == 'audio/pcm;rate=24000':
                                audio_b64 = inline['data']
                                audio_data = base64.b64decode(audio_b64)
                                
                                # Log first audio arrival
                                if first_audio_time is None:
                                    first_audio_time = asyncio.get_event_loop().time()
                                    log(f"FIRST AUDIO BYTE RECEIVED at {first_audio_time:.3f}")
                                
                                speaker_stream.write(audio_data)
                                log(f"Played audio chunk: {len(audio_data)} bytes")

            except Exception as e:
                log(f"Error processing message: {e}")
                continue

    except Exception as e:
        log(f"Receive loop error: {e}")
    
    finally:
        if speaker_stream:
            speaker_stream.stop_stream()
            speaker_stream.close()

async def main():
    global first_audio_time

    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        log("GEMINI_API_KEY environment variable not set.")
        return

    uri = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={api_key}"
    
    log(f"Connecting to {uri}")
    try:
        async with websockets.connect(uri) as websocket:
            log("Connected to Gemini Live WebSocket")

            # Send setup frame
            setup_message = {
                "setup": {
                    "model": "models/gemini-2.5-flash-native-audio-preview-12-2025",
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "temperature": 0.7,
                        "topK": 40,
                        "topP": 0.95
                    },
                    "systemInstruction": {
                        "parts": [
                            {
                                "text": "You are Coach Alex, a Socratic Spanish language tutor. Engage learners in natural conversation, ask open-ended questions, and provide gentle corrections. Speak only in Spanish at an A2 level."
                            }
                        ]
                    }
                }
            }
            
            await websocket.send(json.dumps(setup_message))
            log("Setup frame sent")

            # Wait for setupComplete
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10)
                data = json.loads(response)
                if 'setupComplete' in data:
                    log("Setup complete received")
                else:
                    log(f"Unexpected response: {data}")
                    return
            except asyncio.TimeoutError:
                log("Timeout waiting for setupComplete")
                return

            # Send cold-start clientContent to make Gemini speak first
            cold_start_message = {
                "clientContent": {
                    "turns": [
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": "Hello, student. Let's begin."
                                }
                            ]
                        }
                    ],
                    "turnComplete": True
                }
            }
            
            await websocket.send(json.dumps(cold_start_message))
            log("Cold-start trigger sent - Coach Alex should speak first")

            # Start concurrent audio loops
            send_task = asyncio.create_task(send_audio_loop(websocket))
            receive_task = asyncio.create_task(receive_audio_loop(websocket))

            # Wait for both tasks
            await asyncio.gather(send_task, receive_task)

    except Exception as e:
        log(f"Connection error: {e}")
    
    finally:
        # Close PyAudio
        audio.terminate()
        log("Audio resources terminated")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("\nShutting down...")
        if audio:
            audio.terminate()