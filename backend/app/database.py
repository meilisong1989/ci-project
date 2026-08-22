import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Compose 或本地环境注入 DB_URL；密码不要提交到代码库。
DB_URL = os.getenv("DB_URL", "postgresql+psycopg://postgres@localhost:5432/ci-project")
engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
class Base(DeclarativeBase): pass
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
