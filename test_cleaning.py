from flask import Flask, Blueprint, request, render_template_string, session, redirect, url_for, send_file
import pandas as pd
import hashlib
import pycountry
from phonenumbers.phonenumberutil import country_code_for_region
import re
import os
import tempfile
from unidecode import unidecode
import requests
import hmac
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.customaudience import CustomAudience
from facebook_business.adobjects.adaccount import AdAccount

app = Flask(__name__)
app.secret_key = 'your-super-secret-key'

# Use server-side session storage to handle large session data
from flask_session import Session
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Facebook App details
APP_ID = "706446295357865"
APP_SECRET = "93ca4a4e40e552ed571a7c81f10e66bf"
REDIRECT_URI = "https://127.0.0.1:8090/auth/callback"  # must be exactly same in your FB app settings
SCOPES = "email,public_profile,business_management,ads_management"

######### Cleaning Blueprint #########

cleaning_bp = Blueprint('cleaning', __name__, url_prefix='/cleaning')

BASE_HTML = """
<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<title>{{ title or "Meta Audience Hasher" }}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<style>
{% raw %}
  body {
    background-color: #f5f6f7;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  }
  .container {
    max-width: 900px;
    margin-top: 40px;
    background: white;
    padding: 30px;
    border-radius: 12px;
    box-shadow: 0 0 12px rgba(0,0,0,0.08);
  }
  h1, h3 {
    color: #1c1e21;
  }
  table {
    font-size: 0.85rem;
  }
{% endraw %}
</style>
</head>
<body>
<div class="container">
{{ content }}
</div>
</body>
</html>
"""

UPLOAD_HTML = BASE_HTML.replace("{{ content }}", """
<h1 class="mb-4">Upload Customer CSV</h1>
<form method="post" enctype="multipart/form-data">
  <div class="mb-3">
    <input type="file" name="file" class="form-control" required>
  </div>
  <button type="submit" class="btn btn-primary">Upload</button>
</form>
""")

COLUMN_SELECT_HTML = BASE_HTML.replace("{{ content }}", """
<h1>Select Columns</h1>
<p class="text-muted">Choose the correct columns for standardization & hashing.</p>
<p><a class="btn btn-outline-secondary btn-sm" data-bs-toggle="collapse" href="#csvPreview" role="button" aria-expanded="false" aria-controls="csvPreview">Toggle CSV Preview</a></p>
<div class="collapse" id="csvPreview">
  <div class="card card-body p-2 mb-4">
    <div class="table-responsive">
      <table class="table table-sm table-bordered align-middle mb-0" style="font-size: 0.85rem;">
        <thead class="table-light">
          <tr>{% for col in columns %}<th>{{ col }}</th>{% endfor %}</tr>
        </thead>
        <tbody>
          {% for row in preview %}
          <tr>{% for col in columns %}<td>{{ row[col] }}</td>{% endfor %}</tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
<form method="post" action="{{ url_for('cleaning.process') }}">
  <div class="mb-3">
    <label class="form-label">First Name Column</label>
    <select name="fn_col" class="form-select" required>
      {% for col in columns %}<option value="{{ col }}">{{ col }}</option>{% endfor %}
    </select>
  </div>
  <div class="mb-3">
    <label class="form-label">Last Name Column</label>
    <select name="ln_col" class="form-select" required>
      {% for col in columns %}<option value="{{ col }}">{{ col }}</option>{% endfor %}
    </select>
  </div>
  <div class="mb-3">
    <label class="form-label">Phone Number Column</label>
    <select name="phone_col" class="form-select" required>
      {% for col in columns %}<option value="{{ col }}">{{ col }}</option>{% endfor %}
    </select>
  </div>
  <div class="mb-3">
    <label class="form-label">Country Column</label>
    <select name="country_col" class="form-select" required>
      {% for col in columns %}<option value="{{ col }}">{{ col }}</option>{% endfor %}
    </select>
  </div>
  <button type="submit" class="btn btn-primary">Clean & Hash Data</button>
</form>
""")

def get_country_iso(country_name):
    try:
        country = pycountry.countries.get(name=country_name)
        if not country:
            country = pycountry.countries.search_fuzzy(country_name)[0]
        return country.alpha_2
    except:
        return ""

def get_country_dialing_code(iso_code):
    try:
        return f"+{country_code_for_region(iso_code.upper())}"
    except:
        return ""

def hash_value(value):
    if not value or pd.isna(value):
        return ""
    return hashlib.sha256(str(value).strip().lower().encode()).hexdigest()

def normalize_name(name):
    if isinstance(name, str):
        name = unidecode(name.lower())
        name = re.sub(r'[^\w\s]', '', name)
        name = name.replace(" ", "")
        return name
    return ""

def extract_names(name):
    if isinstance(name, str):
        parts = name.strip().split()
        fn = parts[0] if parts else ''
        ln = parts[-1] if len(parts) > 1 else parts[0] if parts else ''
        return pd.Series([fn, ln])
    return pd.Series(['', ''])

@cleaning_bp.route('/', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            return "No file uploaded."

        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, file.filename)
        base, ext = os.path.splitext(file.filename)
        counter = 1
        while os.path.exists(temp_path):
            temp_path = os.path.join(temp_dir, f"{base}_{counter}{ext}")
            counter += 1

        file.save(temp_path)
        session['temp_csv_path'] = temp_path

        try:
            df = pd.read_csv(temp_path)
        except Exception as e:
            os.remove(temp_path)
            session.pop('temp_csv_path', None)
            return f"Error reading CSV: {e}"

        preview = df.head(5).to_dict(orient='records')
        columns = df.columns.tolist()
        return render_template_string(COLUMN_SELECT_HTML, columns=columns, preview=preview)
    return UPLOAD_HTML

@cleaning_bp.route('/process', methods=['POST'])
def process():
    temp_path = session.get('temp_csv_path')
    if not temp_path or not os.path.exists(temp_path):
        return redirect(url_for('cleaning.upload'))

    df = pd.read_csv(temp_path)

    phone_col = request.form['phone_col']
    country_col = request.form['country_col']
    fn_col = request.form['fn_col']
    ln_col = request.form['ln_col']

    for col in [phone_col, country_col, fn_col, ln_col]:
        if col not in df.columns:
            return f"Column '{col}' not found."

    df = df.rename(columns={phone_col: 'phone', country_col: 'country'})

    if fn_col == ln_col:
        df[['fn', 'ln']] = df[fn_col].apply(extract_names)
    else:
        df['fn'] = df[fn_col]
        df['ln'] = df[ln_col]

    df['fn'] = df['fn'].apply(normalize_name)
    df['ln'] = df['ln'].apply(normalize_name)

    df['phone'] = df['phone'].astype(str).str.replace(r"\D", "", regex=True).str[-10:]
    df['country_iso_code'] = df['country'].apply(get_country_iso)
    df['country_code'] = df['country_iso_code'].apply(get_country_dialing_code)
    df['phone'] = df['country_code'] + df['phone']

    data = df[['phone', 'fn', 'ln', 'country_iso_code']].copy()
    data.drop_duplicates(subset=['phone'], keep='last', inplace=True)

    hashed_rows = [
        {
            "FN": hash_value(row['fn']),
            "LN": hash_value(row['ln']),
            "PHONE": hash_value(row['phone'])
        }
        for _, row in data.iterrows()
    ]
    hashed_df = pd.DataFrame(hashed_rows)

    try:
        os.remove(temp_path)
    except:
        pass
    session.pop('temp_csv_path', None)

    output_path = os.path.join(tempfile.gettempdir(), f"hashed_{os.getpid()}.csv")
    hashed_df.to_csv(output_path, index=False)
    session['hashed_csv_path'] = output_path

    preview = data.head(10).to_dict(orient="records")
    columns = data.columns.tolist()

    PREVIEW_HTML = BASE_HTML.replace("{{ content }}", """
    <h1>Cleaned & Hashed Data</h1>
    <p class="text-muted">Here's a preview of the first 10 rows of your standardized audience data.</p>

    <div class="table-responsive">
    <table class="table table-sm table-bordered align-middle mb-3">
        <thead class="table-light">
        <tr>{% for col in columns %}<th>{{ col }}</th>{% endfor %}</tr>
        </thead>
        <tbody>
        {% for row in preview %}
        <tr>{% for col in columns %}<td>{{ row[col] }}</td>{% endfor %}</tr>
        {% endfor %}
        </tbody>
    </table>
    </div>

    <form method="post" action="{{ url_for('cleaning.download') }}">
    <button type="submit" class="btn btn-success">Download Hashed CSV</button>
    </form>

    <hr>
    <a href="{{ url_for('audience.home') }}" class="btn btn-primary mt-4">Go to Audience Login</a>
    """)

    return render_template_string(PREVIEW_HTML, columns=columns, preview=preview)

@cleaning_bp.route('/download', methods=['POST'])
def download():
    path = session.get('hashed_csv_path')
    if not path or not os.path.exists(path):
        return redirect(url_for('cleaning.upload'))
    return send_file(
        path,
        mimetype='text/csv',
        as_attachment=True,
        download_name='hashed_customers.csv'
    )

######### Audience Blueprint #########

audience_bp = Blueprint('audience', __name__, url_prefix='/audience')

@audience_bp.route('/')
def home():
    if 'access_token' not in session:
        fb_oauth_url = (
            f"https://www.facebook.com/v23.0/dialog/oauth?"
            f"client_id={APP_ID}&redirect_uri={REDIRECT_URI}&state=123abc&scope={SCOPES}"
        )
        return redirect(fb_oauth_url)

    # Place your audience dashboard UI here
    return render_template_string("""
    <h3>Welcome to Audience Management</h3>
    <p><a href="{{ url_for('uploading.upload_data') }}">Go to Upload Hashed Data</a></p>
    """)

@audience_bp.route('/login/facebook')
def facebook_login():
    fb_oauth_url = (
        f"https://www.facebook.com/v23.0/dialog/oauth?"
        f"client_id={APP_ID}&redirect_uri={REDIRECT_URI}&state=123abc&scope={SCOPES}"
    )
    return redirect(fb_oauth_url)

######### Uploading Blueprint #########

uploading_bp = Blueprint('uploading', __name__, url_prefix='/uploading')

@uploading_bp.route("/", methods=["GET", "POST"])
def upload_data():
    if 'access_token' not in session:
        return redirect(url_for('audience.home'))

    created_audience_ids = session.get("created_audience_ids", [])

    if request.method == "POST":
        audience_id = request.form.get('audience_id')
        if not audience_id:
            audience_id_list = request.form.getlist('audience_id')
            if isinstance(audience_id_list, list):
                audience_id = next((val for val in audience_id_list if val.strip()), None)
        if not audience_id:
            return "Audience ID is required.", 400

        file = request.files.get("data_file")
        if not file:
            return "Data file is required.", 400

        try:
            df = pd.read_csv(file)
            expected_columns = ['FN', 'LN', 'PHONE']
            df.columns = [col.upper() for col in df.columns]

            if not all(col in df.columns for col in expected_columns):
                return f"CSV must include columns: {', '.join(expected_columns)}", 400

            df_clean = df.dropna(subset=expected_columns)
            if df_clean.empty:
                return "Uploaded CSV contains no valid data after removing empty rows.", 400

            data_to_upload = df_clean[expected_columns].astype(str).values.tolist()

            FacebookAdsApi.init(access_token=session["access_token"], app_id=APP_ID, app_secret=APP_SECRET)

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

            return render_template_string("""
            <div class='container'>
                <div class='card p-4'>
                    <h4>Upload Successful</h4>
                    <p>Data uploaded to audience ID: <b>{{ audience_id }}</b></p>
                    <pre>{{ response }}</pre>
                    <a href='/uploading/' class='btn btn-primary mt-3'>Upload More</a>
                    <a href='/' class='btn btn-secondary mt-3'>Home</a>
                </div>
            </div>
        """, audience_id=audience_id, response=response)

        except Exception as e:
         return render_template_string("""
            <div class='container'>
                <div class='card p-4'>
                    <h4 class='text-danger'>Upload Failed</h4>
                    <p>{{ e }}</p>
                    <a href='/uploading/' class='btn btn-primary mt-3'>Try Again</a>
                    <a href='/' class='btn btn-secondary mt-3'>Home</a>
                </div>
            </div>
        """, e=str(e))

    options_html = ""
    for aud_id in created_audience_ids:
        options_html += f"<option value='{aud_id}'>{aud_id}</option>"

    return render_template_string(BASE_HTML.replace("{{ content }}", f"""
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
    """))

######### OAuth callback route for Facebook  #########

@app.route('/auth/callback')
def facebook_callback():
    code = request.args.get('code')
    if not code:
        return "Authorization failed", 400

    token_url = f"https://graph.facebook.com/v19.0/oauth/access_token?client_id={APP_ID}&redirect_uri={REDIRECT_URI}&client_secret={APP_SECRET}&code={code}"
    res = requests.get(token_url)
    data = res.json()
    access_token = data.get('access_token')
    if not access_token:
        return f"Error getting access token: {data}", 400

    session['access_token'] = access_token
    return redirect(url_for('audience.home'))

######### Root Redirect #########

@app.route('/')
def index():
    return redirect(url_for('cleaning.upload'))

######### Run the app #########

if __name__ == '__main__':
    app.run(debug=True, port=8090, ssl_context='adhoc')
