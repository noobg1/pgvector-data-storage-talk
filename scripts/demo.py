#!/usr/bin/env python3
import sys
import subprocess

commands = {
    "setup": "embed_demo.py",
    "seed": "seed.py",
    "compare": "compare.py",
    "search": "search.py"
}

if len(sys.argv) < 2 or sys.argv[1] not in commands:
    print("Usage: python demo.py [setup|seed|compare|search]")
    print("\n  setup   - Initialize database and add sample data")
    print("  seed    - Add custom texts to database")
    print("  compare - Compare two texts interactively")
    print("  search  - Search for similar texts in database")
    sys.exit(1)

subprocess.run([sys.executable, commands[sys.argv[1]]])
