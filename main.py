"""Zeisss SubGate entry point."""
import asyncio
from subgate.app import main

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
