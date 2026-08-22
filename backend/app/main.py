import os, time
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from .database import get_db
from .models import TestCase, User
from .schemas import CaseIn, LoginIn

app = FastAPI(title="Case Management Platform")
cors_origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if item.strip()]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"], allow_headers=["*"])
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto"); bearer = HTTPBearer()
SECRET = os.getenv("JWT_SECRET", "change-this-demo-secret-key-to-at-least-32-characters")
def ok(data=None): return {"code": 0, "message": "success", "data": data}
def current_user(token: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)):
    try: uid = jwt.decode(token.credentials, SECRET, algorithms=["HS256"])["user_id"]
    except Exception: raise HTTPException(401, "登录已失效")
    user = db.get(User, uid)
    if not user: raise HTTPException(401, "登录已失效")
    return user
def case_dict(c: TestCase):
    return {"id":c.id,"title":c.title,"module":c.module,"priority":c.priority,"status":c.status,"description":c.description,"expectedResult":c.expected_result,"creator":c.creator,"createTime":c.create_time,"updateTime":c.update_time}
@app.post("/api/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not pwd.verify(body.password, user.password): raise HTTPException(401, "用户名或密码错误")
    token = jwt.encode({"user_id":user.id,"exp":datetime.now(timezone.utc)+timedelta(hours=24)}, SECRET, algorithm="HS256")
    return ok({"token":token,"user":{"id":user.id,"username":user.username,"nickname":user.nickname}})
@app.get("/api/auth/info")
def info(user: User = Depends(current_user)): return ok({"id":user.id,"username":user.username,"nickname":user.nickname})
@app.post("/api/cases")
def create_case(body: CaseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    now=datetime.now(); c=TestCase(**body.model_dump(), creator=user.nickname, create_time=now, update_time=now); db.add(c); db.commit(); db.refresh(c); return ok(case_dict(c))
@app.delete("/api/cases/{case_id}")
def delete_case(case_id:int, _:User=Depends(current_user), db:Session=Depends(get_db)):
    c=db.get(TestCase,case_id)
    if not c: raise HTTPException(404,"用例不存在")
    db.delete(c);db.commit();return ok()
@app.put("/api/cases/{case_id}")
def update_case(case_id:int,body:CaseIn,_:User=Depends(current_user),db:Session=Depends(get_db)):
    c=db.get(TestCase,case_id)
    if not c: raise HTTPException(404,"用例不存在")
    for key,value in body.model_dump().items(): setattr(c,key,value)
    c.update_time=datetime.now();db.commit();return ok()
@app.get("/api/cases/{case_id}")
def get_case(case_id:int,_:User=Depends(current_user),db:Session=Depends(get_db)):
    c=db.get(TestCase,case_id)
    if not c: raise HTTPException(404,"用例不存在")
    return ok(case_dict(c))
@app.get("/api/cases")
def list_cases(current:int=1,size:int=10,module:str|None=None,priority:str|None=None,status:str|None=None,keyword:str|None=None,_:User=Depends(current_user),db:Session=Depends(get_db)):
    q=select(TestCase)
    if module:q=q.where(TestCase.module==module)
    if priority:q=q.where(TestCase.priority==priority)
    if status:q=q.where(TestCase.status==status)
    if keyword:q=q.where(or_(TestCase.title.like(f"%{keyword}%"),TestCase.description.like(f"%{keyword}%")))
    total=db.scalar(select(func.count()).select_from(q.subquery())) or 0
    records=db.scalars(q.order_by(TestCase.update_time.desc()).offset((current-1)*size).limit(size)).all()
    return ok({"records":[case_dict(c) for c in records],"total":total,"current":current,"size":size})
@app.get("/api/cases/statistics")
def statistics(_:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.execute(select(TestCase.status,func.count()).group_by(TestCase.status)).all(); prs=db.execute(select(TestCase.priority,func.count()).group_by(TestCase.priority)).all()
    return ok({"total":db.scalar(select(func.count()).select_from(TestCase)) or 0,"status":{k:v for k,v in rows},"priority":{k:v for k,v in prs}})
@app.get("/api/health")
def health(): return ok({"status":"ok"})
