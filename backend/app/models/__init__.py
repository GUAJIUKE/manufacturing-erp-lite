"""Model registry.

Importing this package imports every model so that ``Base.metadata`` is fully
populated before Alembic autogenerate or ``create_all`` runs.
"""

from app.models.masterdata import (
    InventoryPolicy,
    Material,
    Supplier,
    Warehouse,
)
from app.models.inventory import (
    InventoryBalance,
    InventoryTransaction,
    PurchaseReceipt,
    PurchaseReceiptItem,
)
from app.models.purchase import (
    ApprovalRecord,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemSource,
    PurchaseRequisition,
    PurchaseRequisitionItem,
)
from app.models.reconciliation import StockReconciliation, StockReconciliationItem
from app.models.support import NumberSequence, OperationLog
from app.models.system import (
    Department,
    DepartmentManager,
    Permission,
    Role,
    RolePermission,
    User,
)

__all__ = [
    "ApprovalRecord",
    "Department",
    "DepartmentManager",
    "InventoryBalance",
    "InventoryPolicy",
    "InventoryTransaction",
    "Material",
    "NumberSequence",
    "OperationLog",
    "Permission",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "PurchaseOrderItemSource",
    "PurchaseReceipt",
    "PurchaseReceiptItem",
    "PurchaseRequisition",
    "PurchaseRequisitionItem",
    "Role",
    "RolePermission",
    "StockReconciliation",
    "StockReconciliationItem",
    "Supplier",
    "User",
    "Warehouse",
]
