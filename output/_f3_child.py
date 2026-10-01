import os, sys
data = sys.argv[1]
os.environ["TOKDASH_DATA_DIR"] = data
sys.path.insert(0, r"C:\Users\Dhruv Jadav\Downloads\Tokdash Testing\tokdash\src")
from tokdash.sources.quota import config as qc
errs = 0
for i in range(30):
    try:
        qc.set_quota_consent({"claude_api": i % 2 == 0})
    except Exception:
        errs += 1
print("child errors:", errs)
