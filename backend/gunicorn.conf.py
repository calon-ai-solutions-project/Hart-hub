import os

# "[::]" listens on IPv4 and IPv6: Railway's private network (the web service's proxy) may use either
bind = f"[::]:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = 4
timeout = 120  # photo uploads from the runner
accesslog = "-"
