"""
Admin router — User Management + RBAC (Roles & Menus)

Endpoints:
  Menus     : GET/POST /admin/menus, PUT/DELETE /admin/menus/{id}
  Roles     : GET/POST /admin/roles, PUT/DELETE /admin/roles/{id}
              POST /admin/roles/{id}/menus        — assign menus to role
              DELETE /admin/roles/{id}/menus/{mid} — remove menu from role
  Users     : GET /admin/users, GET/PUT /admin/users/{id}
              POST /admin/users/{id}/activate
              POST /admin/users/{id}/deactivate
              POST /admin/users/{id}/change-password
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Menu, Role, RoleMenu, User
from app.models.schemas import (
    MenuCreate, MenuUpdate, MenuResponse, MenuTreeResponse,
    RoleCreate, RoleUpdate, RoleResponse, RoleMenuAssign, RoleMenuResponse,
    UserDetailResponse, UserListResponse, UserUpdateRequest,
    ChangePasswordRequest, RoleMinimalResponse, ZoneMinimalResponse,
    DivisionMinimalResponse,
)
from app.auth_utils import hash_password, verify_password
from app.rbac_defaults import ensure_default_menus

router = APIRouter(prefix="/admin", tags=["Admin — User Management & RBAC"])


# ── Helper ────────────────────────────────────────────────────────────────────

def _build_user_detail(user: User) -> UserDetailResponse:
    role_menus = []
    if user.role:
        role_menus = [
            RoleMenuResponse(
                menu_id=rm.menu_id,
                menu_name=rm.menu.name,
                menu_slug=rm.menu.slug,
                parent_slug=rm.menu.parent_slug,
                permission=rm.permission,
            )
            for rm in user.role.role_menus
            if rm.menu.is_active
        ]
    return UserDetailResponse(
        id=user.id,
        full_name=user.full_name,
        employee_id=user.employee_id,
        designation=user.designation,
        role_id=user.role_id,
        role_name=user.role.name if user.role else None,
        role_display_name=user.role.display_name if user.role else None,
        zone_id=user.zone_id,
        division_id=user.division_id,
        mobile_number=user.mobile_number,
        email=user.email,
        reporting_officer_id=user.reporting_officer_id,
        is_active=user.is_active,
        created_at=user.created_at,
        menus=role_menus,
        role=RoleMinimalResponse.model_validate(user.role) if user.role else None,
        zone=ZoneMinimalResponse.model_validate(user.zone) if user.zone else None,
        division=DivisionMinimalResponse.model_validate(user.division) if user.division else None,
    )


def _build_menu_tree(menus: List[Menu]) -> List[MenuTreeResponse]:
    children_by_parent: dict[str, list[Menu]] = {}
    roots: list[Menu] = []

    for menu in menus:
        if menu.parent_slug:
            children_by_parent.setdefault(menu.parent_slug, []).append(menu)
        else:
            roots.append(menu)

    def sort_key(menu: Menu):
        return (menu.sort_order or 0, menu.name)

    def as_node(menu: Menu) -> MenuTreeResponse:
        children = sorted(children_by_parent.get(menu.slug, []), key=sort_key)
        return MenuTreeResponse(
            id=menu.id,
            label=menu.name,
            icon=menu.icon,
            sort_order=menu.sort_order or 0,
            roles=menu.roles,
            href=None if children else menu.href,
            children=[as_node(child) for child in children],
        )

    return [as_node(menu) for menu in sorted(roots, key=sort_key)]


# ── Menus ─────────────────────────────────────────────────────────────────────

@router.get("/menus", response_model=List[MenuResponse])
def list_menus(
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
):
    """List all menu items. Used to populate the menu assignment screen."""
    q = db.query(Menu)
    if not include_inactive:
        q = q.filter(Menu.is_active == True)
    return q.order_by(Menu.sort_order, Menu.name).all()


@router.get("/menus/tree", response_model=List[MenuTreeResponse], response_model_exclude_none=True)
def list_menu_tree(
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
):
    """List menu items in the nested shape used by the frontend sidebar and role UI."""
    q = db.query(Menu)
    if not include_inactive:
        q = q.filter(Menu.is_active == True)
    menus = q.order_by(Menu.sort_order, Menu.name).all()
    return _build_menu_tree(menus)


@router.post("/menus/seed", response_model=List[MenuResponse])
def seed_default_menus(db: Session = Depends(get_db)):
    """Create or update the default RDPMS menu master records."""
    ensure_default_menus(db)
    return db.query(Menu).filter(Menu.is_active == True).order_by(Menu.sort_order, Menu.name).all()


@router.post("/menus", response_model=MenuResponse, status_code=status.HTTP_201_CREATED)
def create_menu(payload: MenuCreate, db: Session = Depends(get_db)):
    """Create a new menu item."""
    if db.query(Menu).filter(Menu.slug == payload.slug).first():
        raise HTTPException(status_code=409, detail=f"Menu slug '{payload.slug}' already exists")
    menu = Menu(**payload.model_dump())
    db.add(menu)
    db.commit()
    db.refresh(menu)
    return menu


@router.put("/menus/{menu_id}", response_model=MenuResponse)
def update_menu(menu_id: int, payload: MenuUpdate, db: Session = Depends(get_db)):
    """Update a menu item."""
    menu = db.query(Menu).filter(Menu.id == menu_id).first()
    if not menu:
        raise HTTPException(status_code=404, detail=f"Menu {menu_id} not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(menu, field, value)
    db.commit()
    db.refresh(menu)
    return menu


@router.delete("/menus/{menu_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_menu(menu_id: int, db: Session = Depends(get_db)):
    """Delete a menu item."""
    menu = db.query(Menu).filter(Menu.id == menu_id).first()
    if not menu:
        raise HTTPException(status_code=404, detail=f"Menu {menu_id} not found")
    db.delete(menu)
    db.commit()


# ── Roles ─────────────────────────────────────────────────────────────────────

@router.get("/roles", response_model=List[RoleResponse], response_model_exclude_none=True)
def list_roles(db: Session = Depends(get_db)):
    """List all roles with their assigned menus."""
    return db.query(Role).order_by(Role.level).all()


@router.get("/roles/{role_id}", response_model=RoleResponse, response_model_exclude_none=True)
def get_role(role_id: int, db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role {role_id} not found")
    return role


@router.post("/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED, response_model_exclude_none=True)
def create_role(payload: RoleCreate, db: Session = Depends(get_db)):
    """
    Create a role and optionally assign menus in one call.

    Example:
    {
      "name": "JE",
      "display_name": "Junior Engineer",
      "level": 2,
      "menus": [
        {"menu_id": 1, "permission": "view"},
        {"menu_id": 3, "permission": "edit"}
      ]
    }
    """
    if db.query(Role).filter(Role.name == payload.name).first():
        raise HTTPException(status_code=409, detail=f"Role '{payload.name}' already exists")

    role_data = payload.model_dump(exclude={"menus"})
    role = Role(**role_data)
    db.add(role)
    db.flush()

    for menu_assign in (payload.menus or []):
        menu = db.query(Menu).filter(Menu.id == menu_assign.menu_id).first()
        if not menu:
            raise HTTPException(status_code=404, detail=f"Menu {menu_assign.menu_id} not found")
        role.role_menus.append(RoleMenu(
            menu_id=menu_assign.menu_id,
            permission=menu_assign.permission,
        ))

    db.commit()
    db.expire(role, ["role_menus"])
    db.refresh(role)
    return role


@router.put("/roles/{role_id}", response_model=RoleResponse, response_model_exclude_none=True)
def update_role(role_id: int, payload: RoleUpdate, db: Session = Depends(get_db)):
    """Update role details (not menus — use the menu assignment endpoints for that)."""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role {role_id} not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(role, field, value)
    db.commit()
    db.expire(role, ["role_menus"])
    db.refresh(role)
    return role


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_id: int, db: Session = Depends(get_db)):
    """Delete a role. Users with this role will have role_id set to null."""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role {role_id} not found")
    # Unlink users before deleting
    db.query(User).filter(User.role_id == role_id).update({"role_id": None})
    db.delete(role)
    db.commit()


@router.post("/roles/{role_id}/menus", response_model=RoleResponse, response_model_exclude_none=True)
def assign_menus_to_role(
    role_id: int,
    payload: List[RoleMenuAssign],
    db: Session = Depends(get_db),
):
    """
    Assign (or update) menus for a role.
    Replaces all existing menu assignments with the new list.

    Send empty list [] to remove all menus from a role.
    """
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role {role_id} not found")

    # Validate all menu_ids first
    for item in payload:
        if not db.query(Menu).filter(Menu.id == item.menu_id).first():
            raise HTTPException(status_code=404, detail=f"Menu {item.menu_id} not found")

    # Replace all assignments using collection directly
    role.role_menus.clear()
    for item in payload:
        role.role_menus.append(RoleMenu(
            menu_id=item.menu_id,
            permission=item.permission,
        ))

    db.commit()
    db.expire(role, ["role_menus"])
    db.refresh(role)
    return role


@router.delete("/roles/{role_id}/menus/{menu_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_menu_from_role(role_id: int, menu_id: int, db: Session = Depends(get_db)):
    """Remove a single menu from a role."""
    rm = db.query(RoleMenu).filter(
        RoleMenu.role_id == role_id,
        RoleMenu.menu_id == menu_id,
    ).first()
    if not rm:
        raise HTTPException(status_code=404, detail="Menu not assigned to this role")
    db.delete(rm)
    db.commit()


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=UserListResponse)
def list_users(
    zone_id: Optional[int] = Query(None),
    division_id: Optional[int] = Query(None),
    role_id: Optional[int] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, description="Search by name or employee_id"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List all users with filters. Used by the User Management screen."""
    q = db.query(User)
    if zone_id is not None:
        q = q.filter(User.zone_id == zone_id)
    if division_id is not None:
        q = q.filter(User.division_id == division_id)
    if role_id is not None:
        q = q.filter(User.role_id == role_id)
    if is_active is not None:
        q = q.filter(User.is_active == is_active)
    if search:
        q = q.filter(
            User.full_name.ilike(f"%{search}%") |
            User.employee_id.ilike(f"%{search}%")
        )

    total = q.count()
    total_pages = (total + page_size - 1) // page_size if total else 0
    offset = (page - 1) * page_size
    users = q.order_by(User.full_name).offset(offset).limit(page_size).all()

    return UserListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        rows=[_build_user_detail(u) for u in users],
    )


@router.get("/users/{user_id}", response_model=UserDetailResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    """Get a single user with their role and menu permissions."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return _build_user_detail(user)


@router.put("/users/{user_id}", response_model=UserDetailResponse)
def update_user(user_id: int, payload: UserUpdateRequest, db: Session = Depends(get_db)):
    """
    Update user details including role assignment.
    This is how Admin assigns a role to a user.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    data = payload.model_dump(exclude_unset=True)

    if "role_id" in data and data["role_id"] is not None:
        if not db.query(Role).filter(Role.id == data["role_id"]).first():
            raise HTTPException(status_code=404, detail=f"Role {data['role_id']} not found")

    if "email" in data and data["email"] != user.email:
        if db.query(User).filter(User.email == data["email"]).first():
            raise HTTPException(status_code=409, detail="Email already in use")

    for field, value in data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return _build_user_detail(user)


@router.post("/users/{user_id}/activate", response_model=UserDetailResponse)
def activate_user(user_id: int, db: Session = Depends(get_db)):
    """Activate a deactivated user account."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    user.is_active = True
    db.commit()
    db.refresh(user)
    return _build_user_detail(user)


@router.post("/users/{user_id}/deactivate", response_model=UserDetailResponse)
def deactivate_user(user_id: int, db: Session = Depends(get_db)):
    """Deactivate a user account (soft delete)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    user.is_active = False
    db.commit()
    db.refresh(user)
    return _build_user_detail(user)


@router.post("/users/{user_id}/change-password", response_model=UserDetailResponse)
def change_password(
    user_id: int,
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
):
    """Change a user's password. Requires current password verification."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(status_code=400, detail="New passwords do not match")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    db.refresh(user)
    return _build_user_detail(user)
