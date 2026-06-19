#!/usr/bin/env python3

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.market_validator import MarketAgent, main


if __name__ == "__main__":
    main()
