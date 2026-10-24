import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# The app initializes and seeds its database on import. Keep one worker to
# avoid concurrent initialization, and use threads to handle concurrent requests.
workers = 1
worker_class = "gthread"
threads = 4
timeout = 60
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
capture_output = True
# Forwarded headers are handled explicitly by the opt-in ProxyFix in app.py.
forwarded_allow_ips = ""
