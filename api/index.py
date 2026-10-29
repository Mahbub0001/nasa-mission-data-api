import os
import sys

# Ensure repository root is on sys.path for Vercel Serverless Function runtime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
