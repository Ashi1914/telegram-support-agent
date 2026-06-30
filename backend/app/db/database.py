import ssl

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

_url = settings.DATABASE_URL
_is_supabase = "supabase.co" in _url or "supabase.com" in _url

# Supabase requires TLS; local PostgreSQL does not
_connect_args = {"ssl": ssl.create_default_context()} if _is_supabase else {}

# Supabase free tier: 60 direct connections max — keep the pool small
_pool_size = 5 if _is_supabase else 10
_max_overflow = 10 if _is_supabase else 20

engine = create_async_engine(
    _url,
    echo=False,
    pool_pre_ping=True,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    connect_args=_connect_args,
)

AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
