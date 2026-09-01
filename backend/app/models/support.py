"""Support domain models: numbering sequences, operation audit logs.

Maps 1:1 to docs/database-design.md §6.2 - §6.3.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT as BigInteger, DATETIME

from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import PKMixin
from app.utils.enums import AuditAction


class NumberSequence(PKMixin, Base):
    """单据编号序列（§6.2，架构规则 1）

    取号用单语句 ``INSERT ... ON DUPLICATE KEY UPDATE`` + ``LAST_INSERT_ID()``，
    在唯一索引 uk_seq 上行锁，锁持有仅为单语句时长（独立短事务，不嵌套业务事务）。
    编号允许跳号（业务回滚废弃），不允许重复（UNIQUE 兜底）。
    """

    __tablename__ = "number_sequences"
    __table_args__ = (UniqueConstraint("sequence_key", "sequence_date", name="uk_seq"),)

    sequence_key: Mapped[str] = mapped_column(String(32), nullable=False, comment="PR/PO/REC/TXN/MAT/SUP/WH")
    sequence_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="按日重置用业务日期；全局递增固定 1970-01-01"
    )
    current_value: Mapped[int] = mapped_column(
        BigInteger(unsigned=True), nullable=False, server_default="0", comment="当前值"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3),
        nullable=False,
        server_default=func.current_timestamp(3),
        onupdate=func.current_timestamp(3),
    )


class OperationLog(PKMixin, Base):
    """操作审计日志（§6.3，Q15）

    只审计关键业务操作（登录 / PR 审批 / PO 确认 / 入库 / 冲销 / 权限变更），
    不做普通 CRUD 字段级 diff。
    """

    __tablename__ = "operation_logs"
    __table_args__ = (
        Index("ix_ol_operator", "operator_id"),
        Index("ix_ol_action", "action"),
        Index("ix_ol_doc", "document_type", "document_id"),
        Index("ix_ol_time", "created_at"),
    )

    operator_id: Mapped[int | None] = mapped_column(
        BigInteger(unsigned=True),
        ForeignKey("users.id", name="fk_ol_operator", ondelete="SET NULL"),
        nullable=True,
        comment="操作人（登录失败时可能为 NULL）",
    )
    username_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="账号快照")
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    module: Mapped[str] = mapped_column(String(32), nullable=False, comment="所属模块")
    document_type: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="关联单据类型")
    document_id: Mapped[int | None] = mapped_column(BigInteger(unsigned=True), nullable=True, comment="关联单据 ID")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="操作描述")
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True, comment="支持 IPv6")
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="链路追踪 ID")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
