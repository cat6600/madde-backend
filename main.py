import os
import re
import shutil
from datetime import datetime
from typing import List, Optional, Dict

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 🔹 Supabase는 나중에 쓸 예정이므로, 패키지가 없어도 서버가 죽지 않도록 방어
try:
  from supabase import create_client  # type: ignore
except ImportError:
  create_client = None  # 패키지 없으면 그냥 None으로 둠

# =========================
# 0. Supabase 클라이언트 초기화 (Step 5)
# =========================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase = None
if SUPABASE_URL and SUPABASE_SERVICE_KEY and create_client is not None:
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    print("✅ Supabase client initialized")
else:
    print(
        "⚠️ Supabase client 미사용 상태 "
        "(env 미설정 또는 supabase 패키지 미설치 – 현재는 /uploads 로컬 저장만 사용 중)"
    )


app = FastAPI()

# ✅ CORS 설정
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ 업로드 폴더 설정 (현재는 아직 로컬 파일 사용 중 – 추후 Supabase로 교체 예정)
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# IR 전용 폴더 (uploads/ir)
IR_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "ir")
os.makedirs(IR_UPLOAD_DIR, exist_ok=True)

# IP 전용 폴더 (uploads/ip)
IP_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "ip")
os.makedirs(IP_UPLOAD_DIR, exist_ok=True)

# ✅ 공정 데이터(CAD 등) 전용 폴더
PROCESS_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "process")
os.makedirs(PROCESS_UPLOAD_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/project_uploads", StaticFiles(directory=UPLOAD_DIR), name="project_uploads")

# =========================
# DB 설정 (Postgres + SQLite fallback)
# =========================

# Render에서는 DATABASE_URL이 Postgres(madde-db)로 들어 있고,
# 로컬 개발에서는 없으면 SQLite를 사용하도록 한다.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./madde.db")

if DATABASE_URL.startswith("sqlite"):
    # 로컬 개발용 SQLite
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    # Render Postgres 등
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# =========================
# 1. DB 테이블 정의
# =========================

# ✅ 연구 테이블
class Research(Base):
    __tablename__ = "research"
    id = Column(Integer, primary_key=True)
    sample_type = Column(String)
    property = Column(String)
    value = Column(Float)
    tester = Column(String)
    test_date = Column(String)
    filename = Column(String)  # 파일 없으면 None / 빈 문자열 허용


# ✅ IP 테이블
class IP(Base):
    __tablename__ = "ip"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    number = Column(String)
    apply_date = Column(String)
    reg_date = Column(String)
    inventors = Column(String)
    status = Column(String)


# ✅ IP 파일 테이블 (특허/디자인 등 첨부파일 여러 개)
class IPFile(Base):
    __tablename__ = "ip_files"
    id = Column(Integer, primary_key=True)
    ip_id = Column(Integer, ForeignKey("ip.id"), nullable=False)
    original_name = Column(String)  # 업로드 당시 파일 이름
    stored_name = Column(String)    # 서버에 저장된 실제 파일 이름
    upload_date = Column(String)    # YYYY-MM-DD
    size = Column(Integer)          # byte 단위 크기


# ✅ IR/마케팅 자료 테이블
class IRFile(Base):
    __tablename__ = "ir_files"
    id = Column(Integer, primary_key=True)
    original_name = Column(String)  # 사용자가 업로드한 원래 파일 이름
    stored_name = Column(String)    # 서버에 저장된 실제 파일 이름
    category = Column(String)       # IR / 사진 / 영상 / 브로셔 / 전시회 등
    folder = Column(String)         # 선택 폴더명 (예: Formnext2025)
    upload_date = Column(String)    # 업로드 일자 (YYYY-MM-DD)
    size = Column(Integer)          # 파일 크기 (byte)


# ✅ 인건비(사람) 테이블
class Personnel(Base):
    __tablename__ = "personnel"
    id = Column(Integer, primary_key=True)
    name = Column(String)       # 참여자 이름
    department = Column(String) # 부서
    salary = Column(Integer)    # 연봉 (예: 천원 단위 등)


# ✅ 인건비 과제 배분율 테이블 (사람별 과제 %)
class PersonnelProjectShare(Base):
    __tablename__ = "personnel_project_share"
    id = Column(Integer, primary_key=True)
    personnel_id = Column(Integer)   # Personnel.id
    project_title = Column(String)   # 과제 제목 (또는 코드)
    percent = Column(Float)          # 이 과제에 투입되는 % (0~100)


# ✅ 장비(기계장치) 테이블
class Equipment(Base):
    __tablename__ = "equipment"
    id = Column(Integer, primary_key=True)
    name = Column(String)              # 장치명
    acquisition_cost = Column(Integer) # 취득액 (천원 단위)
    acquisition_date = Column(String)  # 취득일자 (YYYY-MM-DD)


# ✅ 장비 과제 배분율 테이블
class EquipmentProjectShare(Base):
    __tablename__ = "equipment_project_share"
    id = Column(Integer, primary_key=True)
    equipment_id = Column(Integer)   # Equipment.id
    project_title = Column(String)   # 과제 제목
    percent = Column(Float)          # 이 과제에 투입되는 % (0~100)


# ✅ 투자(Investment) 테이블
class Investment(Base):
    __tablename__ = "investments"
    id = Column(Integer, primary_key=True)
    round = Column(String)             # 라운드 (Pre-A, Series A 등)
    contract_date = Column(String)     # 계약일 (YYYY-MM-DD)
    registration_date = Column(String) # 등기일 (YYYY-MM-DD)
    shares = Column(BigInteger)           # 주식수
    amount = Column(BigInteger)           # 투자금 (원 또는 천원 단위)
    investor = Column(String)          # 투자사
    security_type = Column(String)     # 종류 (RCPS, 보통주 등)


# ✅ 공정 데이터 - 견적/발주 현황 테이블
class ProcessOrder(Base):
    __tablename__ = "process_orders"
    id = Column(Integer, primary_key=True)
    company_name = Column(String, nullable=False)          # 업체명
    quote_date = Column(String, nullable=False)            # 견적일 (YYYY-MM-DD)
    category = Column(String, nullable=False)              # 구분 (RBSC, RSiC, WAAM, 기타)
    product_name = Column(String, nullable=False)          # 품명
    quantity = Column(Integer, nullable=False)             # 수량
    unit_manufacturing_cost = Column(Integer, nullable=False)  # 전체 제조원가
    unit_quote_price = Column(Integer, nullable=False)     # 개당 견적가
    total_quote_price = Column(Integer, nullable=False)    # 총 견적가
    status = Column(String, nullable=False)                # 견적중 / 제작중 / 납품완료 / 미진행
    actual_order_amount = Column(Integer)                  # 실제 발주금액
    margin_rate = Column(Float)                            # 마진율(%)
    related_file = Column(String)                          # 관련 파일명/경로
    delivered_at = Column(String)                          # 납품완료일 (YYYY-MM-DD, 매출 인식 기준)
    due_date = Column(String)                              # 납기일 (YYYY-MM-DD)


# ✅ 공정 데이터 - 주문별 공정 상태
class ProcessOrderStatus(Base):
    __tablename__ = "process_order_status"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("process_orders.id"), nullable=False)
    total_process_time_hours = Column(Float)   # 총 공정시간(hr) = 실제 리드타임
    current_stage = Column(String)            # 현 공정 단계
    progress_percent = Column(Float)          # 진행율(%)
    current_detail = Column(String)           # 현 상황(상세)
    priority = Column(String)                 # 이슈/우선순위


# ✅ 공정 데이터 - 단가 테이블
class UnitCost(Base):
    __tablename__ = "unit_costs"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)  # 자동 넘버링
    category = Column(String, nullable=False)  # "재료비" / "소모품비"
    item_name = Column(String, nullable=False)  # 품명
    unit_price = Column(Float, nullable=False)  # 단가
    unit = Column(String, nullable=False)       # KRW/kg, KRW/hr ...
    note = Column(String)                       # 비고


# ✅ 공정 데이터 - 제품별 Raw Tracking 테이블
class ProcessTracking(Base):
    __tablename__ = "process_tracking"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("process_orders.id"), nullable=False)
    product_volume_cm3 = Column(Float)   # 제품 부피
    printing_time_hr = Column(Float)     # 프린팅 시간
    bed_density = Column(Float)          # 베드 밀도
    note = Column(String)


# ✅ 공정 데이터 - RBSC / RSiC 공정 단계별 시간 & 원가 테이블
class ProcessTime(Base):
    __tablename__ = "process_times"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("process_orders.id"), nullable=False)
    process_type = Column(String, nullable=False)  # "RBSC" / "RSiC"

    # 단계별 소요 시간(hr)
    design_hr = Column(Float, default=0)
    printing_hr = Column(Float, default=0)
    infiltration_hr = Column(Float, default=0)
    bonding_hr = Column(Float, default=0)
    lsi_hr = Column(Float, default=0)
    machining_hr = Column(Float, default=0)
    coating_hr = Column(Float, default=0)

    # 제조원가 세부 항목 (추후 계산 로직에서 업데이트 예정)
    material_cost = Column(Float, default=0)    # 재료비
    consumable_cost = Column(Float, default=0)  # 소모품비
    labor_cost = Column(Float, default=0)       # 인건비
    equipment_cost = Column(Float, default=0)   # 장비비
    overhead_cost = Column(Float, default=0)    # 간접비
    total_cost = Column(Float, default=0)       # 총 제조원가


# ✅ 과제(프로젝트) 테이블 – 기존 PROJECTS 메모리 대체
class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)         # 과제명
    organization = Column(String)                  # 주관기관
    type = Column(String)                          # 사업 유형
    period = Column(String)                        # 기간 텍스트 (예: 2025.01~2027.12)
    budget = Column(Float)                         # 총 예산
    status = Column(String)                        # 진행중 / 신청완료 / 종료 등
    due_date = Column(String)                      # 마감일
    participants = Column(String)                  # 참여자 텍스트
    last_updated = Column(String)                  # 마지막 업데이트 날짜(YYYY-MM-DD)


# ✅ 과제별 파일 테이블
class ProjectFile(Base):
    __tablename__ = "project_files"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    filename = Column(String, nullable=False)      # 실제 저장된 파일명(현재는 original 그대로)
    upload_date = Column(String)                   # YYYY-MM-DD


# =========================
# 2. 로그인 (내부용 간단 로그인)
# =========================

ADMIN_PASSWORD = "aodlem0627@"
VIEWER_PASSWORD = "madde-viewer"


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    """
    매우 단순한 내부용 로그인:
    - username: "admin" 또는 "viewer" (프론트에서 role로 보냄)
    """
    if username == "admin" and password == ADMIN_PASSWORD:
        return {"message": "로그인 성공", "role": "admin"}

    if username == "viewer" and password == VIEWER_PASSWORD:
        return {"message": "로그인 성공", "role": "viewer"}

    raise HTTPException(status_code=401, detail="로그인 실패")


# =========================
# 3. 연구 데이터 관리
# =========================

@app.get("/research")
def get_research():
    db = SessionLocal()
    data = db.query(Research).all()
    db.close()
    return data


@app.post("/research")
async def upload_research(
    # ✅ 파일이 없어도 등록 가능하도록 Optional 처리
    file: Optional[UploadFile] = File(None),
    sample_type: str = Form(...),
    property: str = Form(...),
    value: float = Form(...),
    tester: str = Form(...),
    test_date: str = Form(...),
):
    filename: Optional[str] = None

    # 파일이 있는 경우에만 저장 처리 (현재는 로컬 /uploads – 추후 Supabase로 교체 예정)
    if file is not None:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename)
        name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}"
        path = os.path.join(UPLOAD_DIR, name)
        with open(path, "wb") as b:
            shutil.copyfileobj(file.file, b)
        filename = name

    db = SessionLocal()
    db.add(
        Research(
            sample_type=sample_type,
            property=property,
            value=value,
            tester=tester,
            test_date=test_date,
            filename=filename,
        )
    )
    db.commit()
    db.close()
    return {"message": "업로드 완료"}

@app.delete("/research/{research_id}")
def delete_research(research_id: int):
    db = SessionLocal()
    try:
        rec = db.query(Research).filter(Research.id == research_id).first()
        if not rec:
            raise HTTPException(status_code=404, detail="해당 연구 데이터를 찾을 수 없습니다.")

        # 파일 있으면 같이 삭제
        if rec.filename:
            file_path = os.path.join(UPLOAD_DIR, rec.filename)
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

        db.delete(rec)
        db.commit()
        return {"message": "연구 데이터 삭제 완료 ✅"}
    finally:
        db.close()


# =========================
# 4. IP 데이터 관리 + 파일 관리
# =========================

@app.get("/ip")
def get_ip():
    db = SessionLocal()
    try:
        data = db.query(IP).all()
        return data
    finally:
        db.close()


@app.post("/ip")
def add_ip(
    title: str = Form(...),
    number: str = Form(...),
    apply_date: str = Form(""),
    reg_date: str = Form(""),
    inventors: str = Form(""),
    status: str = Form(""),
):
    db = SessionLocal()
    try:
        ip = IP(
            title=title,
            number=number,
            apply_date=apply_date,
            reg_date=reg_date,
            inventors=inventors,
            status=status,
        )
        db.add(ip)
        db.commit()
        db.refresh(ip)
        return {"message": "IP 등록 완료 ✅", "id": ip.id}
    finally:
        db.close()


@app.delete("/ip/{ip_id}")
def delete_ip(ip_id: int):
    db = SessionLocal()
    try:
        ip = db.query(IP).filter(IP.id == ip_id).first()
        if not ip:
            raise HTTPException(status_code=404, detail="해당 IP를 찾을 수 없습니다.")

        # ✅ 해당 IP와 연결된 파일들도 같이 삭제 (현재는 로컬 디스크 기준)
        files = db.query(IPFile).filter(IPFile.ip_id == ip_id).all()
        for f in files:
            file_path = os.path.join(IP_UPLOAD_DIR, f.stored_name)
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
            db.delete(f)

        db.delete(ip)
        db.commit()
        return {"message": "IP 삭제 완료 ✅"}
    finally:
        db.close()


# ---- IP 파일 목록 조회 ----
@app.get("/ip/{ip_id}/files")
def get_ip_files(ip_id: int):
    db = SessionLocal()
    try:
        rows = db.query(IPFile).filter(IPFile.ip_id == ip_id).all()
        return [
            {
                "id": r.id,
                "ip_id": r.ip_id,
                "original_name": r.original_name,
                "stored_name": r.stored_name,
                "upload_date": r.upload_date,
                "size": r.size,
            }
            for r in rows
        ]
    finally:
        db.close()


# ---- IP 파일 업로드 (여러 개) ----
@app.post("/ip/{ip_id}/files")
async def upload_ip_files(
    ip_id: int,
    files: List[UploadFile] = File(...),   # ✅ 이름: files, 타입: List[UploadFile]
):
    db = SessionLocal()
    try:
        ip_obj = db.query(IP).filter(IP.id == ip_id).first()
        if not ip_obj:
            raise HTTPException(status_code=404, detail="해당 IP 항목이 없습니다.")

        uploaded_ids = []

        for file in files:
            original_name = file.filename
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", original_name)
            stored_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}"
            file_path = os.path.join(IP_UPLOAD_DIR, stored_name)

            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

            size = os.path.getsize(file_path)
            upload_date = datetime.now().strftime("%Y-%m-%d")

            rec = IPFile(
                ip_id=ip_id,
                original_name=original_name,
                stored_name=stored_name,
                upload_date=upload_date,
                size=size,
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)
            uploaded_ids.append(rec.id)

        return {"message": "IP 파일 업로드 완료 ✅", "ids": uploaded_ids}
    finally:
        db.close()


# ---- IP 파일 삭제 ----
@app.delete("/ip/files/{file_id}")
def delete_ip_file(file_id: int):
    db = SessionLocal()
    try:
        rec = db.query(IPFile).filter(IPFile.id == file_id).first()
        if not rec:
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

        file_path = os.path.join(IP_UPLOAD_DIR, rec.stored_name)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

        db.delete(rec)
        db.commit()
        return {"message": "IP 파일 삭제 완료 ✅"}
    finally:
        db.close()


# =========================
# 5. IR/마케팅 자료 관리
# =========================

@app.get("/ir")
def get_ir(category: Optional[str] = None):
    db = SessionLocal()
    try:
        query = db.query(IRFile)
        if category and category != "전체":
            query = query.filter(IRFile.category == category)
        records = query.all()

        result = [
            {
                "id": r.id,
                "original_name": r.original_name,
                "stored_name": r.stored_name,
                "category": r.category,
                "folder": r.folder,
                "upload_date": r.upload_date,
                "size": r.size,
            }
            for r in records
        ]
        result = sorted(result, key=lambda x: x["original_name"].lower())
        return result
    finally:
        db.close()


@app.post("/ir")
async def upload_ir(
    file: List[UploadFile] = File(...),   # ✅ 여러 파일
    category: str = Form("IR"),
    folder: Optional[str] = Form(None),
):
    """
    IR/마케팅 자료 다중 파일 업로드
    - file: 같은 category/folder로 업로드할 여러 파일들
    """
    saved_ids = []

    # 폴더 경로 결정 (현재는 로컬 디스크)
    base_dir = IR_UPLOAD_DIR
    if folder:
        base_dir = os.path.join(IR_UPLOAD_DIR, folder)
    os.makedirs(base_dir, exist_ok=True)

    db = SessionLocal()
    try:
        for f in file:
            original_name = f.filename
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", original_name)
            stored_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}"

            file_path = os.path.join(base_dir, stored_name)
            with open(file_path, "wb") as b:
                shutil.copyfileobj(f.file, b)

            file_size = os.path.getsize(file_path)
            upload_date = datetime.now().strftime("%Y-%m-%d")

            ir = IRFile(
                original_name=original_name,
                stored_name=stored_name,
                category=category,
                folder=folder,
                upload_date=upload_date,
                size=file_size,
            )
            db.add(ir)
            db.commit()
            db.refresh(ir)
            saved_ids.append(ir.id)

        return {
            "message": "IR 자료 업로드 완료 ✅",
            "count": len(saved_ids),
            "ids": saved_ids,
        }
    finally:
        db.close()


@app.delete("/ir/{ir_id}")
def delete_ir(ir_id: int):
    db = SessionLocal()
    try:
        ir = db.query(IRFile).filter(IRFile.id == ir_id).first()
        if not ir:
            raise HTTPException(status_code=404, detail="해당 IR 자료를 찾을 수 없습니다.")

        base_dir = IR_UPLOAD_DIR
        if ir.folder:
            base_dir = os.path.join(IR_UPLOAD_DIR, ir.folder)
        file_path = os.path.join(base_dir, ir.stored_name)

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

        db.delete(ir)
        db.commit()
        return {"message": "IR 자료 삭제 완료 ✅"}
    finally:
        db.close()


# =========================
# 6. 인건비 / 현물 현황
# =========================

@app.get("/personnel")
def get_personnel():
    db = SessionLocal()
    try:
        people = db.query(Personnel).all()
        return people
    finally:
        db.close()


@app.post("/personnel")
def add_personnel(
    name: str = Form(...),
    department: str = Form(...),
    salary: int = Form(...),
):
    db = SessionLocal()
    try:
        p = Personnel(name=name, department=department, salary=salary)
        db.add(p)
        db.commit()
        db.refresh(p)
        return {"message": "인건비 인력 등록 완료 ✅", "id": p.id}
    finally:
        db.close()


@app.delete("/personnel/{person_id}")
def delete_personnel(person_id: int):
    db = SessionLocal()
    try:
        person = db.query(Personnel).filter(Personnel.id == person_id).first()
        if not person:
            raise HTTPException(status_code=404, detail="해당 인력을 찾을 수 없습니다.")
        db.query(PersonnelProjectShare).filter(
            PersonnelProjectShare.personnel_id == person_id
        ).delete()
        db.delete(person)
        db.commit()
        return {"message": "인건비 인력 삭제 완료 ✅"}
    finally:
        db.close()


class ShareUpdate(BaseModel):
    shares: Dict[str, float]


@app.put("/personnel/{person_id}/shares")
def update_personnel_shares(person_id: int, payload: ShareUpdate):
    db = SessionLocal()
    try:
        person = db.query(Personnel).filter(Personnel.id == person_id).first()
        if not person:
            raise HTTPException(status_code=404, detail="해당 인력을 찾을 수 없습니다.")

        db.query(PersonnelProjectShare).filter(
            PersonnelProjectShare.personnel_id == person_id
        ).delete()

        for title, percent in (payload.shares or {}).items():
            if percent is None:
                continue
            try:
                val = float(percent)
            except Exception:
                continue
            if val <= 0:
                continue
            db.add(
                PersonnelProjectShare(
                    personnel_id=person_id,
                    project_title=title,
                    percent=val,
                )
            )
        db.commit()
        return {"message": "배분율 업데이트 완료 ✅"}
    finally:
        db.close()


@app.get("/equipment")
def get_equipment():
    db = SessionLocal()
    try:
        eqs = db.query(Equipment).all()
        return eqs
    finally:
        db.close()


@app.post("/equipment")
def add_equipment(
    name: str = Form(...),
    acquisition_cost: int = Form(...),
    acquisition_date: str = Form(...),
):
    db = SessionLocal()
    try:
        e = Equipment(
            name=name,
            acquisition_cost=acquisition_cost,
            acquisition_date=acquisition_date,
        )
        db.add(e)
        db.commit()
        db.refresh(e)
        return {"message": "장비 등록 완료 ✅", "id": e.id}
    finally:
        db.close()


@app.delete("/equipment/{equipment_id}")
def delete_equipment(equipment_id: int):
    db = SessionLocal()
    try:
        eq = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not eq:
            raise HTTPException(status_code=404, detail="해당 장비를 찾을 수 없습니다.")
        db.query(EquipmentProjectShare).filter(
            EquipmentProjectShare.equipment_id == equipment_id
        ).delete()
        db.delete(eq)
        db.commit()
        return {"message": "장비 삭제 완료 ✅"}
    finally:
        db.close()


@app.put("/equipment/{equipment_id}/shares")
def update_equipment_shares(equipment_id: int, payload: ShareUpdate):
    db = SessionLocal()
    try:
        eq = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not eq:
            raise HTTPException(status_code=404, detail="해당 장비를 찾을 수 없습니다.")

        db.query(EquipmentProjectShare).filter(
            EquipmentProjectShare.equipment_id == equipment_id
        ).delete()

        for title, percent in (payload.shares or {}).items():
            if percent is None:
                continue
            try:
                val = float(percent)
            except Exception:
                continue
            if val <= 0:
                continue
            db.add(
                EquipmentProjectShare(
                    equipment_id=equipment_id,
                    project_title=title,
                    percent=val,
                )
            )
        db.commit()
        return {"message": "장비 배분율 업데이트 완료 ✅"}
    finally:
        db.close()


def get_active_project_titles() -> List[str]:
    """
    현재 DB 기반 projects 테이블에서
    status가 진행중/신청완료인 과제 제목만 가져옴.
    """
    active_status = {"진행중", "신청완료"}
    db = SessionLocal()
    try:
        rows = (
            db.query(Project)
            .filter(Project.status.in_(list(active_status)))
            .all()
        )
        titles = [r.title for r in rows if r.title]
        # 중복 제거 + 순서 유지
        return list(dict.fromkeys(titles))
    except Exception as e:
        print("❌ get_active_project_titles DB error:", repr(e))
        return []
    finally:
        try:
            db.close()
        except Exception:
            pass


@app.get("/assets")
def get_assets():
    """
    현물 현황 페이지용 API
    - projects: 현재 진행/신청완료 과제 목록 (DB 기반 projects 테이블)
    - personnel_rows: 인건비(사람) 배분 현황
    - equipment_rows: 장비/현물 배분 현황
    에러가 나더라도 500 대신 빈 구조를 반환해서 프론트가 죽지 않도록 방어적으로 작성.
    """
    empty_result = {
        "projects": [],
        "personnel_rows": [],
        "personnel_salary_total": 0,
        "personnel_grand_total": 0,
        "equipment_rows": [],
        "equipment_acquisition_total": 0,
        "equipment_grand_total": 0,
    }

    try:
        db = SessionLocal()
        people = db.query(Personnel).all()
        person_shares = db.query(PersonnelProjectShare).all()
        equipments = db.query(Equipment).all()
        equip_shares = db.query(EquipmentProjectShare).all()
    except Exception as e:
        print("❌ /assets DB error:", repr(e))
        return empty_result
    finally:
        try:
            db.close()
        except Exception:
            pass

    try:
        active_projects = get_active_project_titles()

        # --- 인건비(사람) 계산 ---
        person_share_map: Dict[int, Dict[str, float]] = {}
        for s in person_shares:
            if s.project_title not in active_projects:
                continue
            if s.personnel_id not in person_share_map:
                person_share_map[s.personnel_id] = {}
            person_share_map[s.personnel_id][s.project_title] = float(s.percent or 0)

        personnel_rows = []
        personnel_salary_total = 0.0
        personnel_grand_total = 0.0

        for person in people:
            proj_shares = {title: 0.0 for title in active_projects}
            if person.id in person_share_map:
                for title, val in person_share_map[person.id].items():
                    if title in proj_shares:
                        proj_shares[title] = val

            total_percent = sum(proj_shares.values())
            salary = float(person.salary or 0)
            total_amount = salary * (total_percent / 100.0)

            personnel_salary_total += salary
            personnel_grand_total += total_amount

            personnel_rows.append(
                {
                    "person_id": person.id,
                    "name": person.name,
                    "department": person.department,
                    "salary": person.salary,
                    "shares": proj_shares,
                    "total_percent": total_percent,
                    "total_amount": int(total_amount),
                }
            )

        # --- 장비(현물) 계산 ---
        equip_share_map: Dict[int, Dict[str, float]] = {}
        for s in equip_shares:
            if s.project_title not in active_projects:
                continue
            if s.equipment_id not in equip_share_map:
                equip_share_map[s.equipment_id] = {}
            equip_share_map[s.equipment_id][s.project_title] = float(s.percent or 0)

        equipment_rows = []
        equipment_acquisition_total = 0.0
        equipment_grand_total = 0.0

        for eq in equipments:
            proj_shares = {title: 0.0 for title in active_projects}
            if eq.id in equip_share_map:
                for title, val in equip_share_map[eq.id].items():
                    if title in proj_shares:
                        proj_shares[title] = val

            total_percent = sum(proj_shares.values())
            cost = float(eq.acquisition_cost or 0)
            total_amount = cost * (total_percent / 100.0)

            equipment_acquisition_total += cost
            equipment_grand_total += total_amount

            equipment_rows.append(
                {
                    "equipment_id": eq.id,
                    "name": eq.name,
                    "acquisition_cost": eq.acquisition_cost,
                    "acquisition_date": eq.acquisition_date,
                    "shares": proj_shares,
                    "total_percent": total_percent,
                    "total_amount": int(total_amount),
                }
            )

        return {
            "projects": active_projects,
            "personnel_rows": personnel_rows,
            "personnel_salary_total": int(personnel_salary_total),
            "personnel_grand_total": int(personnel_grand_total),
            "equipment_rows": equipment_rows,
            "equipment_acquisition_total": int(equipment_acquisition_total),
            "equipment_grand_total": int(equipment_grand_total),
        }
    except Exception as e:
        print("❌ /assets calc error:", repr(e))
        return empty_result


# =========================
# 7. 공정 데이터 API
# =========================

class ProcessOrderSchema(BaseModel):
    id: Optional[int] = None
    company_name: str
    quote_date: str
    category: str                # RBSC / RSiC / WAAM / 기타
    product_name: str
    quantity: int
    unit_manufacturing_cost: int # 전체 제조원가로 사용
    unit_quote_price: int
    total_quote_price: int
    status: str                  # 견적중 / 제작중 / 납품완료 / 미진행
    actual_order_amount: Optional[int] = None
    margin_rate: Optional[float] = None
    related_file: Optional[str] = None
    delivered_at: Optional[str] = None  # 납품완료일 (납품완료 상태 시 입력)
    due_date: Optional[str] = None

    class Config:
        orm_mode = True


class ProcessOrderStatusSchema(BaseModel):
    id: Optional[int] = None
    order_id: int
    total_process_time_hours: Optional[float] = None
    current_stage: Optional[str] = None
    progress_percent: Optional[float] = None
    current_detail: Optional[str] = None
    priority: Optional[str] = None

    class Config:
        orm_mode = True


class UnitCostBase(BaseModel):
    category: str
    item_name: str
    unit_price: float
    unit: str
    note: Optional[str] = None


class UnitCostCreate(UnitCostBase):
    pass


class UnitCostRead(UnitCostBase):
    id: int

    class Config:
        orm_mode = True


class ProcessTrackingSchema(BaseModel):
    id: Optional[int] = None
    order_id: int
    product_volume_cm3: Optional[float] = None
    printing_time_hr: Optional[float] = None
    bed_density: Optional[float] = None
    note: Optional[str] = None

    class Config:
        orm_mode = True


# ✅ RBSC / RSiC 공정 단계별 시간 & 원가 스키마
class ProcessTimeBase(BaseModel):
    order_id: int
    process_type: str  # "RBSC" or "RSiC"

    design_hr: float = 0
    printing_hr: float = 0
    infiltration_hr: float = 0
    bonding_hr: float = 0
    lsi_hr: float = 0
    machining_hr: float = 0
    coating_hr: float = 0


class ProcessTimeCreate(ProcessTimeBase):
    pass


class ProcessTimeRead(ProcessTimeBase):
    id: int
    material_cost: float
    consumable_cost: float
    labor_cost: float
    equipment_cost: float
    overhead_cost: float
    total_cost: float

    class Config:
        orm_mode = True


# ---- 견적/발주(=제작 및 매출 현황) 목록 ----
@app.get("/process/orders", response_model=List[ProcessOrderSchema])
def get_process_orders():
    """
    제작 및 매출 현황 테이블용 전체 리스트
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(ProcessOrder)
            .order_by(ProcessOrder.quote_date.desc(), ProcessOrder.id.desc())
            .all()
        )
        return rows
    finally:
        db.close()


# ---- 견적/발주(=제작 및 매출 현황) 생성 ----
@app.post("/process/orders", response_model=ProcessOrderSchema)
async def create_process_order(
    company_name: str = Form(...),
    quote_date: str = Form(...),
    category: str = Form(...),             # RBSC / RSiC / WAAM / 기타
    product_name: str = Form(...),
    quantity: int = Form(...),
    manufacturing_cost: int = Form(...),   # ✅ 전체 제조원가
    total_quote_price: int = Form(...),    # ✅ 전체 견적가
    status: str = Form(...),               # 견적중 / 제작중 / 납품완료 / 미진행
    due_date: str = Form(...),
    actual_order_amount: Optional[int] = Form(None),
    file: Optional[UploadFile] = File(None),  # CAD 등 파일
):
    db = SessionLocal()
    try:
        # 🔹 파일 업로드 처리 (현재는 로컬 디스크 – 추후 Supabase Storage로 변경 예정)
        stored_name = None
        if file is not None:
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename)
            stored_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}"
            file_path = os.path.join(PROCESS_UPLOAD_DIR, stored_name)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

        # 🔹 개당 견적가 = 전체 견적가 / 수량
        unit_quote_price = int(total_quote_price / quantity) if quantity else 0

        # 🔹 마진율 = (전체 견적가 - 제조원가) / 전체 견적가 * 100
        margin_rate = None
        if total_quote_price > 0:
            margin_rate = (
                (total_quote_price - manufacturing_cost)
                / total_quote_price
                * 100.0
            )

        delivered_at = None
        if status == "납품완료":
            delivered_at = datetime.now().strftime("%Y-%m-%d")

        obj = ProcessOrder(
            company_name=company_name,
            quote_date=quote_date,
            category=category,
            product_name=product_name,
            quantity=quantity,
            # 이 컬럼은 "전체 제조원가" 의미로 사용
            unit_manufacturing_cost=manufacturing_cost,
            unit_quote_price=unit_quote_price,
            total_quote_price=total_quote_price,
            status=status,
            actual_order_amount=actual_order_amount,
            margin_rate=margin_rate,
            related_file=stored_name,
            delivered_at=delivered_at,
            due_date=due_date,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)

        # 🔹 상태가 '제작중'으로 생성된 경우 → 공정 데이터용 기본 row 생성
        if status == "제작중":
            tracking = ProcessTracking(order_id=obj.id)
            db.add(tracking)
            db.commit()

        return obj
    finally:
        db.close()


# ---- 견적/발주(=제작 및 매출 현황) 수정 ----
@app.put("/process/orders/{order_id}", response_model=ProcessOrderSchema)
async def update_process_order(order_id: int, payload: ProcessOrderSchema):
    db = SessionLocal()
    try:
        obj: ProcessOrder = (
            db.query(ProcessOrder).filter(ProcessOrder.id == order_id).first()
        )
        if not obj:
            raise HTTPException(status_code=404, detail="해당 주문을 찾을 수 없습니다.")

        old_status = obj.status

        # -----------------------------
        # 기본 필드 업데이트
        # -----------------------------
        obj.company_name = payload.company_name
        obj.quote_date = payload.quote_date
        obj.category = payload.category
        obj.product_name = payload.product_name
        obj.quantity = payload.quantity
        obj.status = payload.status
        obj.actual_order_amount = payload.actual_order_amount
        obj.related_file = payload.related_file

        # -----------------------------
        # due_date 업데이트
        # -----------------------------
        obj.due_date = payload.due_date

        # -----------------------------
        # 제조원가/견적가/마진율 계산
        # -----------------------------
        obj.unit_manufacturing_cost = payload.unit_manufacturing_cost
        obj.total_quote_price = payload.total_quote_price

        if obj.quantity and obj.total_quote_price:
            obj.unit_quote_price = int(obj.total_quote_price / obj.quantity)
        else:
            obj.unit_quote_price = 0

        if obj.total_quote_price:
            obj.margin_rate = (
                (obj.total_quote_price - (obj.unit_manufacturing_cost or 0))
                / obj.total_quote_price
                * 100.0
            )
        else:
            obj.margin_rate = None

        # -----------------------------
        # status 변화 로직 처리
        # -----------------------------
        if old_status != "제작중" and obj.status == "제작중":
            existing = (
                db.query(ProcessTracking)
                .filter(ProcessTracking.order_id == obj.id)
                .first()
            )
            if not existing:
                tracking = ProcessTracking(order_id=obj.id)
                db.add(tracking)

        if old_status != "납품완료" and obj.status == "납품완료":
            obj.delivered_at = datetime.now().strftime("%Y-%m-%d")

        db.commit()
        db.refresh(obj)
        return obj

    finally:
        db.close()


# ---- 공정 상태 ----
@app.get(
    "/process/orders/{order_id}/status",
    response_model=List[ProcessOrderStatusSchema],
)
def get_order_status(order_id: int):
    db = SessionLocal()
    try:
        rows = db.query(ProcessOrderStatus).filter(
            ProcessOrderStatus.order_id == order_id
        ).all()
        return rows
    finally:
        db.close()


@app.post(
    "/process/orders/{order_id}/status",
    response_model=ProcessOrderStatusSchema,
)
def create_or_update_order_status(order_id: int, payload: ProcessOrderStatusSchema):
    db = SessionLocal()
    try:
        existing = (
            db.query(ProcessOrderStatus)
            .filter(ProcessOrderStatus.order_id == order_id)
            .first()
        )

        if existing:
            existing.total_process_time_hours = payload.total_process_time_hours
            existing.current_stage = payload.current_stage
            existing.progress_percent = payload.progress_percent
            existing.current_detail = payload.current_detail
            existing.priority = payload.priority
            db.commit()
            db.refresh(existing)
            return existing

        obj = ProcessOrderStatus(
            order_id=order_id,
            total_process_time_hours=payload.total_process_time_hours,
            current_stage=payload.current_stage,
            progress_percent=payload.progress_percent,
            current_detail=payload.current_detail,
            priority=payload.priority,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    finally:
        db.close()


# ---- 단가 테이블 ----
@app.get("/process/unit-costs", response_model=List[UnitCostRead])
def get_unit_costs():
    db = SessionLocal()
    try:
        rows = db.query(UnitCost).order_by(UnitCost.id).all()
        return rows
    finally:
        db.close()


@app.post("/process/unit-costs", response_model=UnitCostRead)
def create_unit_cost(cost: UnitCostCreate):
    """
    ID는 자동 증가. 프론트에서는 category, item_name, unit, unit_price, note만 보냄.
    """
    db = SessionLocal()
    try:
        obj = UnitCost(
            category=cost.category,
            item_name=cost.item_name,
            unit_price=cost.unit_price,
            unit=cost.unit,
            note=cost.note,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    finally:
        db.close()


@app.put("/process/unit-costs/{unit_id}", response_model=UnitCostRead)
def update_unit_cost(unit_id: int, cost: UnitCostCreate):
    db = SessionLocal()
    try:
        obj = db.query(UnitCost).filter(UnitCost.id == unit_id).first()
        if not obj:
            raise HTTPException(status_code=404, detail="단가 정보를 찾을 수 없습니다.")

        obj.category = cost.category
        obj.item_name = cost.item_name
        obj.unit_price = cost.unit_price
        obj.unit = cost.unit
        obj.note = cost.note

        db.commit()
        db.refresh(obj)
        return obj
    finally:
        db.close()


@app.delete("/process/unit-costs/{unit_id}")
def delete_unit_cost(unit_id: int):
    db = SessionLocal()
    try:
        obj = db.query(UnitCost).filter(UnitCost.id == unit_id).first()
        if not obj:
            raise HTTPException(status_code=404, detail="단가 정보를 찾을 수 없습니다.")
        db.delete(obj)
        db.commit()
        return {"message": "단가 정보 삭제 완료 ✅"}
    finally:
        db.close()


# ---- 공정 Raw Tracking ----
@app.get("/process/trackings", response_model=List[ProcessTrackingSchema])
def get_trackings():
    """
    공정 데이터 탭에서 사용할 Raw Tracking 리스트
    """
    db = SessionLocal()
    try:
        rows = db.query(ProcessTracking).all()
        return rows
    finally:
        db.close()


@app.post("/process/trackings", response_model=ProcessTrackingSchema)
def create_tracking(tr: ProcessTrackingSchema):
    db = SessionLocal()
    try:
        obj = ProcessTracking(
            order_id=tr.order_id,
            product_volume_cm3=tr.product_volume_cm3,
            printing_time_hr=tr.printing_time_hr,
            bed_density=tr.bed_density,
            note=tr.note,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    finally:
        db.close()


@app.put("/process/trackings/{tracking_id}", response_model=ProcessTrackingSchema)
def update_tracking(tracking_id: int, tr: ProcessTrackingSchema):
    db = SessionLocal()
    try:
        obj = db.query(ProcessTracking).filter(ProcessTracking.id == tracking_id).first()
        if not obj:
            raise HTTPException(status_code=404, detail="추적 데이터를 찾을 수 없습니다.")

        obj.order_id = tr.order_id
        obj.product_volume_cm3 = tr.product_volume_cm3
        obj.printing_time_hr = tr.printing_time_hr
        obj.bed_density = tr.bed_density
        obj.note = tr.note

        db.commit()
        db.refresh(obj)
        return obj
    finally:
        db.close()


@app.delete("/process/trackings/{tracking_id}")
def delete_tracking(tracking_id: int):
    db = SessionLocal()
    try:
        obj = db.query(ProcessTracking).filter(ProcessTracking.id == tracking_id).first()
        if not obj:
            raise HTTPException(status_code=404, detail="추적 데이터를 찾을 수 없습니다.")
        db.delete(obj)
        db.commit()
        return {"message": "추적 데이터 삭제 완료 ✅"}
    finally:
        db.close()


# ---- RBSC / RSiC 공정 단계별 시간 ----
@app.post("/process/times", response_model=ProcessTimeRead)
def upsert_process_time(data: ProcessTimeCreate):
    """
    RBSC / RSiC 공정 단계별 시간 입력용 API
    - order_id + process_type 기준 upsert
    """
    db = SessionLocal()
    try:
        existing = (
            db.query(ProcessTime)
            .filter(
                ProcessTime.order_id == data.order_id,
                ProcessTime.process_type == data.process_type,
            )
            .first()
        )

        if existing:
            for field, value in data.dict().items():
                setattr(existing, field, value)
            db.commit()
            db.refresh(existing)
            return existing

        obj = ProcessTime(**data.dict())
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    finally:
        db.close()


@app.get("/process/times/{order_id}", response_model=List[ProcessTimeRead])
def get_process_times(order_id: int):
    """
    특정 주문(order_id)에 대한 RBSC/RSiC 공정 시간 조회
    """
    db = SessionLocal()
    try:
        rows = db.query(ProcessTime).filter(ProcessTime.order_id == order_id).all()
        return rows
    finally:
        db.close()


# ---- 제작 및 매출 현황 상단 KPI용 요약 API ----
@app.get("/sales/summary")
def get_sales_summary():
    """
    제작 및 매출 현황 상단 카드용:
    - total_sales_all      : 전체 매출 (납품완료 기준, 총 견적가 합)
    - total_sales_year     : 올해 매출
    - total_sales_quarter  : 이번 분기 매출
    - total_sales_month    : 이번 달 매출
    """
    db = SessionLocal()
    try:
        now = datetime.now()
        this_year = now.year
        this_month = now.month
        this_quarter = (this_month - 1) // 3 + 1

        def parse_date(s: Optional[str]):
            if not s:
                return None
            try:
                return datetime.strptime(s, "%Y-%m-%d")
            except Exception:
                return None

        # 납품완료된 주문만 매출로 인식
        delivered_orders = db.query(ProcessOrder).filter(
            ProcessOrder.status == "납품완료"
        ).all()

        total_all = 0
        total_year = 0
        total_quarter = 0
        total_month = 0

        for o in delivered_orders:
            amount = int(o.total_quote_price or 0)
            total_all += amount
            d = parse_date(o.delivered_at)
            if not d:
                continue

            if d.year == this_year:
                total_year += amount

                q = (d.month - 1) // 3 + 1
                if q == this_quarter:
                    total_quarter += amount

                if d.month == this_month:
                    total_month += amount

        return {
            "year": this_year,
            "quarter": this_quarter,
            "month": this_month,
            "total_sales_all": total_all,
            "total_sales_year": total_year,
            "total_sales_quarter": total_quarter,
            "total_sales_month": total_month,
        }
    finally:
        db.close()


# =========================
# 8. 재무 / 투자 현황
# =========================

@app.get("/investments")
def get_investments():
    db = SessionLocal()
    try:
        items = db.query(Investment).all()
        return items
    finally:
        db.close()


@app.post("/investments")
def add_investment(
    round: str = Form(...),
    contract_date: str = Form(""),
    registration_date: str = Form(""),
    shares: int = Form(0),
    amount: int = Form(0),
    investor: str = Form(""),
    security_type: str = Form(""),
):
    db = SessionLocal()
    try:
        inv = Investment(
            round=round,
            contract_date=contract_date,
            registration_date=registration_date,
            shares=shares,
            amount=amount,
            investor=investor,
            security_type=security_type,
        )
        db.add(inv)
        db.commit()
        db.refresh(inv)
        return {"message": "투자 이력 등록 완료 ✅", "id": inv.id}
    finally:
        db.close()


@app.put("/investments/{investment_id}")
def update_investment(
    investment_id: int,
    round: str = Form(...),
    contract_date: str = Form(...),
    registration_date: str = Form(...),
    shares: int = Form(...),
    amount: int = Form(...),
    investor: str = Form(...),
    security_type: str = Form(...),
):
    db = SessionLocal()
    try:
        inv = db.query(Investment).filter(Investment.id == investment_id).first()
        if not inv:
            raise HTTPException(status_code=404, detail="해당 투자 이력을 찾을 수 없습니다.")

        inv.round = round
        inv.contract_date = contract_date
        inv.registration_date = registration_date
        inv.shares = shares
        inv.amount = amount
        inv.investor = investor
        inv.security_type = security_type

        db.commit()
        db.refresh(inv)
        return {"message": "투자 이력 수정 완료 ✅", "id": inv.id}
    finally:
        db.close()


@app.delete("/investments/{investment_id}")
def delete_investment(investment_id: int):
    db = SessionLocal()
    try:
        inv = db.query(Investment).filter(Investment.id == investment_id).first()
        if not inv:
            raise HTTPException(status_code=404, detail="해당 투자 이력을 찾을 수 없습니다.")
        db.delete(inv)
        db.commit()
        return {"message": "투자 이력 삭제 완료 ✅"}
    finally:
        db.close()


# =========================
# 9. 과제 데이터 – DB 기반으로 변경
# =========================

class ProjectBase(BaseModel):
    title: str
    organization: Optional[str] = None
    type: Optional[str] = None
    period: Optional[str] = None
    budget: Optional[float] = 0.0
    status: Optional[str] = None
    due_date: Optional[str] = None
    participants: Optional[str] = None


def _project_to_dict(db: SessionLocal, proj: Project) -> dict:
    """
    Project + ProjectFile을 프론트에서 쓰던 dict 형태로 변환
    (id, title, organization, ..., last_updated, files[])
    """
    files = (
        db.query(ProjectFile)
        .filter(ProjectFile.project_id == proj.id)
        .all()
    )
    file_names = [f.filename for f in files]

    return {
        "id": proj.id,
        "title": proj.title,
        "organization": proj.organization,
        "type": proj.type,
        "period": proj.period,
        "budget": proj.budget,
        "status": proj.status,
        "due_date": proj.due_date,
        "participants": proj.participants,
        "last_updated": proj.last_updated,
        "files": file_names,
    }


@app.get("/projects")
def get_projects():
    """
    과제 현황 페이지용 – DB 기반 projects + project_files
    """
    db = SessionLocal()
    try:
        rows = db.query(Project).order_by(Project.id.asc()).all()
        return [_project_to_dict(db, p) for p in rows]
    finally:
        db.close()


@app.post("/projects")
def add_project(project: dict = Body(...)):
    """
    새 과제 추가 – 기존과 동일하게 dict를 받고, DB에 저장.
    """
    db = SessionLocal()
    try:
        now_str = datetime.now().strftime("%Y-%m-%d")
        title = project.get("title")
        if not title:
            raise HTTPException(status_code=400, detail="title은 필수입니다.")

        proj = Project(
            title=title,
            organization=project.get("organization"),
            type=project.get("type"),
            period=project.get("period"),
            budget=project.get("budget") or 0.0,
            status=project.get("status"),
            due_date=project.get("due_date"),
            participants=project.get("participants"),
            last_updated=now_str,
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)

        proj_dict = _project_to_dict(db, proj)
        print("✅ 새 과제 등록(DB):", proj_dict)
        return {"message": "과제 등록 완료", "project": proj_dict}
    except HTTPException:
        raise
    except Exception as e:
        print("❌ /projects add_project error:", repr(e))
        raise HTTPException(status_code=400, detail=f"등록 실패: {str(e)}")
    finally:
        try:
            db.close()
        except Exception:
            pass


@app.put("/projects/{project_id}")
def update_project(project_id: int, project: dict = Body(...)):
    """
    과제 수정 – project_id에 해당하는 DB row를 project dict로 업데이트.
    """
    db = SessionLocal()
    try:
        proj = db.query(Project).filter(Project.id == project_id).first()
        if not proj:
            raise HTTPException(status_code=404, detail="해당 과제를 찾을 수 없습니다.")

        proj.title = project.get("title", proj.title)
        proj.organization = project.get("organization", proj.organization)
        proj.type = project.get("type", proj.type)
        proj.period = project.get("period", proj.period)
        proj.budget = project.get("budget", proj.budget)
        proj.status = project.get("status", proj.status)
        proj.due_date = project.get("due_date", proj.due_date)
        proj.participants = project.get("participants", proj.participants)
        proj.last_updated = datetime.now().strftime("%Y-%m-%d")

        db.commit()
        db.refresh(proj)

        proj_dict = _project_to_dict(db, proj)
        print("✏️ 과제 수정(DB):", proj_dict)
        return {"message": "과제 수정 완료", "project": proj_dict}
    except HTTPException:
        raise
    except Exception as e:
        print("❌ /projects update_project error:", repr(e))
        raise HTTPException(status_code=400, detail=f"수정 실패: {str(e)}")
    finally:
        try:
            db.close()
        except Exception:
            pass


@app.delete("/projects/{project_id}")
def delete_project(project_id: int):
    """
    과제 삭제 – projects/project_files 테이블에서 삭제.
    (실제 파일(uploads/project_{id})는 일단 그대로 두고, 필요하면 나중에 정리)
    """
    db = SessionLocal()
    try:
        proj = db.query(Project).filter(Project.id == project_id).first()
        if not proj:
            raise HTTPException(status_code=404, detail="해당 과제를 찾을 수 없습니다.")

        db.query(ProjectFile).filter(ProjectFile.project_id == project_id).delete()
        db.delete(proj)
        db.commit()
        print(f"🗑️ 과제 삭제(DB): {project_id}")
        return {"message": f"ID {project_id} 과제 삭제 완료"}
    finally:
        try:
            db.close()
        except Exception:
            pass


@app.post("/projects/{project_id}/upload")
async def upload_project_file(project_id: int, file: UploadFile = File(...)):
    """
    각 과제별 파일 업로드 – DB(project_files) + uploads/project_{id}/
    """
    db = SessionLocal()
    try:
        proj = db.query(Project).filter(Project.id == project_id).first()
        if not proj:
            raise HTTPException(status_code=404, detail="해당 과제를 찾을 수 없습니다.")

        proj_dir = os.path.join(UPLOAD_DIR, f"project_{project_id}")
        os.makedirs(proj_dir, exist_ok=True)

        file_path = os.path.join(proj_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        upload_date = datetime.now().strftime("%Y-%m-%d")
        pf = ProjectFile(
            project_id=project_id,
            filename=file.filename,
            upload_date=upload_date,
        )
        db.add(pf)
        db.commit()

        proj.last_updated = upload_date
        db.commit()

        return {"message": "파일 업로드 완료", "filename": file.filename}
    finally:
        try:
            db.close()
        except Exception:
            pass


@app.get("/projects/{project_id}/files")
def list_project_files(project_id: int):
    db = SessionLocal()
    try:
        proj = db.query(Project).filter(Project.id == project_id).first()
        if not proj:
            raise HTTPException(status_code=404, detail="해당 과제를 찾을 수 없습니다.")

        files = (
            db.query(ProjectFile)
            .filter(ProjectFile.project_id == project_id)
            .all()
        )
        return [f.filename for f in files]
    finally:
        try:
            db.close()
        except Exception:
            pass


# =========================
# DB 생성
# =========================

Base.metadata.create_all(bind=engine)
