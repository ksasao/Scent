#!/usr/bin/env python3
"""
Scent Bridge - Viewer と AI エージェント間のゲートウェイ

起動方法:
    python main.py

または uvicorn 直接:
    uvicorn server:app --host 127.0.0.1 --port 8001 --reload
"""

import uvicorn
import logging
from server import app
from config import BRIDGE_HOST, BRIDGE_PORT, LOG_LEVEL

logger = logging.getLogger(__name__)

def main():
    """メインエントリーポイント"""
    logger.info(f"Starting Scent Bridge on {BRIDGE_HOST}:{BRIDGE_PORT}")

    uvicorn.run(
        app,
        host=BRIDGE_HOST,
        port=BRIDGE_PORT,
        log_level=LOG_LEVEL.lower(),
    )

if __name__ == "__main__":
    main()
