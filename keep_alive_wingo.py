#!/usr/bin/env python3
import sys
from pathlib import Path

# Add scripts directory to path and invoke main keep_alive engine
scripts_dir = Path(__file__).parent / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from keep_alive import main

if __name__ == "__main__":
    main()
