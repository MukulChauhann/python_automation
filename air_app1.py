import os
import uuid
import base64
import hashlib

from flask import Flask, redirect, request, session, url_for
import requests

# ============ DEVELOPMENT SETTINGS (hardcoded secrets here for convenience) ============
CLIENT_ID = "9370efdd-4d74-40dc-a05e-77a660ecb6c7"
CLIENT_SECRET = "98b73bec7a746dc99492a59d95bfab617974f6293359a09c2a94b1c1043c90da"
REDIRECT_URI = "https://localhost:8090/callback"
AUTHORIZATION_URL = "https://airtable.com/oauth2/v1/authorize"
TOKEN_URL = "https://airtable.com/oauth2/v1/token"
SCOPES = "data.records:read schema.bases:read"
# ============ END DEVELOPMENT SETTINGS ==============


def generate_flask_secret_key():
    # Generates a random Flask secret key (url-safe base64 24 bytes)
    return base64.urlsafe_b64encode(os.urandom(24)).rstrip(b"=").decode("utf-8")


app = Flask(__name__)

# You can set your own key here or use generate_flask_secret_key() once and then fix the value:
# For development, it’s fine to hardcode. For production, load from environment securely.
app.secret_key = "change_this_for_dev"  # <-- Change this for production!

# Optional: Uncomment below to auto-generate a secret key at runtime (not persistent across restarts)
# app.secret_key = generate_flask_secret_key()


def generate_code_verifier():
    # Create a high-entropy cryptographic code verifier for PKCE
    return base64.urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode("utf-8")


def generate_code_challenge(verifier):
    # Generate SHA256 hash and encode as base64 urlsafe string for code_challenge
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")


@app.route("/")
def home():
    return '<a href="/login">Connect to Airtable</a>'


@app.route("/login")
def login():
    state = str(uuid.uuid4())
    session["oauth_state"] = state

    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    session["pkce_verifier"] = code_verifier

    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{AUTHORIZATION_URL}?{urlencode(params)}"
    print("Authorize URL:\n", auth_url)

    return redirect(auth_url)


@app.route("/callback")
def callback():
    if "error" in request.args:
        desc = request.args.get("error_description") or request.args.get("error")
        return f"Error during OAuth: {desc}", 400

    received_state = request.args.get("state")
    if received_state != session.get("oauth_state"):
        return "Invalid or missing state parameter", 400

    code = request.args.get("code")
    if not code:
        return "No code provided", 400

    code_verifier = session.get("pkce_verifier")
    if not code_verifier:
        return "Missing PKCE verifier", 400

    token_response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if token_response.status_code != 200:
        return f"Failed to get token: {token_response.text}", 400

    token_data = token_response.json()
    session["access_token"] = token_data.get("access_token")

    return redirect(url_for("profile"))


@app.route("/profile")
def profile():
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("login"))

    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get("https://api.airtable.com/v0/meta/bases", headers=headers)

    if response.status_code != 200:
        return f"API call failed: {response.text}", 400

    import json

    return f"<pre>{json.dumps(response.json(), indent=2)}</pre>"


if __name__ == "__main__":
    # WARNING: ssl_context="adhoc" is for dev only. Use a real TLS cert in production
    app.run(port=8090, ssl_context="adhoc", debug=True)
