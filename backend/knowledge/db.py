"""Runtime connection only; import never migrates or writes knowledge data."""
import os
def dsn():
    value=os.environ.get('KNOWLEDGE_DATABASE_URL') or os.environ.get('CHAT_DATABASE_URL')
    if not value:
        raise RuntimeError('Knowledge database is not configured')
    return value
