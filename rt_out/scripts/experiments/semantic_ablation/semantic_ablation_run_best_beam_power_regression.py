#!/usr/bin/env python3
"""Thin alias for the reusable regression CLI; it deliberately sets no defaults."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'training'))
from run_best_beam_power_regression import main
if __name__ == '__main__': main()
