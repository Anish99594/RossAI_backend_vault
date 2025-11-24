# app/db_indexes.py

import sys
sys.path.append("/app")  # Allow absolute import inside Docker

from db import get_db  # uses the updated import in db.py

db = get_db()

# Ensure uniqueness for users
db.users.create_index("email", unique=True)
db.users.create_index("user_id", unique=True)

# Ensure a user can only belong to the same project once
db.memberships.create_index(
    [("user_id", 1), ("company_id", 1), ("team_id", 1), ("project_id", 1)],
    unique=True
)

# Optimize document queries
db.documents.create_index(
    [("company_id", 1), ("team_id", 1), ("project_id", 1)]
)

print("🚀 Indexes created successfully in MongoDB!")
