from flask import Flask, redirect, request, render_template_string, url_for, session
import requests
import hashlib
import hmac
import pandas as pd
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.customaudience import CustomAudience
from facebook_business.adobjects.adaccount import AdAccount
from flask_session import Session

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Required for session management
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

APP_ID = "706446295357865" #"1276778010724389"
APP_SECRET = "93ca4a4e40e552ed571a7c81f10e66bf" #"7b1f7856ff5f15619772b4c7717a867c"
REDIRECT_URI = "https://127.0.0.1:8090/auth/callback"
SCOPES = "email,public_profile,business_management,ads_management"

# Helper functions

def generate_appsecret_proof(access_token, app_secret):
    return hmac.new(app_secret.encode("utf-8"), access_token.encode("utf-8"), hashlib.sha256).hexdigest()

def fetch_all_ad_accounts(access_token, app_secret):
    appsecret_proof = generate_appsecret_proof(access_token, app_secret)
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "access_token": access_token,
        "appsecret_proof": appsecret_proof,
        "fields": "name",
        "limit": 100
    }
    businesses_url = "https://graph.facebook.com/v19.0/me/businesses"
    biz_response = requests.get(businesses_url, params=params, headers=headers).json()
    business_list = biz_response.get("data", [])

    all_accounts = []
    for biz in business_list:
        business_id = biz["id"]
        for endpoint in ["owned_ad_accounts", "client_ad_accounts"]:
            next_url = f"https://graph.facebook.com/v19.0/{business_id}/{endpoint}"
            while next_url:
                account_res = requests.get(next_url, params={
                    "access_token": access_token,
                    "appsecret_proof": appsecret_proof,
                    "fields": "name,account_id",
                    "limit": 100
                }, headers=headers).json()
                all_accounts.extend(account_res.get("data", []))
                next_url = account_res.get("paging", {}).get("next")
    return all_accounts

HTML_HEAD = """
<!DOCTYPE html>
<html lang='en'>
<head>
    <meta charset='UTF-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1.0'>
    <title>Meta Audience Manager</title>
    <link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css' rel='stylesheet'>
    <style>
        body {
            background-color: #f0f2f5;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        }
        .container {
            margin-top: 60px;
            max-width: 720px;
        }
        .card {
            border: none;
            border-radius: 1rem;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        }
        .scroll-box {
            max-height: 300px;
            overflow-y: auto;
            border: 1px solid #ddd;
            padding: 10px;
            border-radius: 0.5rem;
            background-color: #fff;
        }
        .btn-primary {
            background-color: #1877f2;
            border: none;
        }
        .btn-primary:hover {
            background-color: #165fce;
        }
        label {
            font-weight: 500;
        }
    </style>
</head>
<body>
"""

# Routes

@app.route("/")
def home():
    return HTML_HEAD + """
    <div class='container'>
        <div class='card p-4 text-center'>
            <h3>Welcome to Meta Audience Manager</h3>
            <p class='text-muted'>Login to manage and create your audiences.</p>
            <a href='/login/facebook' class='btn btn-primary'>Login with Facebook</a>
        </div>
    </div>
    </body></html>
    """

@app.route("/login/facebook")
def facebook_login():
    fb_oauth_url = (
        f"https://www.facebook.com/v23.0/dialog/oauth?"
        f"client_id={APP_ID}&redirect_uri={REDIRECT_URI}&state=123abc&scope={SCOPES}"
    )
    return redirect(fb_oauth_url)

@app.route("/auth/callback")
def facebook_callback():
    code = request.args.get("code")
    if not code:
        return "Authorization failed", 400

    token_url = (
        f"https://graph.facebook.com/v19.0/oauth/access_token?"
        f"client_id={APP_ID}&redirect_uri={REDIRECT_URI}&client_secret={APP_SECRET}&code={code}"
    )
    res = requests.get(token_url)
    data = res.json()
    access_token = data.get("access_token")
    if not access_token:
        return f"Error getting access token: {data}", 400

    session['access_token'] = access_token
    accounts_data = fetch_all_ad_accounts(access_token, APP_SECRET)
    ad_account_map = {}
    for acct in accounts_data:
        account_id = f"act_{acct['account_id']}"
        name = acct.get("name")
        display_name = f"{name} ({account_id})" if name else f"{account_id} (No Brand Name)"
        ad_account_map[display_name] = account_id
    session['ad_account_map'] = ad_account_map

    form_html = HTML_HEAD + """
    <div class='container'>
        <div class='card p-4'>
            <h4 class='mb-3'>Create Custom Audience</h4>
            <form method='post' action='/create_audience'>
                <div class='mb-3'>
                    <label>Select Brands:</label>
                    <input type='text' class='form-control mb-2' id='searchBox' placeholder='Search brands...'>
                    <div class='scroll-box' id='brandsContainer'>
                        {% for name in account_names %}
                            <div class='form-check brand-entry'>
                                <input class='form-check-input' type='checkbox' name='brand_name' value='{{ name }}'>
                                <label class='form-check-label'>{{ name }}</label>
                            </div>
                        {% endfor %}
                    </div>
                </div>
                <script>
                document.getElementById('searchBox').addEventListener('input', function() {
                    let filter = this.value.toLowerCase();
                    let entries = document.querySelectorAll('.brand-entry');
                    entries.forEach(function(entry) {
                        let label = entry.querySelector('label').textContent.toLowerCase();
                        entry.style.display = label.includes(filter) ? '' : 'none';
                    });
                });
                </script>

                <div class='mb-3'>
                    <label>Audience Title:</label>
                    <input type='text' class='form-control' name='audience_name' required>
                </div>
                <button type='submit' class='btn btn-primary w-100'>Create Custom Audience</button>
            </form>
            <hr>
            <a href='/upload_data' class='btn btn-secondary w-100 mt-3'>Go to Upload Hashed Data</a>
        </div>
    </div>
    </body></html>
    """

    return render_template_string(form_html, account_names=ad_account_map.keys())

@app.route("/create_audience", methods=["POST"])
def create_audience():
    access_token = session.get("access_token")
    ad_account_map = session.get("ad_account_map", {})
    if not access_token:
        return "Missing access token", 401
    

    brand_names = request.form.getlist("brand_name")
    audience_name = request.form.get("audience_name")
    if not brand_names or not audience_name:
        return "Both brand(s) and audience name are required.", 400

    FacebookAdsApi.init(access_token=access_token, app_id=APP_ID, app_secret=APP_SECRET)

    created_audience_ids = []
    results = []
    for brand in brand_names:
        account_id = ad_account_map.get(brand)
        if not account_id:
            results.append(f"<b>{brand}</b>: ❌ Brand not found")
            continue

        account = AdAccount(account_id)
        try:
            existing = account.get_custom_audiences(fields=["id", "name"])
            matched = next((a for a in existing if a['name'].strip().lower() == audience_name.strip().lower()), None)
            if matched:
                results.append(f"<b>{brand}</b>: ⚠️ Audience already exists (ID: {matched['id']})")
                created_audience_ids.append(matched['id'])
            else:
                new_aud = account.create_custom_audience(fields=[], params={
                    'name': audience_name,
                    'subtype': 'CUSTOM',
                    'description': f'Audience for {brand}',
                    'customer_file_source': 'USER_PROVIDED_ONLY',
                })
                results.append(f"<b>{brand}</b>: ✅ Created new audience (ID: {new_aud['id']})")
                created_audience_ids.append(new_aud['id'])
        except Exception as e:
            results.append(f"<b>{brand}</b>: ❌ Error - {str(e)}")
    
    # Save created audience IDs in session so user can select later
    session['created_audience_ids'] = created_audience_ids

    # Show results and link to upload page with option to upload now
    upload_link = url_for("upload_data")

    return HTML_HEAD + f"""
    <div class='container'>
        <div class='card p-4'>
            <h5>Audience Creation Results</h5>
            <hr>
            {"<br>".join(results)}
            <hr>
            <a href='{upload_link}' class='btn btn-primary w-100 mt-3'>Upload Hashed Data To Audience</a>
        </div>
    </div>
    </body></html>
    """

@app.route("/upload_data", methods=["GET", "POST"])
def upload_data():
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("home"))

    # Retrieve audiences created in this session if any
    created_audience_ids = session.get("created_audience_ids", [])

    if request.method == "POST":
        # Since your form has both a <select name='audience_id'> and <input name='audience_id'>,
        # Flask's request.form.get('audience_id') returns the first one.  
        # To handle both, try to fetch non-empty value from either:
        audience_id = request.form.get('audience_id')
        if not audience_id:
            # Try to get value from form keys explicitly (usually second input)
            audience_id = request.form.getlist('audience_id')
            if isinstance(audience_id, list):
                # Filter out empty strings and pick the first non-empty
                audience_id = next((val for val in audience_id if val.strip()), None)
        if not audience_id:
            return "Audience ID is required.", 400

        file = request.files.get("data_file")
        if not file:
            return "Data file is required.", 400

        try:
            df = pd.read_csv(file)


            expected_columns = ['FN', 'LN', 'PHONE']  # Use uppercase to match Facebook schema

            # Normalize dataframe column names to uppercase for consistent matching
            df.columns = [col.upper() for col in df.columns]

            # Validate that all expected columns exist after adjusting case
            if not all(col in df.columns for col in expected_columns):
                return f"CSV must include columns: {', '.join(expected_columns)}", 400

            # Drop rows with any NaNs in the expected columns
            df_clean = df.dropna(subset=expected_columns)

            if df_clean.empty:
                return "Uploaded CSV contains no valid data after removing empty rows.", 400

            # Prepare data as list of lists after converting to string
            data_to_upload = df_clean[expected_columns].astype(str).values.tolist()

            FacebookAdsApi.init(access_token=access_token, app_id=APP_ID, app_secret=APP_SECRET)

            audience = CustomAudience(audience_id)
            response = audience.create_user(
                fields=[],
                params={
                    'payload': {
                        'schema': expected_columns,
                        'data': data_to_upload,
                    }
                }
            )



            return HTML_HEAD + f"""
            <div class='container'>
                <div class='card p-4'>
                    <h4>Upload Successful!</h4>
                    <p>Data uploaded to audience ID: <b>{audience_id}</b></p>
                    <pre>{response}</pre>
                    <a href='/upload_data' class='btn btn-primary mt-3'>Upload More Data</a>
                    <a href='/' class='btn btn-secondary mt-3'>Home</a>
                </div>
            </div>
            </body></html>
            """

        except Exception as e:
            return HTML_HEAD + f"""
            <div class='container'>
                <div class='card p-4'>
                    <h4 class='text-danger'>Upload Failed</h4>
                    <p>{str(e)}</p>
                    <a href='/upload_data' class='btn btn-primary mt-3'>Try Again</a>
                    <a href='/' class='btn btn-secondary mt-3'>Home</a>
                </div>
            </div>
            </body></html>
            """

    # GET method: show upload form
    options_html = ""
    for aud_id in created_audience_ids:
        options_html += f"<option value='{aud_id}'>{aud_id}</option>"

    return HTML_HEAD + f"""
    <div class='container'>
        <div class='card p-4'>
            <h4 class='mb-3'>Upload Hashed Data to Audience</h4>
            <form method='post' enctype='multipart/form-data'>
                <div class='mb-3'>
                    <label>Select Audience ID</label>
                    <select name='audience_id' class='form-select mb-2'>
                        <option value=''>Select from created audiences</option>
                        {options_html}
                    </select>
                    <input type='text' class='form-control' name='audience_id' placeholder='Or enter Audience ID manually'>
                </div>
                <div class='mb-3'>
                    <label>Hashed Data CSV File</label>
                    <input type='file' class='form-control' name='data_file' accept='.csv' required>
                </div>
                <button type='submit' class='btn btn-primary w-100'>Upload Data</button>
            </form>
            <hr>
            <a href='/' class='btn btn-secondary w-100 mt-3'>Back to Home</a>
        </div>
    </div>
    </body></html>
    """


if __name__ == "__main__":
    # Run with HTTPS because of Facebook OAuth redirect URI requirements
    app.run(port=8090, ssl_context="adhoc", debug=True)
