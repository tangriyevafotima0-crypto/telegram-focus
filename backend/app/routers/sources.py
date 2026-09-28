from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Source
from ..schemas import SourceCreate, SourceOut, SourceUpdate


router = APIRouter(prefix="/api/sources", tags=["sources"])


def normalize_identifier(value: str) -> str:
    return value.strip().lstrip("@").casefold()


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreate,
    db: AsyncSession = Depends(get_db),
) -> Source:
    normalized = normalize_identifier(payload.identifier)
    existing = await db.execute(select(Source).where(Source.kind == "telegram"))
    if any(normalize_identifier(item.identifier) == normalized for item in existing.scalars()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu manba allaqachon qo‘shilgan.",
        )

    source = Source(
        identifier=payload.identifier,
        display_name=payload.display_name or payload.identifier,
        type=payload.type,
        is_active=True,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


@router.get("", response_model=list[SourceOut])
async def list_sources(db: AsyncSession = Depends(get_db)) -> list[Source]:
    result = await db.execute(
        select(Source).where(Source.kind == "telegram").order_by(Source.created_at.desc())
    )
    return list(result.scalars().all())


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: int,
    payload: SourceUpdate,
    db: AsyncSession = Depends(get_db),
) -> Source:
    source = await db.get(Source, source_id)
    if source is None or source.kind != "telegram":
        raise HTTPException(status_code=404, detail="Manba topilmadi.")

    updates = payload.model_dump(exclude_unset=True)
    if "display_name" in updates:
        if not updates["display_name"]:
            raise HTTPException(status_code=422, detail="Nomi bo‘sh bo‘lishi mumkin emas.")
        source.display_name = updates["display_name"].strip()
    if "is_active" in updates:
        source.is_active = updates["is_active"]
    await db.commit()
    await db.refresh(source)
    return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    source = await db.get(Source, source_id)
    if source is None or source.kind != "telegram":
        raise HTTPException(status_code=404, detail="Manba topilmadi.")
    await db.delete(source)
    await db.commit()