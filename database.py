import os

from pony.orm import Database

db = Database()
db_path = os.environ.get("DB_PATH", "db.sqlite")
db.bind(provider="sqlite", filename=db_path, create_db=True)
