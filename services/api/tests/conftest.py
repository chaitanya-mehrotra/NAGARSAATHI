"""Keep the test suite away from any hosted service configured in a developer's .env.

Settings() reads .env, and environment variables win over it. Pinning these here (before any
Settings object is built) means a run can never write test photos to a real Supabase bucket or
bypass the seed guard that refuses non-local databases.
"""

import os

os.environ["STORAGE_BACKEND"] = "local"
os.environ["ALLOW_HOSTED_DEMO_SEED"] = "false"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
