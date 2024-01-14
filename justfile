set dotenv-load

run:
    python app.py

req:
    pip-compile requirements.in
