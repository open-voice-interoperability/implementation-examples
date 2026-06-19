#!/usr/bin/env python3

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.workforce_strategist import WorkforceAgent, main


if __name__ == "__main__":
    main()
