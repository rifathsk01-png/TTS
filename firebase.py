import os
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

def _init_firebase():
    """Initialize Firebase app if not already initialized."""
    if firebase_admin._apps:
        return firestore.client()

    raw = os.getenv("FIREBASE_CREDENTIALS")
    if not raw:
        raise ValueError("FIREBASE_CREDENTIALS environment variable is not set.")

    # Accept either a file path or a raw JSON string
    if raw.strip().startswith("{"):
        cred_dict = json.loads(raw)
        cred = credentials.Certificate(cred_dict)
    else:
        cred = credentials.Certificate(raw)

    firebase_admin.initialize_app(cred)
    return firestore.client()


db = _init_firebase()
USERS_COL = "users"
WITHDRAWALS_COL = "withdrawals"


# ─────────────────────────────────────────────
# User Management
# ─────────────────────────────────────────────

def create_user(user_id: int, username: str, full_name: str) -> dict:
    """Create a new user document; skip if already exists."""
    ref = db.collection(USERS_COL).document(str(user_id))
    doc = ref.get()
    if doc.exists:
        return doc.to_dict()

    data = {
        "user_id": user_id,
        "username": username or "",
        "full_name": full_name or "",
        "points": 0,
        "total_generations": 0,
        "is_banned": False,
        "created_at": datetime.utcnow().isoformat(),
    }
    ref.set(data)
    return data


def get_user(identifier) -> dict | None:
    """
    Fetch a user by user_id (int/str) or username (str starting with @
    or plain username string).
    """
    identifier = str(identifier).strip()

    # Try direct document lookup by numeric ID first
    if identifier.lstrip("@").isdigit():
        uid = identifier.lstrip("@")
        doc = db.collection(USERS_COL).document(uid).get()
        if doc.exists:
            return doc.to_dict()
        return None

    # Lookup by username
    uname = identifier.lstrip("@").lower()
    results = (
        db.collection(USERS_COL)
        .where("username", "==", uname)
        .limit(1)
        .stream()
    )
    for doc in results:
        return doc.to_dict()

    return None


def update_points(user_id: int, delta: int) -> int:
    """Add (or subtract) points. Returns new balance."""
    ref = db.collection(USERS_COL).document(str(user_id))
    doc = ref.get()
    if not doc.exists:
        return 0
    current = doc.to_dict().get("points", 0)
    new_balance = max(0, current + delta)
    ref.update({"points": new_balance})
    return new_balance


def increment_generation(user_id: int) -> int:
    """Increment total_generations counter. Returns new count."""
    ref = db.collection(USERS_COL).document(str(user_id))
    doc = ref.get()
    if not doc.exists:
        return 0
    current = doc.to_dict().get("total_generations", 0)
    new_count = current + 1
    ref.update({"total_generations": new_count})
    return new_count


def ban_user(user_id: int) -> bool:
    ref = db.collection(USERS_COL).document(str(user_id))
    if not ref.get().exists:
        return False
    ref.update({"is_banned": True})
    return True


def unban_user(user_id: int) -> bool:
    ref = db.collection(USERS_COL).document(str(user_id))
    if not ref.get().exists:
        return False
    ref.update({"is_banned": False})
    return True


def set_points_direct(user_id: int, amount: int):
    """Set points to a specific value (used by /add and /remove)."""
    ref = db.collection(USERS_COL).document(str(user_id))
    ref.update({"points": max(0, amount)})


# ─────────────────────────────────────────────
# Withdrawal Requests
# ─────────────────────────────────────────────

def save_withdraw_request(
    user_id: int,
    username: str,
    points: int,
    method: str,
    address: str,
) -> str:
    """Save a withdrawal request and return its document ID."""
    ref = db.collection(WITHDRAWALS_COL).document()
    data = {
        "request_id": ref.id,
        "user_id": user_id,
        "username": username or "",
        "points": points,
        "method": method,
        "address": address,
        "status": "pending",
        "requested_at": datetime.utcnow().isoformat(),
    }
    ref.set(data)
    return ref.id
