"""Schemas de request/response para autenticação."""
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=1)
    senha: str = Field(min_length=1)


class LoginResponse(BaseModel):
    user_name: str
    user_email: str
    senha_temporaria: bool = False


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    senha_atual: str = Field(min_length=1)
    nova_senha: str = Field(min_length=1)


class CondominioSelection(BaseModel):
    codigo: int
    nome: str
