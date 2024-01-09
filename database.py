from pony.orm import Database

db = Database()
db.bind(provider="sqlite", filename="db.sqlite", create_db=True)
