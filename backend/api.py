import os
from datetime import datetime, timedelta, timezone

import psycopg
from jose import JWTError, jwt
from litestar import Litestar, Request, delete, get, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from passlib.context import CryptContext
from psycopg.rows import dict_row
from pydantic import BaseModel

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")
SECRET = os.environ.get("JWT_SECRET", "spectrum-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "calibrator": {"role": "writer", "password_hash": pwd.hash("calib123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id serial PRIMARY KEY,
    lamp text NOT NULL,
    nominal_nm double precision NOT NULL,
    measured_nm double precision NOT NULL,
    status text NOT NULL,
    verdict text NOT NULL DEFAULT '',
    reason text NOT NULL DEFAULT '',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS prefixes (
    id serial PRIMARY KEY,
    prefix text NOT NULL UNIQUE,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS prefix_events (
    id serial PRIMARY KEY,
    action text NOT NULL,
    prefix text NOT NULL,
    actor text NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS rejections (
    id serial PRIMARY KEY,
    lamp text NOT NULL,
    reason text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL
);
"""


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class JobIn(BaseModel):
    lamp: str
    nominal_nm: float
    measured_nm: float


class PrefixIn(BaseModel):
    prefix: str


def user_from_request(request: Request) -> dict:
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = jwt.decode(auth[7:], SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


@get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "spectrum-wavelength-desk"}


@post("/api/login")
async def login(data: LoginIn) -> dict:
    u = USERS.get(data.username)
    if not u or not pwd.verify(data.password, u["password_hash"]):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    token = jwt.encode(
        {
            "sub": data.username,
            "role": u["role"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"access_token": token, "role": u["role"], "username": data.username}


@get("/api/jobs")
async def list_jobs(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, lamp, nominal_nm, measured_nm, status, verdict, reason, created_by FROM jobs ORDER BY id DESC"
        ).fetchall()
        return list(rows)


@get("/api/jobs/{job_id:int}")
async def get_job(request: Request, job_id: int) -> dict:
    user_from_request(request)
    with connect() as conn:
        row = conn.execute(
            "SELECT id, lamp, nominal_nm, measured_nm, status, verdict, reason, created_by FROM jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        return dict(row)


@post("/api/jobs")
async def create_job(request: Request, data: JobIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可提交")
    lamp = data.lamp.strip()
    now = datetime.now(timezone.utc)
    with connect() as conn:
        prefixes = [r["prefix"] for r in conn.execute("SELECT prefix FROM prefixes ORDER BY id").fetchall()]
        if not any(lamp.startswith(p) for p in prefixes):
            reason = "称呼须以合法前缀开头（当前簿：" + ("、".join(prefixes) if prefixes else "空") + "）"
            conn.execute(
                "INSERT INTO rejections(lamp, reason, created_by, created_at) VALUES (%s,%s,%s,%s)",
                (lamp, reason, user["username"], now),
            )
            conn.commit()
            raise HTTPException(status_code=400, detail=reason)
        row = conn.execute(
            """
            INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
            VALUES (%s,%s,%s,'pending','','',%s,%s) RETURNING id
            """,
            (lamp, data.nominal_nm, data.measured_nm, user["username"], now),
        ).fetchone()
        conn.commit()
        return {"id": row["id"], "status": "pending"}


@get("/api/prefixes")
async def list_prefixes(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, prefix, created_by, created_at FROM prefixes ORDER BY id"
        ).fetchall()
        return list(rows)


@post("/api/prefixes")
async def add_prefix(request: Request, data: PrefixIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可维护前缀簿")
    prefix = data.prefix.strip()
    if not prefix:
        raise HTTPException(status_code=400, detail="前缀不能为空")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM prefixes WHERE prefix = %s", (prefix,)).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="前缀已存在")
        row = conn.execute(
            "INSERT INTO prefixes(prefix, created_by, created_at) VALUES (%s,%s,%s) RETURNING id",
            (prefix, user["username"], now),
        ).fetchone()
        conn.execute(
            "INSERT INTO prefix_events(action, prefix, actor, created_at) VALUES ('add',%s,%s,%s)",
            (prefix, user["username"], now),
        )
        conn.commit()
        return {"id": row["id"], "prefix": prefix}


@delete("/api/prefixes/{prefix_id:int}", status_code=200)
async def remove_prefix(request: Request, prefix_id: int) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可维护前缀簿")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        row = conn.execute("SELECT id, prefix FROM prefixes WHERE id = %s", (prefix_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="前缀不存在")
        conn.execute("DELETE FROM prefixes WHERE id = %s", (prefix_id,))
        conn.execute(
            "INSERT INTO prefix_events(action, prefix, actor, created_at) VALUES ('remove',%s,%s,%s)",
            (row["prefix"], user["username"], now),
        )
        conn.commit()
        return {"removed": row["prefix"]}


@get("/api/prefix-events")
async def list_prefix_events(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, action, prefix, actor, created_at FROM prefix_events ORDER BY id DESC"
        ).fetchall()
        return list(rows)


@get("/api/rejections")
async def list_rejections(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, lamp, reason, created_by, created_at FROM rejections ORDER BY id DESC"
        ).fetchall()
        return list(rows)


def on_startup() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)
        now = datetime.now(timezone.utc)
        n = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        if n == 0:
            conn.execute(
                """
                INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
                VALUES
                ('氦灯-587', 587.56, 587.50, 'done', '合格', '偏差 0.0600 nm 在允差内', 'seed', %s),
                ('汞灯-546', 546.07, 546.30, 'done', '超差', '偏差 0.2300 nm 超过允差 0.08', 'seed', %s)
                """,
                (now, now),
            )
        p = conn.execute("SELECT COUNT(*) AS n FROM prefixes").fetchone()["n"]
        if p == 0:
            conn.execute(
                "INSERT INTO prefixes(prefix, created_by, created_at) VALUES ('氦', 'seed', %s)",
                (now,),
            )
            conn.execute(
                "INSERT INTO prefix_events(action, prefix, actor, created_at) VALUES ('add', '氦', 'seed', %s)",
                (now,),
            )
        conn.commit()


app = Litestar(
    route_handlers=[
        health,
        login,
        list_jobs,
        get_job,
        create_job,
        list_prefixes,
        add_prefix,
        remove_prefix,
        list_prefix_events,
        list_rejections,
    ],
    on_startup=[on_startup],
)
