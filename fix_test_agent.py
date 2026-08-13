import re
import os

for filename in ["backend/tests/test_checkpointer.py", "backend/tests/test_session_store.py"]:
    if not os.path.exists(filename):
        continue
    with open(filename, "r") as f:
        content = f.read()
    
    # Remove agent=... from TripSession calls
    content = re.sub(r'agent=[^,]+,\s*', '', content)
    
    with open(filename, "w") as f:
        f.write(content)
