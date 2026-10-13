"""Project paths, resolved relative to this package (cwd-independent)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # caption-agent/
DATA_DIR = ROOT / "data"
WORK_DIR = DATA_DIR / "work"
REMOTION_DIR = ROOT / "remotion"
PUBLIC_DIR = REMOTION_DIR / "public"
DB_PATH = DATA_DIR / "checkpoints.sqlite"
