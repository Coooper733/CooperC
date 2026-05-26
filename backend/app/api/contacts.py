"""紧急联系人 CRUD。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import current_user
from app.db import get_db
from app.models import ContactStatus, EmergencyContact, User, utcnow
from app.schemas import ContactCreateRequest, ContactOut, OkResponse

router = APIRouter(prefix="/api/v1/contacts", tags=["contacts"])

MAX_CONTACTS = 5


@router.get("", response_model=list[ContactOut])
def list_contacts(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[EmergencyContact]:
    return (
        db.query(EmergencyContact)
        .filter(
            EmergencyContact.user_id == user.id,
            EmergencyContact.status != ContactStatus.REMOVED,
        )
        .order_by(EmergencyContact.priority.asc(), EmergencyContact.id.asc())
        .all()
    )


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def create_contact(
    req: ContactCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> EmergencyContact:
    existing_count = (
        db.query(EmergencyContact)
        .filter(
            EmergencyContact.user_id == user.id,
            EmergencyContact.status != ContactStatus.REMOVED,
        )
        .count()
    )
    if existing_count >= MAX_CONTACTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Maximum {MAX_CONTACTS} contacts allowed")

    # MVP：自动确认（生产应改为对方扫码/点击邀请链接确认）
    contact = EmergencyContact(
        user_id=user.id,
        contact_phone=req.contact_phone,
        contact_name=req.contact_name,
        relation=req.relation,
        priority=req.priority,
        status=ContactStatus.ACCEPTED,
        confirmed_at=utcnow(),
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/{contact_id}", response_model=OkResponse)
def remove_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> OkResponse:
    contact = (
        db.query(EmergencyContact)
        .filter(EmergencyContact.id == contact_id, EmergencyContact.user_id == user.id)
        .first()
    )
    if not contact:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contact not found")
    contact.status = ContactStatus.REMOVED
    db.commit()
    return OkResponse(message="removed")
