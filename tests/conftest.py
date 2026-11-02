import os

# Run Qt tests without showing windows.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
