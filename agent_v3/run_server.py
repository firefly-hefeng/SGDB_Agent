#!/usr/bin/env python3
"""
SCeQTL-Agent V2 — Server launcher

Usage:
    python run_server.py [--host 0.0.0.0] [--port 8000] [--reload]
"""

import argparse
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

def main():
    parser = argparse.ArgumentParser(description="SCeQTL-Agent V2 Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed. Run: pip install uvicorn[standard]")
        sys.exit(1)

    print(f"Starting SCeQTL-Agent V2 on http://{args.host}:{args.port}")
    print(f"  API docs: http://localhost:{args.port}/docs")
    print(f"  Health:   http://localhost:{args.port}/api/v1/health")

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
