from fastapi import APIRouter, Depends, HTTPException
from .db import get_db
from .auth import get_current_user, User

router = APIRouter()
db = get_db()


def ensure_same_scope(current: User, company_id: str, team_id: str, project_id: str):
    """
    Scope rules:
    - Owner  : global (no scope restriction)
    - Admin  : company-wide (can manage any team/project within same company)
    - Manager/Member: locked to exact (company, team, project)
    """
    roles = current.roles or []

    # 🌍 product owner → no scope checks
    if "owner" in roles:
        return

    # 🏢 admin → company-wide
    if "admin" in roles:
        if current.company_id != company_id:
            raise HTTPException(
                status_code=403,
                detail="Admins can only manage members in their own company."
            )
        return

    # 👷 manager / member → must match full project scope
    if (
        current.company_id != company_id
        or current.team_id != team_id
        or current.project_id != project_id
    ):
        raise HTTPException(
            status_code=403,
            detail="You can only manage members in your own project."
        )


@router.post("/add-member")
def add_member(
    user_id: str,
    company_id: str,
    team_id: str,
    project_id: str,
    role: str = "member",
    current: User = Depends(get_current_user),
):
    """
    Role hierarchy:

    - There is ONE product owner (seeded manually, not via this API).
    - Owner: can ONLY add admins (any company/team/project).
    - Admin: can ONLY add managers (inside their company).
    - Manager: can ONLY add members (inside their team+project).
    - Member: cannot add anyone.
    """

    ensure_same_scope(current, company_id, team_id, project_id)

    user_roles = current.roles or []
    valid_roles = ["admin", "manager", "member"]  # 'owner' cannot be created via API

    if role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Allowed: {valid_roles}")

    # 🔐 Determine what role the current user is allowed to assign
    if "owner" in user_roles:
        # Owner can ONLY add admins (anywhere)
        if role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Owner can only add admins. Admins can then add managers."
            )
        assigned_role = "admin"

    elif "admin" in user_roles:
        # Admin can ONLY add managers (any team/project inside same company)
        if role != "manager":
            raise HTTPException(
                status_code=403,
                detail="Admin can only add managers. Managers can then add members."
            )
        assigned_role = "manager"

    elif "manager" in user_roles:
        # Manager can ONLY add members (same team+project)
        if role != "member":
            raise HTTPException(
                status_code=403,
                detail="Manager can only add members."
            )
        assigned_role = "member"

    else:
        raise HTTPException(
            status_code=403,
            detail="Only owner, admins, or managers can add members."
        )

    # ❗ NEW CHECK — ensure user *actually exists* before adding role
    user_exists = db.users.find_one({"user_id": user_id})
    if not user_exists:
        raise HTTPException(
            status_code=404,
            detail=f"User '{user_id}' does NOT exist. They must /signup first."
        )

    # Avoid duplicate membership in same scope
    if db.memberships.find_one({
        "user_id": user_id,
        "company_id": company_id,
        "team_id": team_id,
        "project_id": project_id
    }):
        raise HTTPException(status_code=400, detail="This user is already a member of this project.")

    db.memberships.insert_one({
        "user_id": user_id,
        "company_id": company_id,
        "team_id": team_id,
        "project_id": project_id,
        "role": assigned_role
    })

    return {"status": "ok", "message": f"Member added as {assigned_role}"}


@router.delete("/remove-member")
def remove_member(
    user_id: str,
    company_id: str,
    team_id: str,
    project_id: str,
    current: User = Depends(get_current_user),
):
    """
    Role hierarchy for removal:

    - Owner: can remove admins (any company/team/project).
    - Admin: can remove managers (inside their company).
    - Manager: can remove members (inside their project).
    - Cannot remove owner (owner is permanent / created only by seed).
    """

    ensure_same_scope(current, company_id, team_id, project_id)

    user_roles = current.roles or []

    if not any(r in user_roles for r in ["owner", "admin", "manager"]):
        raise HTTPException(
            status_code=403,
            detail="Only owner, admins, or managers can remove members."
        )

    target = db.memberships.find_one({
        "user_id": user_id,
        "company_id": company_id,
        "team_id": team_id,
        "project_id": project_id,
    })

    if not target:
        raise HTTPException(status_code=404, detail="Membership not found for this user in this project.")

    target_role = target.get("role")

    # ⛔ Cannot remove owner via API
    if target_role == "owner":
        raise HTTPException(
            status_code=403,
            detail="Owner cannot be removed via this API."
        )

    # Removal rules
    if "owner" in user_roles:
        if target_role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Owner can only remove admins."
            )

    elif "admin" in user_roles:
        if target_role != "manager":
            raise HTTPException(
                status_code=403,
                detail="Admin can only remove managers."
            )

    elif "manager" in user_roles:
        if target_role != "member":
            raise HTTPException(
                status_code=403,
                detail="Manager can only remove members."
            )

    db.memberships.delete_one({
        "user_id": user_id,
        "company_id": company_id,
        "team_id": team_id,
        "project_id": project_id,
    })

    return {"status": "ok", "message": f"Removed {user_id} from project {project_id}."}
