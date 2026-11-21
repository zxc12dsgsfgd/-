import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_session, digest, get_db, now
from app.models import Card, Draft, Share, ShareComment, ShareItem
from app.rate_limit import check_limit

router = APIRouter(prefix='/api/v1', tags=['shares'])
def limit_public(request: Request, db: Session = Depends(get_db)):
    check_limit(request, db, "share", 60)


class ShareIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    card_ids: list[int] = Field(default_factory=list, max_length=50)
    draft_id: int | None = Field(default=None, ge=1)
    expires_days: int = Field(ge=1, le=365)
    allow_comments: bool = False

    @model_validator(mode='after')
    def selection(self):
        if bool(self.card_ids) == bool(self.draft_id) or any(i < 1 for i in self.card_ids) or len(set(self.card_ids)) != len(self.card_ids):
            raise ValueError('请选择卡片或单个草稿，卡片编号不能重复')
        return self


class CommentIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    share_item_id: int = Field(ge=1)
    author_name: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=5000)


class CommentUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    handled: bool


def owner_share(share_id, owner, db, lock=False):
    stmt = select(Share).where(Share.id == share_id, Share.owner_id == owner)
    share = db.scalar(stmt.with_for_update() if lock else stmt)
    if not share:
        raise HTTPException(404, '分享不存在')
    return share


def public_share(token, db, lock=False):
    if not token or len(token) != 43 or not all(c.isascii() and (c.isalnum() or c in '-_') for c in token):
        raise HTTPException(404, '分享不可用')
    stmt = select(Share).where(Share.token_hash == digest(token))
    share = db.scalar(stmt.with_for_update() if lock else stmt)
    if not share or share.revoked_at or share.expires_at <= now():
        raise HTTPException(404, '分享不可用')
    return share


@router.post('/shares', status_code=201)
def create_share(data: ShareIn, current=Depends(current_session), db: Session = Depends(get_db)):
    owner = current[1].id
    if data.draft_id:
        draft = db.scalar(select(Draft).where(Draft.id == data.draft_id, Draft.owner_id == owner))
        if not draft:
            raise HTTPException(404, '材料不存在')
        snapshots = [('draft', {'title': draft.title, 'content': draft.content})]
    else:
        cards = db.scalars(select(Card).where(Card.owner_id == owner, Card.deleted_at.is_(None), Card.id.in_(data.card_ids))).all()
        if len(cards) != len(data.card_ids):
            raise HTTPException(404, '材料不存在')
        cards_by_id = {c.id: c for c in cards}
        snapshots = [('card', {'title': c.title, 'content': c.content, 'type': c.type, 'source_title': c.source_title_snapshot, 'source_page': c.source_page, 'source_excerpt': c.source_excerpt, 'note': c.note}) for c in (cards_by_id[i] for i in data.card_ids)]
    token = secrets.token_urlsafe(32)
    share = Share(owner_id=owner, token_hash=digest(token), expires_at=now() + timedelta(days=data.expires_days), allow_comments=data.allow_comments)
    db.add(share); db.flush()
    db.add_all([ShareItem(share_id=share.id, item_type=kind, snapshot=snapshot) for kind, snapshot in snapshots])
    db.commit()
    return {'id': share.id, 'token': token, 'expires_at': share.expires_at.isoformat() + 'Z'}


@router.get('/shares')
def list_shares(current=Depends(current_session), db: Session = Depends(get_db)):
    shares = db.scalars(select(Share).where(Share.owner_id == current[1].id).order_by(Share.id.desc()).limit(100)).all()
    return [{'id': s.id, 'expires_at': s.expires_at.isoformat() + 'Z', 'revoked_at': s.revoked_at.isoformat() + 'Z' if s.revoked_at else None, 'allow_comments': s.allow_comments} for s in shares]


@router.post('/shares/{share_id}/revoke', status_code=204)
def revoke(share_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    share = owner_share(share_id, current[1].id, db, lock=True)
    if not share.revoked_at:
        share.revoked_at = now(); db.commit()
    return Response(status_code=204)


@router.get('/public/shares', dependencies=[Depends(limit_public)])
def read_share(response: Response, token: str | None = Header(default=None, alias='X-Share-Token'), db: Session = Depends(get_db)):
    share = public_share(token, db)
    items = db.scalars(select(ShareItem).where(ShareItem.share_id == share.id).order_by(ShareItem.id)).all()
    response.headers['Cache-Control'] = 'no-store'
    return {'allow_comments': share.allow_comments, 'items': [{'id': item.id, 'type': item.item_type, 'snapshot': item.snapshot} for item in items]}


@router.post('/public/shares/comments', status_code=201, dependencies=[Depends(limit_public)])
def create_comment(data: CommentIn, token: str | None = Header(default=None, alias='X-Share-Token'), db: Session = Depends(get_db)):
    share = public_share(token, db, lock=True)
    if not share.allow_comments:
        raise HTTPException(403, '此分享不允许批注')
    item = db.scalar(select(ShareItem).where(ShareItem.id == data.share_item_id, ShareItem.share_id == share.id))
    if not item:
        raise HTTPException(404, '分享内容不存在')
    comment = ShareComment(share_id=share.id, share_item_id=item.id, author_name=data.author_name, content=data.content)
    db.add(comment); db.commit(); db.refresh(comment)
    return {'id': comment.id, 'created_at': comment.created_at.isoformat() + 'Z'}


@router.get('/shares/{share_id}/comments')
def comments(share_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    owner_share(share_id, current[1].id, db)
    rows = db.scalars(select(ShareComment).where(ShareComment.share_id == share_id).order_by(ShareComment.id.desc()).limit(500)).all()
    return [{'id': c.id, 'share_item_id': c.share_item_id, 'author_name': c.author_name, 'content': c.content, 'created_at': c.created_at.isoformat() + 'Z', 'handled_at': c.handled_at.isoformat() + 'Z' if c.handled_at else None} for c in rows]


@router.patch('/shares/{share_id}/comments/{comment_id}')
def handle_comment(share_id: int, comment_id: int, data: CommentUpdate, current=Depends(current_session), db: Session = Depends(get_db)):
    owner_share(share_id, current[1].id, db)
    comment = db.scalar(select(ShareComment).where(ShareComment.id == comment_id, ShareComment.share_id == share_id))
    if not comment:
        raise HTTPException(404, '批注不存在')
    comment.handled_at = now() if data.handled else None
    db.commit()
    return {'id': comment.id, 'handled': data.handled}
