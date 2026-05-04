# Guard Pay — Demo Fintech Platform

A Nigerian mobile money demo app backed by the AI/ML Fraud Detection API.
Built for research testing of the fraud detection framework.

## Features
- User registration (up to 20 users)
- Send money between users — every transfer scored by the fraud API
- Transaction history with risk scores
- Admin dashboard with full transaction feed
- Compliance queue — HIGH/CRITICAL transactions held for human review (NDPA §37(1))

## Local Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set your fraud API URL (if running locally, default is http://localhost:8000):
```bash
export FRAUD_API_URL=http://localhost:8000
```

3. Run the app:
```bash
uvicorn main:app --reload --port 8080
```

4. Open http://localhost:8080 in your browser.

## Default Admin Account
- Phone : 08000000000
- PIN   : 0000

## User Registration
Share the URL with your test users. Each user:
- Registers with name, phone, state, and a 4-digit PIN
- Receives ₦50,000 starting balance
- Can send money to other registered users

## Deploying to Render

1. Push the guardpay/ folder to a GitHub repository
2. Go to render.com → New Web Service → Connect your GitHub repo
3. Set environment variable: FRAUD_API_URL = your fraud API URL on Render
4. Deploy

## Folder Structure
```
guardpay/
├── main.py          ← FastAPI backend
├── database.py      ← SQLite database
├── fraud_client.py  ← Fraud API connector
├── requirements.txt
├── render.yaml      ← Render deployment config
└── static/
    └── app.html     ← Full frontend
```
