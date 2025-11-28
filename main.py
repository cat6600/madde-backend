from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, Float
from typing import List, Optional, Dict
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import shutil, os, re

app = FastAPI()

# ✅ CORS 설정
#   - 지금은 편의를 위해 모든 origin 허용 ("*")
#   - 보안 강화하려면 나중에 정확한 도메인만 남겨두면 됨.
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ 업로드 폴더 설정
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# IR 전용 폴더 (uploads/ir)
IR_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "ir")
os.makedirs(IR_UPLOAD_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/project_uploads", StaticFiles(directory=UPLOAD_DIR), name="project_uploads")

# ✅ 데이터베이스 설정
DATABASE_URL = "sqlite:///./madde.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
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
    shares = Column(Integer)           # 주식수
    amount = Column(Integer)           # 투자금 (원 또는 천원 단위)
    investor = Column(String)          # 투자사
    security_type = Column(String)     # 종류 (RCPS, 보통주 등)


# =========================
# 2. 로그인 (내부용 간단 로그인)
# =========================

ADMIN_PASSWORD = "madde-admin"
VIEWER_PASSWORD = "madde-viewer"

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    """
    매우 단순한 내부용 로그인:
    - username: "admin" 또는 "viewer" (프론트에서 role로 보냄)
    - password:
        admin  → madde-admin
        viewer → madde-viewer
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

    # 파일이 있는 경우에만 저장 처리
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


# =========================
# 4. IP 데이터 관리
# =========================

@app.get("/ip")
def get_ip():
    db = SessionLocal()
    data = db.query(IP).all()
    db.close()
    return data


@app.post("/ip")
def add_ip(
    title: str = Form(...),
    number: str = Form(...),
    apply_date: str = Form(...),
    reg_date: str = Form(...),
    inventors: str = Form(...),
    status: str = Form(...),
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
        db.delete(ip)
        db.commit()
        return {"message": "IP 삭제 완료 ✅"}
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
    file: UploadFile = File(...),
    category: str = Form("IR"),
    folder: Optional[str] = Form(None),
):
    original_name = file.filename
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename)
    stored_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}"

    base_dir = IR_UPLOAD_DIR
    if folder:
        base_dir = os.path.join(IR_UPLOAD_DIR, folder)
    os.makedirs(base_dir, exist_ok=True)

    file_path = os.path.join(base_dir, stored_name)
    with open(file_path, "wb") as b:
        shutil.copyfileobj(file.file, b)

    file_size = os.path.getsize(file_path)
    upload_date = datetime.now().strftime("%Y-%m-%d")

    db = SessionLocal()
    try:
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
        return {
            "message": "IR 자료 업로드 완료 ✅",
            "id": ir.id,
            "original_name": ir.original_name,
            "stored_name": ir.stored_name,
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


def get_active_project_titles():
    active_status = {"진행중", "신청완료"}
    titles = [
        p["title"]
        for p in PROJECTS
        if p.get("status") in active_status
    ]
    return list(dict.fromkeys(titles))


@app.get("/assets")
def get_assets():
    db = SessionLocal()
    try:
        people = db.query(Personnel).all()
        person_shares = db.query(PersonnelProjectShare).all()
        equipments = db.query(Equipment).all()
        equip_shares = db.query(EquipmentProjectShare).all()
    finally:
        db.close()

    active_projects = get_active_project_titles()

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


# =========================
# 7. 재무 / 투자 현황
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
    contract_date: str = Form(...),
    registration_date: str = Form(...),
    shares: int = Form(...),
    amount: int = Form(...),
    investor: str = Form(...),
    security_type: str = Form(...),
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
# 8. 과제 데이터 (임시, 메모리 기반)
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


PROJECTS = [
    {
        "id": 1,
        "title": "고성능 세라믹 소재 개발",
        "organization": "산업통상자원부",
        "type": "R&D",
        "period": "2024-01-01 ~ 2026-12-31",
        "budget": 15.0,
        "status": "진행중",
        "due_date": "2024-01-10",
        "participants": "김철수, 박민수, 이영희",
        "files": ["세라믹_계획서.pdf"],
        "last_updated": "2025-11-27",
    },
    {
        "id": 2,
        "title": "신제품 사업화 지원",
        "organization": "중소벤처기업부",
        "type": "사업화",
        "period": "2024-07-01 ~ 2025-06-30",
        "budget": 5.0,
        "status": "신청예정",
        "due_date": "2024-06-01",
        "participants": "이영희, 정다운",
        "files": [],
        "last_updated": "2025-11-20",
    },
]


@app.get("/projects")
def get_projects():
    return PROJECTS


@app.post("/projects")
def add_project(project: dict = Body(...)):
    try:
        new_id = max(p["id"] for p in PROJECTS) + 1 if PROJECTS else 1
        new_proj = project
        new_proj["id"] = new_id
        new_proj["files"] = []
        new_proj["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        PROJECTS.append(new_proj)
        print("✅ 새 과제 등록:", new_proj)
        return {"message": "과제 등록 완료", "project": new_proj}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"등록 실패: {str(e)}")


@app.put("/projects/{project_id}")
def update_project(project_id: int, project: dict = Body(...)):
    for p in PROJECTS:
        if p["id"] == project_id:
            p.update(project)
            p["last_updated"] = datetime.now().strftime("%Y-%m-%d")
            return {"message": "과제 수정 완료", "project": p}
    raise HTTPException(status_code=404, detail="해당 과제를 찾을 수 없습니다.")


@app.delete("/projects/{project_id}")
def delete_project(project_id: int):
    global PROJECTS
    before = len(PROJECTS)
    PROJECTS = [p for p in PROJECTS if p["id"] != project_id]
    if len(PROJECTS) < before:
        return {"message": f"ID {project_id} 과제 삭제 완료"}
    raise HTTPException(status_code=404, detail="해당 과제를 찾을 수 없습니다.")


@app.post("/projects/{project_id}/upload")
async def upload_project_file(project_id: int, file: UploadFile = File(...)):
    project = next((p for p in PROJECTS if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="해당 과제를 찾을 수 없습니다.")

    proj_dir = os.path.join(UPLOAD_DIR, f"project_{project_id}")
    os.makedirs(proj_dir, exist_ok=True)

    file_path = os.path.join(proj_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    project["files"].append(file.filename)
    project["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    return {"message": "파일 업로드 완료", "filename": file.filename}


@app.get("/projects/{project_id}/files")
def list_project_files(project_id: int):
    project = next((p for p in PROJECTS if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="해당 과제를 찾을 수 없습니다.")
    return project["files"]


Base.metadata.create_all(bind=engine)
