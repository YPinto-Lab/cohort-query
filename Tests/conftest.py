import sys
from pathlib import Path

# Add project root to path so we can import Agents, Engines, etc.
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
