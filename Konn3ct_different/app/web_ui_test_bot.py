import sys
import asyncio

# Setup path so testweb can be imported cleanly
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from testweb.bot import run_bot

if __name__ == "__main__":
    asyncio.run(run_bot())
