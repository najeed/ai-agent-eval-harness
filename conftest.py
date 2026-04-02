import sys
import os

# Authoritative Industrial Path Injection
# Ensures that both industries/ and dataproc_engine/ are resolvable by the evaluation runner.
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
