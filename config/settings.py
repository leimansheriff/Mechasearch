from pathlib import Path

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Data paths
INDEX_DIR = BASE_DIR / "data" / "whoosh_index"
DB_PATH = BASE_DIR / "data" / "seeds_check.db"
