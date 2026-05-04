"""
main.py — Guard Pay Backend
============================
Nigerian mobile money demo platform backed by the fraud detection API.
"""

import os, json, random, string, hashlib
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from database import get_db, init_db, hash_pin, generate_bvn, generate_account_number
from fraud_client import score_transaction

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Guard Pay", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

NIGERIAN_BANKS = ["GTB", "Access", "Zenith", "UBA", "Kuda",
                  "Opay", "Moniepoint", "PalmPay", "FCMB", "Sterling"]
NIGERIAN_STATES = ["Lagos", "Abuja", "Kano", "Rivers", "Oyo",
                   "Kaduna", "Anambra", "Delta", "Enugu", "Ogun"]

# Serve frontend
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

@app.on_event("startup")
def startup():
    init_db()

# ── Helper ────────────────────────────────────────────────────────────────────

def gen_ref():
    chars = string.ascii_uppercase + string.digits
    return "GP" + "".join(random.choices(chars, k=10))

def get_velocity(conn, account: str):
    now = datetime.utcnow()
    def count(minutes):
        since = (now - timedelta(minutes=minutes)).isoformat()
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM transactions "
            "WHERE sender_account=? AND created_at>=? AND status='completed'",
            (account, since)
        ).fetchone()
        return int(row[0]), float(row[1])
    c1h,  a1h  = count(60)
    c6h,  _    = count(360)
    c24h, a24h = count(1440)
    return c1h, c6h, c24h, a24h

# ── Schemas ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    full_name : str
    phone     : str
    pin       : str
    state     : str = "Lagos"

class LoginRequest(BaseModel):
    phone : str
    pin   : str

class TransferRequest(BaseModel):
    sender_account      : str
    beneficiary_account : str
    amount              : float
    narration           : str = ""
    channel             : str = "mobile_app"
    pin                 : str

class ReviewRequest(BaseModel):
    transaction_ref : str
    action          : str   # APPROVE or REJECT
    note            : str = ""
    admin_phone     : str

# ── Auth endpoints ────────────────────────────────────────────────────────────

@app.post("/api/register")
def register(req: RegisterRequest):
    conn = get_db()
    # Check phone not taken
    exists = conn.execute(
        "SELECT id FROM users WHERE phone=?", (req.phone,)
    ).fetchone()
    if exists:
        conn.close()
        raise HTTPException(400, "Phone number already registered.")

    # Check user limit
    count = conn.execute(
        "SELECT COUNT(*) FROM users WHERE is_admin=0"
    ).fetchone()[0]
    if count >= 20:
        conn.close()
        raise HTTPException(400, "User limit reached (20 users max for this demo).")

    bvn     = generate_bvn()
    account = generate_account_number()

    conn.execute("""
        INSERT INTO users (full_name, phone, bvn, account_number, pin_hash, state)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (req.full_name, req.phone, bvn, account, hash_pin(req.pin), req.state))
    conn.commit()

    user = conn.execute(
        "SELECT * FROM users WHERE phone=?", (req.phone,)
    ).fetchone()
    conn.close()

    return {
        "message"        : "Registration successful",
        "account_number" : account,
        "bvn"            : bvn,
        "balance"        : 50000.0,
        "full_name"      : req.full_name,
    }

@app.post("/api/login")
def login(req: LoginRequest):
    conn  = get_db()
    user  = conn.execute(
        "SELECT * FROM users WHERE phone=?", (req.phone,)
    ).fetchone()
    conn.close()

    if not user:
        raise HTTPException(401, "Phone number not found.")
    if user["pin_hash"] != hash_pin(req.pin):
        raise HTTPException(401, "Incorrect PIN.")
    if user["is_blocked"]:
        raise HTTPException(403, "Account blocked. Contact support.")

    return {
        "full_name"      : user["full_name"],
        "phone"          : user["phone"],
        "account_number" : user["account_number"],
        "balance"        : user["balance"],
        "state"          : user["state"],
        "is_admin"       : bool(user["is_admin"]),
        "bvn"            : user["bvn"],
    }

@app.get("/api/balance/{account_number}")
def get_balance(account_number: str):
    conn = get_db()
    user = conn.execute(
        "SELECT balance, full_name FROM users WHERE account_number=?",
        (account_number,)
    ).fetchone()
    conn.close()
    if not user:
        raise HTTPException(404, "Account not found.")
    return {"balance": user["balance"], "full_name": user["full_name"]}

@app.get("/api/lookup/{account_number}")
def lookup_account(account_number: str):
    conn = get_db()
    user = conn.execute(
        "SELECT full_name, account_number, bank FROM users WHERE account_number=?",
        (account_number,)
    ).fetchone()
    conn.close()
    if not user:
        raise HTTPException(404, "Account not found.")
    return {"full_name": user["full_name"], "account_number": user["account_number"]}

# ── Transfer endpoint ─────────────────────────────────────────────────────────

@app.post("/api/transfer")
def transfer(req: TransferRequest):
    conn = get_db()

    # Validate sender
    sender = conn.execute(
        "SELECT * FROM users WHERE account_number=?", (req.sender_account,)
    ).fetchone()
    if not sender:
        conn.close()
        raise HTTPException(404, "Sender account not found.")
    if sender["pin_hash"] != hash_pin(req.pin):
        conn.close()
        raise HTTPException(401, "Incorrect PIN.")
    if sender["is_blocked"]:
        conn.close()
        raise HTTPException(403, "Your account is currently blocked.")
    if sender["balance"] < req.amount:
        conn.close()
        raise HTTPException(400, "Insufficient balance.")
    if req.amount <= 0 or req.amount > 5_000_000:
        conn.close()
        raise HTTPException(400, "Amount must be between ₦1 and ₦5,000,000.")

    # Validate beneficiary
    beneficiary = conn.execute(
        "SELECT * FROM users WHERE account_number=?", (req.beneficiary_account,)
    ).fetchone()
    if not beneficiary:
        conn.close()
        raise HTTPException(404, "Beneficiary account not found.")
    if req.sender_account == req.beneficiary_account:
        conn.close()
        raise HTTPException(400, "Cannot transfer to yourself.")

    # Check if new beneficiary
    prev_txn = conn.execute(
        "SELECT id FROM transactions WHERE sender_account=? AND beneficiary_account=? AND status='completed'",
        (req.sender_account, req.beneficiary_account)
    ).fetchone()
    is_new_bene = prev_txn is None

    # Velocity
    v1h, v6h, v24h, cum24h = get_velocity(conn, req.sender_account)

    # Generate ref
    ref = gen_ref()

    # Score with fraud API
    score_result = score_transaction(
        transaction_ref     = ref,
        sender_account      = req.sender_account,
        beneficiary_account = req.beneficiary_account,
        amount              = req.amount,
        channel             = req.channel,
        sender_bank         = "GuardPay",
        state               = sender["state"],
        sim_age_days        = 365,
        velocity_1h         = v1h,
        velocity_6h         = v6h,
        velocity_24h        = v24h,
        cumulative_24h      = cum24h + req.amount,
        is_new_beneficiary  = is_new_bene,
    )

    risk_score  = score_result.get("risk_score", 0.1)
    risk_band   = score_result.get("risk_band", "LOW")
    action      = score_result.get("recommended_action", "ALLOW")
    top_signals = json.dumps(score_result.get("top_signals", []))
    shap_exp    = json.dumps(score_result.get("shap_explanation", {}))
    ndpa_note   = score_result.get("ndpa_note", "")

    # Determine transaction status
    if action == "ALLOW":
        status = "completed"
    elif action == "STEP_UP_AUTH":
        status = "completed"   # demo: allow with flag
    elif action in ["HUMAN_REVIEW", "BLOCK_AND_ALERT"]:
        status = "pending_review"
    else:
        status = "completed"

    # Insert transaction
    conn.execute("""
        INSERT INTO transactions
        (transaction_ref, sender_account, beneficiary_account, amount,
         channel, narration, status, risk_score, risk_band,
         recommended_action, top_signals, shap_explanation, ndpa_note,
         velocity_1h, velocity_6h, velocity_24h, cumulative_24h, is_new_beneficiary)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ref, req.sender_account, req.beneficiary_account, req.amount,
        req.channel, req.narration, status, risk_score, risk_band,
        action, top_signals, shap_exp, ndpa_note,
        v1h, v6h, v24h, cum24h + req.amount, int(is_new_bene)
    ))

    # Debit/credit only if completed
    if status == "completed":
        conn.execute(
            "UPDATE users SET balance = balance - ? WHERE account_number=?",
            (req.amount, req.sender_account)
        )
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE account_number=?",
            (req.amount, req.beneficiary_account)
        )

    conn.commit()

    # Refresh balance
    new_balance = conn.execute(
        "SELECT balance FROM users WHERE account_number=?", (req.sender_account,)
    ).fetchone()["balance"]
    conn.close()

    return {
        "transaction_ref"   : ref,
        "status"            : status,
        "risk_score"        : risk_score,
        "risk_band"         : risk_band,
        "recommended_action": action,
        "top_signals"       : score_result.get("top_signals", []),
        "ndpa_note"         : ndpa_note,
        "new_balance"       : new_balance,
        "message"           : (
            "Transfer successful." if status == "completed"
            else "Transfer is under review by our compliance team (NDPA §37(1))."
        )
    }

# ── Transaction history ───────────────────────────────────────────────────────

@app.get("/api/transactions/{account_number}")
def get_transactions(account_number: str, limit: int = 20):
    conn = get_db()
    rows = conn.execute("""
        SELECT t.*, 
               u1.full_name as sender_name,
               u2.full_name as beneficiary_name
        FROM transactions t
        LEFT JOIN users u1 ON t.sender_account = u1.account_number
        LEFT JOIN users u2 ON t.beneficiary_account = u2.account_number
        WHERE t.sender_account=? OR t.beneficiary_account=?
        ORDER BY t.created_at DESC LIMIT ?
    """, (account_number, account_number, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Admin endpoints ───────────────────────────────────────────────────────────

@app.get("/api/admin/transactions")
def admin_transactions(admin_phone: str, limit: int = 100):
    conn  = get_db()
    admin = conn.execute(
        "SELECT is_admin FROM users WHERE phone=?", (admin_phone,)
    ).fetchone()
    if not admin or not admin["is_admin"]:
        conn.close()
        raise HTTPException(403, "Admin access required.")
    rows = conn.execute("""
        SELECT t.*,
               u1.full_name as sender_name,
               u2.full_name as beneficiary_name
        FROM transactions t
        LEFT JOIN users u1 ON t.sender_account = u1.account_number
        LEFT JOIN users u2 ON t.beneficiary_account = u2.account_number
        ORDER BY t.created_at DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/admin/users")
def admin_users(admin_phone: str):
    conn  = get_db()
    admin = conn.execute(
        "SELECT is_admin FROM users WHERE phone=?", (admin_phone,)
    ).fetchone()
    if not admin or not admin["is_admin"]:
        conn.close()
        raise HTTPException(403, "Admin access required.")
    rows = conn.execute(
        "SELECT id, full_name, phone, account_number, balance, state, "
        "created_at, is_blocked FROM users WHERE is_admin=0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/admin/queue")
def compliance_queue(admin_phone: str):
    conn  = get_db()
    admin = conn.execute(
        "SELECT is_admin FROM users WHERE phone=?", (admin_phone,)
    ).fetchone()
    if not admin or not admin["is_admin"]:
        conn.close()
        raise HTTPException(403, "Admin access required.")
    rows = conn.execute("""
        SELECT t.*,
               u1.full_name as sender_name,
               u2.full_name as beneficiary_name
        FROM transactions t
        LEFT JOIN users u1 ON t.sender_account = u1.account_number
        LEFT JOIN users u2 ON t.beneficiary_account = u2.account_number
        WHERE t.status = 'pending_review'
        ORDER BY t.risk_score DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/admin/review")
def review_transaction(req: ReviewRequest):
    conn  = get_db()
    admin = conn.execute(
        "SELECT is_admin FROM users WHERE phone=?", (req.admin_phone,)
    ).fetchone()
    if not admin or not admin["is_admin"]:
        conn.close()
        raise HTTPException(403, "Admin access required.")

    txn = conn.execute(
        "SELECT * FROM transactions WHERE transaction_ref=?",
        (req.transaction_ref,)
    ).fetchone()
    if not txn:
        conn.close()
        raise HTTPException(404, "Transaction not found.")

    new_status = "completed" if req.action == "APPROVE" else "rejected"

    conn.execute("""
        UPDATE transactions
        SET status=?, reviewed_by=?, review_action=?, review_note=?
        WHERE transaction_ref=?
    """, (new_status, req.admin_phone, req.action, req.note, req.transaction_ref))

    if req.action == "APPROVE":
        conn.execute(
            "UPDATE users SET balance = balance - ? WHERE account_number=?",
            (txn["amount"], txn["sender_account"])
        )
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE account_number=?",
            (txn["amount"], txn["beneficiary_account"])
        )

    conn.commit()
    conn.close()
    return {"message": f"Transaction {req.action}D successfully."}

@app.get("/api/admin/stats")
def admin_stats(admin_phone: str):
    conn  = get_db()
    admin = conn.execute(
        "SELECT is_admin FROM users WHERE phone=?", (admin_phone,)
    ).fetchone()
    if not admin or not admin["is_admin"]:
        conn.close()
        raise HTTPException(403, "Admin access required.")

    total_txns    = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    total_users   = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=0").fetchone()[0]
    pending       = conn.execute("SELECT COUNT(*) FROM transactions WHERE status='pending_review'").fetchone()[0]
    total_volume  = conn.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE status='completed'").fetchone()[0]
    high_risk     = conn.execute("SELECT COUNT(*) FROM transactions WHERE risk_band IN ('HIGH','CRITICAL')").fetchone()[0]
    avg_score     = conn.execute("SELECT COALESCE(AVG(risk_score),0) FROM transactions").fetchone()[0]

    band_counts = {}
    for band in ["LOW","MEDIUM","HIGH","CRITICAL"]:
        c = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE risk_band=?", (band,)
        ).fetchone()[0]
        band_counts[band] = c

    conn.close()
    return {
        "total_transactions" : total_txns,
        "total_users"        : total_users,
        "pending_review"     : pending,
        "total_volume_ngn"   : round(total_volume, 2),
        "high_risk_count"    : high_risk,
        "avg_risk_score"     : round(avg_score, 4),
        "band_distribution"  : band_counts,
    }

# ── Serve frontend ────────────────────────────────────────────────────────────

@app.get("/favicon.ico")
def favicon():
    # Return a minimal favicon to suppress 404 logs
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def serve_app():
    html_path = os.path.join(STATIC_DIR, "app.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h1>Guard Pay — place app.html in static/</h1>")

class UpdateProfileRequest(BaseModel):
    account_number : str
    pin            : str
    new_name       : Optional[str] = None
    new_state      : Optional[str] = None
    new_phone      : Optional[str] = None

class ChangePinRequest(BaseModel):
    account_number : str
    old_pin        : str
    new_pin        : str

@app.post("/api/profile/update")
def update_profile(req: UpdateProfileRequest):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE account_number=?", (req.account_number,)
    ).fetchone()
    if not user:
        conn.close()
        raise HTTPException(404, "Account not found.")
    if user["pin_hash"] != hash_pin(req.pin):
        conn.close()
        raise HTTPException(401, "Incorrect PIN.")

    if req.new_phone:
        exists = conn.execute(
            "SELECT id FROM users WHERE phone=? AND account_number!=?",
            (req.new_phone, req.account_number)
        ).fetchone()
        if exists:
            conn.close()
            raise HTTPException(400, "Phone number already in use.")

    updates = []
    values  = []
    if req.new_name:
        updates.append("full_name=?")
        values.append(req.new_name)
    if req.new_state:
        updates.append("state=?")
        values.append(req.new_state)
    if req.new_phone:
        updates.append("phone=?")
        values.append(req.new_phone)

    if updates:
        values.append(req.account_number)
        conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE account_number=?",
            values
        )
        conn.commit()

    updated = conn.execute(
        "SELECT * FROM users WHERE account_number=?", (req.account_number,)
    ).fetchone()
    conn.close()
    return {
        "full_name" : updated["full_name"],
        "phone"     : updated["phone"],
        "state"     : updated["state"],
    }

@app.post("/api/profile/change-pin")
def change_pin(req: ChangePinRequest):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE account_number=?", (req.account_number,)
    ).fetchone()
    if not user:
        conn.close()
        raise HTTPException(404, "Account not found.")
    if user["pin_hash"] != hash_pin(req.old_pin):
        conn.close()
        raise HTTPException(401, "Current PIN is incorrect.")
    if len(req.new_pin) != 4 or not req.new_pin.isdigit():
        conn.close()
        raise HTTPException(400, "New PIN must be exactly 4 digits.")
    conn.execute(
        "UPDATE users SET pin_hash=? WHERE account_number=?",
        (hash_pin(req.new_pin), req.account_number)
    )
    conn.commit()
    conn.close()
    return {"message": "PIN changed successfully."}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
