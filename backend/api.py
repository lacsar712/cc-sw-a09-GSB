import os
from datetime import datetime, timedelta, timezone

import psycopg
from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
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

CREATE TABLE IF NOT EXISTS lamp_prefixes (
    prefix text PRIMARY KEY,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS prefix_audit (
    id serial PRIMARY KEY,
    action text NOT NULL,
    prefix text NOT NULL,
    changed_by text NOT NULL,
    changed_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_submissions (
    id serial PRIMARY KEY,
    lamp text NOT NULL,
    nominal_nm double precision NOT NULL,
    measured_nm double precision NOT NULL,
    matched_prefix text NOT NULL DEFAULT '',
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


def require_writer(request: Request) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可维护前缀簿")
    return user


def active_prefixes(conn) -> list[str]:
    return [
        r["prefix"]
        for r in conn.execute("SELECT prefix FROM lamp_prefixes ORDER BY prefix").fetchall()
    ]


def match_prefix(lamp: str, prefixes: list[str]) -> str:
    """称呼必须以任一合法前缀「开头」；取最长匹配。"""
    best = ""
    for p in prefixes:
        if lamp.startswith(p) and len(p) > len(best):
            best = p
    return best


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
    if not lamp:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="灯种称呼不能为空")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        prefixes = active_prefixes(conn)
        matched = match_prefix(lamp, prefixes)
        if not matched:
            allowed = "、".join(prefixes) if prefixes else "（前缀簿为空）"
            reason = f"称呼「{lamp}」未以任一合法前缀开头，合法前缀：{allowed}"
            conn.execute(
                """
                INSERT INTO rejected_submissions
                    (lamp, nominal_nm, measured_nm, matched_prefix, reason, created_by, created_at)
                VALUES (%s,%s,%s,'',%s,%s,%s)
                """,
                (lamp, data.nominal_nm, data.measured_nm, reason, user["username"], now),
            )
            conn.commit()
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=reason)
        row = conn.execute(
            """
            INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
            VALUES (%s,%s,%s,'pending','','',%s,%s) RETURNING id
            """,
            (lamp, data.nominal_nm, data.measured_nm, user["username"], now),
        ).fetchone()
        conn.commit()
        return {"id": row["id"], "status": "pending", "matched_prefix": matched}


@get("/api/prefixes")
async def list_prefixes(request: Request) -> dict:
    user_from_request(request)
    with connect() as conn:
        return {"prefixes": active_prefixes(conn)}


@post("/api/prefixes")
async def add_prefix(request: Request, data: PrefixIn) -> dict:
    user = require_writer(request)
    prefix = data.prefix.strip()
    if not prefix:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="前缀不能为空")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM lamp_prefixes WHERE prefix = %s", (prefix,)
        ).fetchone()
        if exists:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=f"前缀「{prefix}」已存在")
        conn.execute(
            "INSERT INTO lamp_prefixes(prefix, created_by, created_at) VALUES (%s,%s,%s)",
            (prefix, user["username"], now),
        )
        conn.execute(
            "INSERT INTO prefix_audit(action, prefix, changed_by, changed_at) VALUES ('add',%s,%s,%s)",
            (prefix, user["username"], now),
        )
        conn.commit()
    return {"prefix": prefix, "action": "add"}


@post("/api/prefixes/delete")
async def delete_prefix(request: Request, data: PrefixIn) -> dict:
    user = require_writer(request)
    prefix = data.prefix.strip()
    now = datetime.now(timezone.utc)
    with connect() as conn:
        # 只删前缀簿条目与记录履历；jobs 中已入队的称呼保持原样不改写
        deleted = conn.execute("DELETE FROM lamp_prefixes WHERE prefix = %s", (prefix,)).rowcount
        if not deleted:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=f"前缀「{prefix}」不存在")
        conn.execute(
            "INSERT INTO prefix_audit(action, prefix, changed_by, changed_at) VALUES ('remove',%s,%s,%s)",
            (prefix, user["username"], now),
        )
        conn.commit()
    return {"prefix": prefix, "action": "remove"}


@get("/api/prefixes/audit")
async def prefix_audit_log(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, action, prefix, changed_by, changed_at
            FROM prefix_audit ORDER BY id DESC LIMIT 200
            """
        ).fetchall()
        return list(rows)


@get("/api/rejected")
async def list_rejected(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, lamp, nominal_nm, measured_nm, matched_prefix, reason, created_by, created_at
            FROM rejected_submissions
            WHERE created_at >= date_trunc('day', now())
            ORDER BY id DESC
            """
        ).fetchall()
        return list(rows)


def on_startup() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)
        n = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        if n == 0:
            now = datetime.now(timezone.utc)
            conn.execute(
                """
                INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
                VALUES
                ('氦灯-587', 587.56, 587.50, 'done', '合格', '偏差 0.0600 nm 在允差内', 'seed', %s),
                ('汞灯-546', 546.07, 546.30, 'done', '超差', '偏差 0.2300 nm 超过允差 0.08', 'seed', %s)
                """,
                (now, now),
            )
        # 前缀簿初始只留「氦」；幂等种子，重复启动不重复写履历
        seeded = conn.execute("SELECT COUNT(*) AS n FROM lamp_prefixes").fetchone()["n"]
        audited = conn.execute("SELECT COUNT(*) AS n FROM prefix_audit").fetchone()["n"]
        if seeded == 0 and audited == 0:
            now = datetime.now(timezone.utc)
            conn.execute(
                "INSERT INTO lamp_prefixes(prefix, created_by, created_at) VALUES ('氦', 'seed', %s)",
                (now,),
            )
            conn.execute(
                "INSERT INTO prefix_audit(action, prefix, changed_by, changed_at) VALUES ('seed', '氦', 'seed', %s)",
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
        delete_prefix,
        prefix_audit_log,
        list_rejected,
    ],
    on_startup=[on_startup],
)
