# projectrestore/tests/conftest.py


import sys
import os

# Get the path to projectrestore root (parent of tests)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))
app_root = os.path.abspath(os.path.join(project_root, ".."))
src_path = os.path.join(app_root, "src")

# Insert paths
sys.path.insert(0, project_root)
sys.path.insert(0, src_path) # Allow importing 'common' via 'src.common' ? No, 'src' is a package.
# If src is a package (has __init__.py? No, it doesn't), then we import 'src.common'.
# We need the parent of 'src' to be in sys.path to import 'src'.
# But parent of 'src' is '/app'.
# If we add '/app', we break 'projectrestore' import.
# Solution: Add '/app/src' to sys.path, so we can import 'common' if 'common' is in 'src'.
# But imports are like `from src.common import ...`.
# If we cannot add '/app', we cannot import `src`.
# Unless we use `PYTHONPATH` trickery or rely on `conftest` removing `/app` ONLY if it confuses `projectrestore`.
# But `projectrestore` is confused by `/app` because `/app/projectrestore` exists.
# `src` is in `/app/src`. `/app/src` does not conflict with anything (unless we have `src` elsewhere).
# So we need `/app` in path to import `src`.
# BUT `/app` causes `projectrestore` to be namespace.

# Alternative: Rename `projectrestore` root dir to `projectrestore-pkg`? No.
# Alternative: Create `src` symlink or copy in test env? No.
# Alternative: Use `sys.modules` hacking? No.

# Wait, `src` directory usually IS the root of source code.
# If `project-vault` structure is:
# /app
#   projectclone/
#   projectrestore/
#   src/
#     cli.py
#     common/
#
# `src` is a sibling of `projectrestore`.
# If I want `from src.common import ...`, I need `/app` in sys.path.
# This seems to be a circular dependency or bad structure issue if namespace packages conflict.

# If I add `/app` to end of sys.path?
# `sys.path.append(app_root)`.
# Then `import projectrestore`.
# It checks `project_root` (added at 0). Finds `projectrestore` package.
# It should STOP there.
# Why did it find namespace before?
# Because `.` was at 0 (or before `project_root`).
# So if I ensure `project_root` is BEFORE `app_root` in sys.path, it should work.

# I will add `app_root` to the END of sys.path (or just ensure `project_root` is inserted at 0).
# And remove `app_root` from wherever it was (likely 0 or 1).

# Remove /app from sys.path if it exists to avoid namespace package confusion being FIRST
if app_root in sys.path:
    try:
        sys.path.remove(app_root)
    except ValueError:
        pass

# Also remove "." and "" if present
if "." in sys.path:
    sys.path.remove(".")
if "" in sys.path:
    sys.path.remove("")

# Re-add app_root at the end, so 'src' can be imported, but 'projectrestore' is found in project_root first
sys.path.append(app_root)

# Force check/reload of projectrestore to ensure we have the real package, not a namespace
import projectrestore
if not hasattr(projectrestore, 'modules'):
    print(f"DEBUG: projectrestore loaded as namespace from {projectrestore.__path__}. Reloading...")
    # Remove from sys.modules so we can reload from the correct path (which is now at 0)
    del sys.modules['projectrestore']
    import projectrestore
    if not hasattr(projectrestore, 'modules'):
         print("DEBUG: CRITICAL - projectrestore still lacks 'modules' after reload!")
    else:
         print(f"DEBUG: projectrestore successfully reloaded from {projectrestore.__file__}")

