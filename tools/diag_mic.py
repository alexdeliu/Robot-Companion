import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from diag_mic import ruleaza_diagnostic

if __name__ == "__main__":
    ruleaza_diagnostic()