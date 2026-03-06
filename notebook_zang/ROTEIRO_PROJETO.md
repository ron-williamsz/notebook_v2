# Notebook Zang - Roteiro de Recriação do Projeto

## Visão Geral

Plataforma estilo NotebookLM com **Skills customizáveis** criadas por administradores.
Cada Skill define um roteiro de análise que o LLM executa sobre dados vindos de **uploads** ou da **API GoSATI**.

---

## 1. Estrutura de Diretórios

```
notebook_zang/
├── app/
│   ├── core/                          # Configuração e utilitários
│   │   ├── __init__.py
│   │   ├── config.py                  # Settings (pydantic-settings, .env)
│   │   ├── auth.py                    # Autenticação GCP (gcloud token)
│   │   ├── exceptions.py             # Exceções customizadas
│   │   ├── exception_handlers.py     # Middleware de exceções FastAPI
│   │   └── http_client.py            # httpx.AsyncClient global
│   │
│   ├── models/                        # Modelos de banco (SQLAlchemy/SQLModel)
│   │   ├── __init__.py
│   │   ├── base.py                    # Base declarativa + engine
│   │   ├── skill.py                   # Skill, SkillStep, SkillExample
│   │   ├── session.py                 # Session (notebook do usuário)
│   │   └── source.py                 # Source (arquivo/dado carregado)
│   │
│   ├── schemas/                       # Pydantic schemas (request/response)
│   │   ├── __init__.py
│   │   ├── skill.py                   # SkillCreate, SkillUpdate, SkillResponse
│   │   ├── session.py                 # SessionCreate, SessionResponse
│   │   ├── source.py                 # SourceUpload, SourceResponse
│   │   ├── chat.py                    # ChatMessage, ChatResponse
│   │   └── gosati.py                 # GoSatiQuery, GoSatiResponse
│   │
│   ├── routers/                       # Endpoints da API
│   │   ├── __init__.py
│   │   ├── pages.py                   # Renderização de páginas HTML
│   │   ├── skills.py                  # CRUD de Skills (admin)
│   │   ├── sessions.py               # CRUD de Sessions (notebooks)
│   │   ├── sources.py                # Upload/listagem de fontes
│   │   ├── chat.py                    # Chat com LLM (streaming)
│   │   └── gosati.py                 # Integração GoSATI
│   │
│   ├── services/                      # Lógica de negócio
│   │   ├── __init__.py
│   │   ├── base.py                    # BaseService (HTTP + auth)
│   │   ├── skill_service.py          # Gerenciamento de Skills
│   │   ├── session_service.py        # Gerenciamento de Sessions
│   │   ├── source_service.py         # Upload e cache de documentos
│   │   ├── chat_service.py           # Integração Gemini + contexto de Skill
│   │   ├── gosati_service.py         # Cliente SOAP GoSATI/Zangari
│   │   └── document_converter.py    # Conversão de XLSX, DOCX, HTML → texto
│   │
│   ├── templates/                     # Jinja2 templates
│   │   ├── base.html                  # Layout base
│   │   ├── dashboard.html            # Página inicial (lista de notebooks)
│   │   ├── notebook.html             # Editor do notebook (3 painéis)
│   │   ├── admin/
│   │   │   ├── skills.html           # Lista de Skills (admin)
│   │   │   └── skill_editor.html     # Editor de Skill (admin)
│   │   └── components/
│   │       ├── _navbar.html
│   │       ├── _source_panel.html    # Painel esquerdo: fontes
│   │       ├── _chat_panel.html      # Painel central: chat
│   │       ├── _skill_cards.html     # Painel direito: cards de skills
│   │       ├── _upload_modal.html
│   │       └── _gosati_panel.html
│   │
│   ├── static/
│   │   ├── css/
│   │   │   ├── style.css             # Estilos globais
│   │   │   ├── dashboard.css         # Estilos do dashboard
│   │   │   ├── notebook.css          # Estilos do notebook
│   │   │   └── admin.css             # Estilos da área admin
│   │   └── js/
│   │       ├── api.js                 # Cliente HTTP (fetch wrapper)
│   │       ├── utils.js               # Utilitários (toast, helpers)
│   │       ├── dashboard.js           # Lógica do dashboard
│   │       ├── notebook.js            # Inicialização do notebook
│   │       ├── sources.js             # Upload e listagem de fontes
│   │       ├── chat.js                # Interface de chat (streaming)
│   │       ├── skills.js              # Cards de skills no notebook
│   │       ├── gosati.js              # Interface GoSATI
│   │       └── admin/
│   │           └── skill_editor.js    # Editor de skills (admin)
│   │
│   ├── dependencies.py               # Injeção de dependência FastAPI
│   └── main.py                        # Inicialização do FastAPI app
│
├── data/
│   ├── db/
│   │   └── notebook_zang.db          # SQLite (skills, sessions, sources)
│   ├── uploads/                       # Arquivos enviados pelos usuários
│   ├── examples/                      # Arquivos de exemplo das skills
│   └── examples/                      # Arquivos de exemplo das skills
│
├── .env.example                       # Template de variáveis de ambiente
├── pyproject.toml                     # Dependências Python
├── run.py                             # Entry point (uvicorn)
└── ROTEIRO_PROJETO.md                 # Este arquivo
```

---

## 2. Modelo de Dados (Skills)

### 2.1 Skill (Tabela `skills`)

| Campo           | Tipo         | Descrição                                      |
|-----------------|--------------|-------------------------------------------------|
| `id`            | UUID / int   | Identificador único                             |
| `name`          | str          | Nome da skill (aparece no card)                 |
| `description`   | str          | Descrição curta (aparece no card)               |
| `icon`          | str          | Ícone ou emoji do card                          |
| `color`         | str          | Cor do card (hex)                               |
| `macro_instruction` | text     | Instrução macro geral do que a skill faz        |
| `is_active`     | bool         | Se a skill está ativa para uso                  |
| `created_at`    | datetime     | Data de criação                                 |
| `updated_at`    | datetime     | Data de atualização                             |

### 2.2 SkillStep (Tabela `skill_steps`)

| Campo           | Tipo         | Descrição                                      |
|-----------------|--------------|-------------------------------------------------|
| `id`            | UUID / int   | Identificador único                             |
| `skill_id`      | FK → skills  | Skill pai                                       |
| `order`         | int          | Ordem de execução (1, 2, 3...)                  |
| `title`         | str          | Nome da etapa                                   |
| `instruction`   | text         | Instrução específica para o LLM nessa etapa     |
| `expected_output` | text       | Descrição do output esperado (opcional)         |

### 2.3 SkillExample (Tabela `skill_examples`)

| Campo           | Tipo         | Descrição                                      |
|-----------------|--------------|-------------------------------------------------|
| `id`            | UUID / int   | Identificador único                             |
| `skill_id`      | FK → skills  | Skill pai                                       |
| `filename`      | str          | Nome original do arquivo                        |
| `file_path`     | str          | Caminho no disco (`data/examples/`)             |
| `description`   | text         | O que o LLM deve observar nesse exemplo         |
| `mime_type`     | str          | Tipo do arquivo                                 |

*(Tabela de indexação removida — o Gemini 2.0 Flash com janela de 1M tokens lê os documentos inteiros, tornando RAG desnecessário para o volume atual.)*

---

## 3. Fluxos Principais

### 3.1 Fluxo do Administrador — Criar Skill

```
┌─────────────────────────────────────────────────────────────────┐
│  PÁGINA ADMIN: /admin/skills                                    │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                     │
│  │ Skill 1  │  │ Skill 2  │  │  + Nova  │                     │
│  │ Análise  │  │ Auditoria│  │  Skill   │                     │
│  └──────────┘  └──────────┘  └──────────┘                     │
└─────────────────────────────────────────────────────────────────┘
                         │ Clica em "+ Nova Skill" ou edita
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  EDITOR DE SKILL: /admin/skills/{id}                            │
│                                                                 │
│  Nome: [Análise de Prestação de Contas_________]                │
│  Descrição: [Analisa documentos de prestação____]               │
│  Ícone: [📊]  Cor: [#4A90D9]                                   │
│                                                                 │
│  ┌─ Instrução Macro ──────────────────────────────────────────┐ │
│  │ Você é um especialista em análise contábil de condomínios. │ │
│  │ Seu objetivo é verificar se os documentos estão corretos...│ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ Etapas Específicas ──────────────────────────────────────┐  │
│  │                                                            │  │
│  │  1. [Verificar classificação de despesas_______________]   │  │
│  │     Instrução: [Compare cada despesa com o plano de____]   │  │
│  │                                                [❌ Remover]│  │
│  │                                                            │  │
│  │  2. [Validar comprovantes de pagamento_________________]   │  │
│  │     Instrução: [Verifique se cada despesa tem__________]   │  │
│  │                                                [❌ Remover]│  │
│  │                                                            │  │
│  │  [+ Adicionar Etapa]                                       │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─ Arquivos de Exemplo ─────────────────────────────────────┐  │
│  │  📄 exemplo_prestacao.pdf  - "Modelo de prestação correta"│  │
│  │  📄 plano_contas.xlsx      - "Plano de contas padrão"     │  │
│  │  [+ Upload Exemplo]                                        │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                 │
│  [💾 Salvar Skill]                                              │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Fluxo do Usuário — Usar Notebook com Skill

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  NOTEBOOK: /notebooks/{id}                                                  │
│                                                                             │
│  ┌─ FONTES (esquerda) ──┐  ┌─ CHAT (centro) ───────┐  ┌─ SKILLS (dir) ──┐│
│  │                       │  │                        │  │                  ││
│  │  📁 Upload Arquivos   │  │  💬 Bem-vindo ao       │  │  ┌────────────┐ ││
│  │  ┌─────────────────┐  │  │     Notebook Zang!     │  │  │ 📊 Análise │ ││
│  │  │ Arraste arquivos│  │  │                        │  │  │ Prestação  │ ││
│  │  │ ou clique aqui  │  │  │                        │  │  │ de Contas  │ ││
│  │  └─────────────────┘  │  │                        │  │  │   [Usar]   │ ││
│  │                       │  │                        │  │  └────────────┘ ││
│  │  📋 Fontes Carregadas │  │                        │  │                  ││
│  │  • doc1.pdf      [🗑] │  │                        │  │  ┌────────────┐ ││
│  │  • doc2.xlsx     [🗑] │  │                        │  │  │ 🔍 Conf.   │ ││
│  │                       │  │                        │  │  │ Receitas   │ ││
│  │  ── GoSATI ────────── │  │                        │  │  │   [Usar]   │ ││
│  │  Condomínio: [____]   │  │                        │  │  └────────────┘ ││
│  │  Mês: [__] Ano: [__]  │  │                        │  │                  ││
│  │  Tipo: [prestação ▼]  │  │  ┌──────────────────┐  │  │  ┌────────────┐ ││
│  │  [Consultar GoSATI]   │  │  │ Digite mensagem  │  │  │  │ 📈 Fluxo   │ ││
│  │                       │  │  └──────────────────┘  │  │  │ de Caixa   │ ││
│  │                       │  │                        │  │  │   [Usar]   │ ││
│  └───────────────────────┘  └────────────────────────┘  │  └────────────┘ ││
│                                                          └────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Fluxo de Execução da Skill

```
Usuário clica [Usar] no card da skill
        │
        ▼
┌──────────────────────────┐
│ 1. Carrega a Skill       │
│    - Instrução macro     │
│    - Lista de etapas     │
│    - Arquivos de exemplo │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│ 2. Monta o Contexto      │
│    - System prompt =     │
│      macro_instruction + │
│      etapas formatadas + │
│      exemplos (se houver)│
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│ 3. Envia ao Gemini       │
│    - System instruction  │
│    - Documentos (fontes) │
│    - Pergunta do usuário │
│      ou "execute a skill"│
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│ 4. Streaming Response    │
│    - LLM executa etapa   │
│      por etapa           │
│    - Retorna análise     │
│      no chat             │
└──────────────────────────┘
```

---

## 4. APIs (Endpoints)

### 4.1 Skills (Admin) — `/api/v1/skills`

| Método | Rota                             | Descrição                          |
|--------|----------------------------------|------------------------------------|
| GET    | `/api/v1/skills`                 | Listar todas as skills             |
| POST   | `/api/v1/skills`                 | Criar nova skill                   |
| GET    | `/api/v1/skills/{id}`            | Detalhe de uma skill               |
| PUT    | `/api/v1/skills/{id}`            | Atualizar skill                    |
| DELETE | `/api/v1/skills/{id}`            | Deletar skill                      |
| POST   | `/api/v1/skills/{id}/steps`      | Adicionar etapa                    |
| PUT    | `/api/v1/skills/{id}/steps/{sid}`| Atualizar etapa                    |
| DELETE | `/api/v1/skills/{id}/steps/{sid}`| Remover etapa                      |
| POST   | `/api/v1/skills/{id}/examples`   | Upload de arquivo exemplo          |
| DELETE | `/api/v1/skills/{id}/examples/{eid}` | Remover exemplo               |

### 4.2 Sessions (Notebooks) — `/api/v1/sessions`

| Método | Rota                                     | Descrição                    |
|--------|------------------------------------------|------------------------------|
| GET    | `/api/v1/sessions`                       | Listar notebooks             |
| POST   | `/api/v1/sessions`                       | Criar notebook               |
| GET    | `/api/v1/sessions/{id}`                  | Detalhe do notebook          |
| DELETE | `/api/v1/sessions/{id}`                  | Deletar notebook             |

### 4.3 Sources (Fontes) — `/api/v1/sessions/{id}/sources`

| Método | Rota                                     | Descrição                    |
|--------|------------------------------------------|------------------------------|
| POST   | `/api/v1/sessions/{id}/sources/upload`   | Upload de arquivo            |
| GET    | `/api/v1/sessions/{id}/sources`          | Listar fontes                |
| DELETE | `/api/v1/sessions/{id}/sources/{sid}`    | Remover fonte                |
| POST   | `/api/v1/sessions/{id}/sources/gosati`   | Consulta GoSATI como fonte   |

### 4.4 Chat — `/api/v1/sessions/{id}/chat`

| Método | Rota                                     | Descrição                    |
|--------|------------------------------------------|------------------------------|
| POST   | `/api/v1/sessions/{id}/chat`             | Enviar mensagem (streaming)  |
| GET    | `/api/v1/sessions/{id}/chat/history`     | Histórico do chat            |
| POST   | `/api/v1/sessions/{id}/chat/skill/{sid}` | Executar skill sobre fontes  |

---

## 5. Arquivos Base — Conteúdo Inicial

### 5.1 `pyproject.toml`

```toml
[project]
name = "notebook-zang"
version = "0.1.0"
description = "Notebook com Skills customizáveis para análise de dados"
requires-python = ">=3.11"

dependencies = [
    # Web
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "jinja2>=3.1.0",
    "python-multipart>=0.0.18",

    # HTTP & Dados
    "httpx>=0.28.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.7.0",

    # Banco de dados
    "sqlmodel>=0.0.22",
    "aiosqlite>=0.20.0",

    # IA / LLM
    "google-genai>=1.0.0",

    # PDF
    "pdfplumber>=0.11.0",
    "pypdf>=4.0.0",

    # Documentos
    "openpyxl>=3.1.0",
    "python-docx>=1.1.0",
    "numpy>=1.26.0",
]

[tool.ruff]
target-version = "py311"
line-length = 100
lint.select = ["E", "F", "I", "N", "UP", "B"]
```

### 5.2 `.env.example`

```bash
# === GCP / Gemini ===
GCP_PROJECT_ID=seu-projeto-gcp
GCP_PROJECT_NUMBER=123456789
GCP_LOCATION=global
GEMINI_MODEL=gemini-2.0-flash
GEMINI_LOCATION=us-central1
GEMINI_TEMPERATURE=0.3
GEMINI_MAX_OUTPUT_TOKENS=8192

# === GoSATI / Zangari ===
ZANGARI_USUARIO=seu_usuario
ZANGARI_SENHA=sua_senha
ZANGARI_CHAVE=sua_chave_api
ZANGARI_URL=https://sistemas.zangari.com.br/administracaoweb/wsDocumentos.asmx

# === App ===
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO
DATABASE_URL=sqlite+aiosqlite:///data/db/notebook_zang.db
```

### 5.3 `run.py`

```python
"""Entry point para o Notebook Zang."""
import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
        reload=True,
    )
```

### 5.4 `app/main.py`

```python
"""Inicialização do FastAPI — Notebook Zang."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.http_client import init_client, close_client
from app.core.exception_handlers import register_handlers
from app.models.base import init_db
from app.routers import pages, skills, sessions, sources, chat, gosati


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_client()
    await init_db()
    yield
    await close_client()


app = FastAPI(
    title="Notebook Zang",
    version="0.1.0",
    lifespan=lifespan,
)

register_handlers(app)

# Rotas de API
app.include_router(skills.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(sources.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(gosati.router, prefix="/api/v1")

# Páginas HTML
app.include_router(pages.router)

# Arquivos estáticos
app.mount("/static", StaticFiles(directory="app/static"), name="static")
```

### 5.5 `app/models/base.py`

```python
"""Database engine e inicialização."""
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
```

### 5.6 `app/models/skill.py`

```python
"""Modelos de Skill, SkillStep e SkillExample."""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship


class Skill(SQLModel, table=True):
    __tablename__ = "skills"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    description: str = Field(max_length=500)
    icon: str = Field(default="📋", max_length=10)
    color: str = Field(default="#4A90D9", max_length=7)
    macro_instruction: str  # Instrução macro para o LLM
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    steps: list["SkillStep"] = Relationship(back_populates="skill")
    examples: list["SkillExample"] = Relationship(back_populates="skill")


class SkillStep(SQLModel, table=True):
    __tablename__ = "skill_steps"

    id: Optional[int] = Field(default=None, primary_key=True)
    skill_id: int = Field(foreign_key="skills.id")
    order: int = Field(default=1)
    title: str = Field(max_length=200)
    instruction: str  # Instrução específica para esta etapa
    expected_output: Optional[str] = None

    skill: Optional[Skill] = Relationship(back_populates="steps")


class SkillExample(SQLModel, table=True):
    __tablename__ = "skill_examples"

    id: Optional[int] = Field(default=None, primary_key=True)
    skill_id: int = Field(foreign_key="skills.id")
    filename: str
    file_path: str
    description: str  # O que o LLM deve observar nesse exemplo
    mime_type: str

    skill: Optional[Skill] = Relationship(back_populates="examples")
```

---

## 6. Serviços Chave

### 6.1 `skill_service.py` — O que faz

- **CRUD completo** de Skills no banco SQLite
- **Gerencia etapas** (adicionar, reordenar, remover)
- **Upload de exemplos** (salva em `data/examples/{skill_id}/`)
- **Monta o prompt** completo para o Gemini combinando:
  ```
  [Instrução Macro]

  ## Etapas de Análise

  ### Etapa 1: {title}
  {instruction}

  ### Etapa 2: {title}
  {instruction}
  ...

  ## Arquivos de Referência

  - {filename}: {description}
  ```

### 6.2 `chat_service.py` — O que faz

- Mantém cache de documentos por sessão (fontes do usuário)
- Quando uma **skill é ativada**, injeta o prompt montado como system instruction
- Envia documentos + exemplos da skill + mensagem ao Gemini
- Streaming via SSE
- Histórico de chat em memória (pode migrar para DB depois)

### 6.3 `document_converter.py` — O que faz

- Converte formatos que o Gemini não lê nativamente:
  - **XLSX/XLS** → texto tabular via `openpyxl`
  - **DOCX** → texto plano via `python-docx` (preserva headings e tabelas)
  - **HTML** → texto limpo (remove scripts/styles/tags)
- Extrai texto de **PDF** como backup via `pdfplumber` + `pypdf`
- Detecta automaticamente se o formato precisa de conversão
- Salva `.converted.txt` ao lado do arquivo original

### 6.4 `gosati_service.py` — Reutilizado

- Mesmo cliente SOAP do projeto original
- Consultas: prestacao_contas, fluxo_caixa, inadimplencia, etc.
- Resultado convertido em texto e cacheado como fonte

---

## 7. Frontend — Componentes Principais

### 7.1 Dashboard (`dashboard.html`)
- Grid de cards de notebooks existentes
- Botão "Novo Notebook" → modal de criação
- Cada card mostra: título, data, quantidade de fontes

### 7.2 Notebook (`notebook.html`) — Layout 3 Painéis

| Painel Esquerdo (Fontes) | Painel Central (Chat) | Painel Direito (Skills) |
|---------------------------|------------------------|--------------------------|
| Upload de arquivos        | Histórico de mensagens | Cards das skills ativas  |
| Lista de fontes           | Input de mensagem      | Cada card tem [Usar]     |
| Consulta GoSATI           | Streaming de resposta  | Skill ativa = destaque   |

### 7.3 Admin — Skills (`admin/skills.html`)
- Lista de todas as skills em cards
- Botão "+ Nova Skill"
- Status: ativa/inativa

### 7.4 Admin — Editor de Skill (`admin/skill_editor.html`)
- Form com: nome, descrição, ícone, cor
- Textarea para instrução macro
- Lista de etapas com:
  - Campo título + instrução
  - Botão `[+ Adicionar Etapa]`
  - Botão `[❌]` para remover
  - Drag & drop para reordenar (futuro)
- Seção de upload de exemplos com descrição
- Botão salvar

---

## 8. Ordem de Implementação (Fases)

### Fase 1 — Base & Infraestrutura
1. Criar estrutura de diretórios
2. `pyproject.toml` + `.env` + `run.py`
3. `app/main.py` + `core/` (config, auth, http_client, exceptions)
4. `models/base.py` (SQLite + SQLModel)
5. Templates base (`base.html`, `_navbar.html`)

### Fase 2 — Skills (Admin)
6. `models/skill.py` (Skill, SkillStep, SkillExample)
7. `schemas/skill.py`
8. `services/skill_service.py`
9. `routers/skills.py`
10. Templates admin (`skills.html`, `skill_editor.html`)
11. JS admin (`skill_editor.js`)

### Fase 3 — Sessions & Sources
12. `models/session.py` + `schemas/session.py`
13. `services/session_service.py` + `routers/sessions.py`
14. `services/source_service.py` + `routers/sources.py`
15. Templates (`dashboard.html`, `_source_panel.html`, `_upload_modal.html`)
16. JS (`dashboard.js`, `sources.js`)

### Fase 4 — Chat + Integração com Skills
17. `schemas/chat.py`
18. `services/chat_service.py` (Gemini + contexto de skill)
19. `routers/chat.py`
20. Templates (`_chat_panel.html`, `_skill_cards.html`)
21. JS (`chat.js`, `skills.js`)
22. Template notebook completo (`notebook.html`)

### Fase 5 — GoSATI
23. `schemas/gosati.py`
24. `services/gosati_service.py` (reutilizar do projeto original)
25. `routers/gosati.py`
26. Templates (`_gosati_panel.html`)
27. JS (`gosati.js`)

### Fase 6 — Melhorias
28. Relatórios exportáveis (PDF via html2pdf.js)
29. Histórico de chat persistido no banco
30. Compartilhamento de notebooks

---

## 9. O que Muda em Relação ao Projeto Original

| Aspecto                  | Original (notebooklm)           | Novo (notebook_zang)             |
|--------------------------|----------------------------------|----------------------------------|
| **Skills**               | Fixas no código (system prompt)  | Dinâmicas, criadas pelo admin    |
| **Banco de dados**       | JSON em arquivo                  | SQLite com SQLModel              |
| **Etapas de análise**    | Hardcoded no chat_service        | Modular, configurável por skill  |
| **Exemplos**             | Não existiam                     | Upload + descrição por skill     |
| **Layout notebook**      | Fontes + Chat + Relatórios       | Fontes + Chat + **Cards Skills** |
| **Admin**                | Não existia                      | Página dedicada para skills      |
| **Conversão de docs**    | Não existia                      | XLSX/DOCX/HTML → texto auto      |
| **NotebookLM Enterprise**| API do Google Discovery Engine   | **Removida** (usa Gemini direto) |
| **Conferência**          | Módulo separado                  | Vira uma **Skill** configurável  |
| **Relatórios**           | Templates fixos                  | Viram **Skills** configuráveis   |

---

## 10. Tecnologias

| Camada      | Tecnologia                      |
|-------------|----------------------------------|
| Backend     | Python 3.11+ / FastAPI          |
| Frontend    | Vanilla JS + Jinja2 Templates   |
| Banco       | SQLite + SQLModel (async)       |
| LLM         | Google Gemini 2.0 Flash         |
| Docs        | openpyxl + python-docx           |
| API Externa | GoSATI / Zangari (SOAP)         |
| PDF         | pdfplumber + pypdf              |
| HTTP        | httpx (async)                   |
| CSS         | Custom (sem framework)          |

---

## 11. Resumo dos Arquivos a Criar

### Arquivos Python (22 arquivos)
```
app/__init__.py
app/main.py
app/dependencies.py
app/core/__init__.py
app/core/config.py
app/core/auth.py
app/core/exceptions.py
app/core/exception_handlers.py
app/core/http_client.py
app/models/__init__.py
app/models/base.py
app/models/skill.py
app/models/session.py
app/models/source.py
app/schemas/__init__.py
app/schemas/skill.py
app/schemas/session.py
app/schemas/source.py
app/schemas/chat.py
app/schemas/gosati.py
app/routers/__init__.py
app/routers/pages.py
app/routers/skills.py
app/routers/sessions.py
app/routers/sources.py
app/routers/chat.py
app/routers/gosati.py
app/services/__init__.py
app/services/base.py
app/services/skill_service.py
app/services/session_service.py
app/services/source_service.py
app/services/chat_service.py
app/services/gosati_service.py
app/services/document_converter.py
run.py
```

### Arquivos Frontend (17 arquivos)
```
app/templates/base.html
app/templates/dashboard.html
app/templates/notebook.html
app/templates/admin/skills.html
app/templates/admin/skill_editor.html
app/templates/components/_navbar.html
app/templates/components/_source_panel.html
app/templates/components/_chat_panel.html
app/templates/components/_skill_cards.html
app/templates/components/_upload_modal.html
app/templates/components/_gosati_panel.html
app/static/css/style.css
app/static/css/admin.css
app/static/js/api.js
app/static/js/utils.js
app/static/js/dashboard.js
app/static/js/notebook.js
app/static/js/sources.js
app/static/js/chat.js
app/static/js/skills.js
app/static/js/gosati.js
app/static/js/admin/skill_editor.js
```

### Configuração (3 arquivos)
```
pyproject.toml
.env.example
run.py
```

**Total: ~42 arquivos para a estrutura completa**

---

> **Próximo passo**: Confirme este roteiro e começamos a implementação fase por fase.
