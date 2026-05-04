"""
fraud_client.py
===============
Connects Guard Pay to the fraud detection API.
"""

import httpx
import hashlib
import os
from datetime import datetime, timedelta

FRAUD_API_URL = os.getenv("FRAUD_API_URL", "http://localhost:8000")

def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]

def score_transaction(
    transaction_ref: str,
    sender_account: str,
    beneficiary_account: str,
    amount: float,
    channel: str,
    sender_bank: str,
    state: str,
    sim_age_days: int,
    velocity_1h: int,
    velocity_6h: int,
    velocity_24h: int,
    cumulative_24h: float,
    is_new_beneficiary: bool,
) -> dict:
    """
    Call the fraud detection API and return the risk score response.
    Returns a safe default (LOW risk) if the API is unreachable.
    """
    payload = {
        "transaction_id"            : transaction_ref,
        "sender_id"                 : hash_id(sender_account),
        "beneficiary_id"            : hash_id(beneficiary_account),
        "amount_ngn"                : amount,
        "channel"                   : channel,
        "sender_bank"               : sender_bank,
        "beneficiary_bank"          : "GuardPay",
        "state"                     : state,
        "timestamp"                 : datetime.utcnow().isoformat(),
        "sim_age_days"              : sim_age_days,
        "device_fingerprint_changed": sim_age_days <= 2,
        "geo_displacement_flag"     : False,
        "nin_bvn_mismatch"          : False,
        "velocity_1h"               : velocity_1h,
        "velocity_6h"               : velocity_6h,
        "velocity_24h"              : velocity_24h,
        "cumulative_send_24h_ngn"   : cumulative_24h,
        "is_new_beneficiary"        : is_new_beneficiary,
        "agent_id"                  : None,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{FRAUD_API_URL}/v1/score",
                json=payload
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        print(f"Fraud API unreachable: {e}")

    # Safe default if API is down
    return {
        "risk_score"        : 0.1,
        "risk_band"         : "LOW",
        "recommended_action": "ALLOW",
        "top_signals"       : [],
        "shap_explanation"  : {},
        "ndpa_note"         : "Fraud API unavailable — defaulting to LOW risk.",
    }
