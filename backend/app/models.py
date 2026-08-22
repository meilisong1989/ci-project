from datetime import datetime
from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
class User(Base):
    __tablename__ = "user"
    __table_args__ = {"quote": True}  # user 是 PostgreSQL 保留关键字，强制加双引号。
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password: Mapped[str] = mapped_column(String(100))
    nickname: Mapped[str] = mapped_column(String(64))
    create_time: Mapped[datetime] = mapped_column(DateTime)
class TestCase(Base):
    __tablename__ = "test_case"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255)); module: Mapped[str] = mapped_column(String(100))
    priority: Mapped[str] = mapped_column(String(10)); status: Mapped[str] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text); expected_result: Mapped[str | None] = mapped_column(Text)
    creator: Mapped[str] = mapped_column(String(64)); create_time: Mapped[datetime] = mapped_column(DateTime); update_time: Mapped[datetime] = mapped_column(DateTime)
