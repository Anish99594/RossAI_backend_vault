# access.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from .db import SessionLocal
from .auth import get_current_user, User

router = APIRouter()


def ensure_same_scope(current: User, company_id: str, team_id: str, project_id: str):
    """Ensure current user is operating inside their own project scope."""
    if (
        current.company_id != company_id
        or current.team_id != team_id
        or current.project_id != project_id
    ):
        raise HTTPException(status_code=403, detail="You can only manage members in your own project.")


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
    Role hierarchy: Owner → Admin → Manager → Member
    
    Rules:
    - Owner: can ONLY add 'admin' (and only one owner per project)
    - Admin: can ONLY add 'manager'
    - Manager: can ONLY add 'member'
    - Member: cannot add anyone
    """

    ensure_same_scope(current, company_id, team_id, project_id)

    session = SessionLocal()

    valid_roles = ["owner", "admin", "manager", "member"]
    if role not in valid_roles:
        session.close()
        raise HTTPException(status_code=400, detail=f"Invalid role. Allowed: {valid_roles}")

    user_roles = current.roles or []

    # Determine what role the current user can assign
    if "owner" in user_roles:
        # Owner can ONLY add admins
        if role != "admin":
            session.close()
            raise HTTPException(
                status_code=403, 
                detail="Owner can only add admins. Admins can then add managers."
            )
        assigned_role = "admin"
        
        # Check if there's already an owner for this project
        existing_owner = session.execute(
            text("""
                SELECT 1 FROM memberships
                WHERE company_id = :company_id
                  AND team_id = :team_id
                  AND project_id = :project_id
                  AND role = 'owner'
            """),
            {
                "company_id": company_id,
                "team_id": team_id,
                "project_id": project_id,
            }
        ).fetchone()
        
        if existing_owner:
            session.close()
            raise HTTPException(
                status_code=400,
                detail="There can only be one owner per project. An owner already exists."
            )
            
    elif "admin" in user_roles:
        # Admin can ONLY add managers
        if role != "manager":
            session.close()
            raise HTTPException(
                status_code=403,
                detail="Admin can only add managers. Managers can then add members."
            )
        assigned_role = "manager"
        
    elif "manager" in user_roles:
        # Manager can ONLY add members
        if role != "member":
            session.close()
            raise HTTPException(
                status_code=403,
                detail="Manager can only add members."
            )
        assigned_role = "member"
    else:
        session.close()
        raise HTTPException(
            status_code=403, 
            detail="Only owner, admins, or managers can add members."
        )

    # avoid duplicate membership
    existing = session.execute(
        text("""
            SELECT 1 FROM memberships
            WHERE user_id = :user_id
              AND company_id = :company_id
              AND team_id = :team_id
              AND project_id = :project_id
        """),
        {
            "user_id": user_id,
            "company_id": company_id,
            "team_id": team_id,
            "project_id": project_id,
        }
    ).fetchone()

    if existing:
        session.close()
        raise HTTPException(status_code=400, detail="This user is already a member of this project.")

    session.execute(
        text("""
            INSERT INTO memberships (user_id, company_id, team_id, project_id, role)
            VALUES (:user_id, :company_id, :team_id, :project_id, :role)
        """),
        {
            "user_id": user_id,
            "company_id": company_id,
            "team_id": team_id,
            "project_id": project_id,
            "role": assigned_role,
        },
    )

    session.commit()
    session.close()

    return {
        "status": "ok",
        "message": f"Member added as {assigned_role}",
    }


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
    
    Rules:
    - Owner: can remove admins
    - Admin: can remove managers
    - Manager: can remove members
    - Cannot remove owner (owner is permanent)
    """

    ensure_same_scope(current, company_id, team_id, project_id)

    session = SessionLocal()
    user_roles = current.roles or []

    if "owner" not in user_roles and "admin" not in user_roles and "manager" not in user_roles:
        session.close()
        raise HTTPException(
            status_code=403, 
            detail="Only owner, admins, or managers can remove members."
        )

    # find target membership
    target = session.execute(
        text("""
            SELECT role
            FROM memberships
            WHERE user_id   = :user_id
              AND company_id = :company_id
              AND team_id    = :team_id
              AND project_id = :project_id
        """),
        {
            "user_id": user_id,
            "company_id": company_id,
            "team_id": team_id,
            "project_id": project_id,
        }
    ).mappings().fetchone()

    if not target:
        session.close()
        raise HTTPException(status_code=404, detail="Membership not found for this user in this project.")

    target_role = target["role"]

    # Cannot remove owner
    if target_role == "owner":
        session.close()
        raise HTTPException(
            status_code=403, 
            detail="Owner cannot be removed. Owner is permanent."
        )

    # Owner can remove admins
    if "owner" in user_roles:
        if target_role != "admin":
            session.close()
            raise HTTPException(
                status_code=403, 
                detail="Owner can only remove admins."
            )
    
    # Admin can remove managers
    elif "admin" in user_roles:
        if target_role != "manager":
            session.close()
            raise HTTPException(
                status_code=403, 
                detail="Admin can only remove managers."
            )
    
    # Manager can remove only members
    elif "manager" in user_roles:
        if target_role != "member":
            session.close()
            raise HTTPException(
                status_code=403, 
                detail="Manager can only remove members."
            )

    # perform delete
    session.execute(
        text("""
            DELETE FROM memberships
            WHERE user_id   = :user_id
              AND company_id = :company_id
              AND team_id    = :team_id
              AND project_id = :project_id
        """),
        {
            "user_id": user_id,
            "company_id": company_id,
            "team_id": team_id,
            "project_id": project_id,
        }
    )

    session.commit()
    session.close()

    return {"status": "ok", "message": f"Removed {user_id} from project {project_id}."}
