"""Table de jointure many-to-many entre User et Role."""

from sqlmodel import Field, SQLModel


class UserRoleLink(SQLModel, table=True):
    """Association User-Role avec cle primaire composite."""

    __tablename__ = "user_role_link"
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    role_id: int = Field(foreign_key="role.id", primary_key=True)
