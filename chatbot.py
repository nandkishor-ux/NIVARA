import logging
import os

from dotenv import load_dotenv
from huggingface_hub import InferenceClient

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nivara.chatbot")

MODEL_ID = "meta-llama/Llama-3.2-3B-Instruct"
API_TOKEN = os.getenv("HF_API_TOKEN")

SYSTEM_PROMPT = """You are "Nivara Buddy," a supportive AI companion inside the NIVARA hostel wellness platform.
Students come to you when they feel stressed, lonely, low on energy, or just want to talk.
You are a first line of emotional support — not a therapist, not a doctor, and not a diagnostic tool.

You detect conversational MOOD SIGNALS, not medical conditions. You never state or imply a
diagnosis, never use clinical terminology with the student, never claim to know their mental
health status, and never try to replace a counselor, doctor, or trusted adult.

Keep replies short (2-4 sentences), warm, and conversational — not clinical or robotic. Respond
in whatever language the student uses (English, Hindi, or Hinglish).

If a student describes ongoing sadness, loneliness, or stress, gently suggest a specific human
connection: hostel counseling desk, warden, or a Peer Buddy.

If a student expresses any intent or ideation around self-harm, suicide, or being in immediate
danger: respond with direct care, do not minimize or change the subject, clearly provide
emergency contact info, and encourage them to reach a real person right now."""

_client = InferenceClient(model=MODEL_ID, token=API_TOKEN)

CRISIS_KEYWORDS = [
    "end my life",
    "end it all",
    "kill myself",
    "killing myself",
    "take my own life",
    "ending my life",
    "don't want to live",
    "do not want to live",
    "want to die",
    "wish i was dead",
    "wish i were dead",
    "hurt myself",
    "self-harm",
    "self harm",
    "suicide",
]


def check_crisis_keywords(message):
    text = message.lower()
    return any(keyword in text for keyword in CRISIS_KEYWORDS)


def get_buddy_response(message, conversation_history=None):
    conversation_history = conversation_history or []

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": message})

    log.info("Calling HuggingFace Inference API - model=%s", MODEL_ID)
    log.info("API_TOKEN set: %s", bool(API_TOKEN))
    try:
        response = _client.chat_completion(
            messages=messages,
            max_tokens=512,
            temperature=0.7,
        )
    except Exception as exc:
        log.exception("HuggingFace Inference API call failed: %s", exc)
        raise

    return response.choices[0].message.content