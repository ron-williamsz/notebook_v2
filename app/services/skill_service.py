"""Serviço de gerenciamento de Skills."""
import io
import json
import logging
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import BASE_DIR
from app.core.exceptions import NotFoundError
from app.models.criterion import SkillCriterion
from app.models.skill import Skill, SkillExample, SkillStep
from app.schemas.criterio import CriterionSyncItem
from app.schemas.skill import SkillCreate, SkillUpdate, StepCreate, StepSyncItem, StepUpdate

logger = logging.getLogger(__name__)

EXAMPLES_DIR = BASE_DIR / "data" / "examples"


class SkillService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Skill]:
        result = await self.db.execute(select(Skill).order_by(Skill.name))
        return result.scalars().all()

    async def get_by_id(self, skill_id: int) -> Skill:
        skill = await self.db.get(Skill, skill_id)
        if not skill:
            raise NotFoundError(404, f"Skill {skill_id} não encontrada")
        # Carrega relacionamentos
        await self.db.refresh(skill, ["steps", "examples", "criteria"])
        return skill

    async def create(self, data: SkillCreate) -> Skill:
        skill = Skill(**data.model_dump())
        self.db.add(skill)
        await self.db.commit()
        await self.db.refresh(skill, ["steps", "examples", "criteria"])
        return skill

    async def update(self, skill_id: int, data: SkillUpdate) -> Skill:
        skill = await self.get_by_id(skill_id)
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(skill, key, value)
        skill.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(skill, ["steps", "examples", "criteria"])
        return skill

    async def delete(self, skill_id: int) -> None:
        skill = await self.get_by_id(skill_id)
        # Remove arquivos de exemplo do disco
        example_dir = EXAMPLES_DIR / str(skill_id)
        if example_dir.exists():
            shutil.rmtree(example_dir)
        await self.db.delete(skill)
        await self.db.commit()

    # --- Steps ---

    async def add_step(self, skill_id: int, data: StepCreate) -> SkillStep:
        await self.get_by_id(skill_id)  # valida existência
        # Calcula próximo order
        result = await self.db.execute(
            select(SkillStep).where(SkillStep.skill_id == skill_id).order_by(SkillStep.order.desc())
        )
        last = result.scalars().first()
        next_order = (last.order + 1) if last else 1

        step = SkillStep(skill_id=skill_id, order=next_order, **data.model_dump())
        self.db.add(step)
        await self.db.commit()
        await self.db.refresh(step)
        return step

    async def update_step(self, skill_id: int, step_id: int, data: StepUpdate) -> SkillStep:
        step = await self.db.get(SkillStep, step_id)
        if not step or step.skill_id != skill_id:
            raise NotFoundError(404, f"Step {step_id} não encontrada")
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(step, key, value)
        await self.db.commit()
        await self.db.refresh(step)
        return step

    async def delete_step(self, skill_id: int, step_id: int) -> None:
        step = await self.db.get(SkillStep, step_id)
        if not step or step.skill_id != skill_id:
            raise NotFoundError(404, f"Step {step_id} não encontrada")
        await self.db.delete(step)
        await self.db.commit()

    async def sync_steps(self, skill_id: int, items: list[StepSyncItem]) -> list[SkillStep]:
        """Substitui todas as etapas de uma skill atomicamente numa única transação."""
        skill = await self.get_by_id(skill_id)

        # Remove etapas existentes
        existing = await self.db.execute(
            select(SkillStep).where(SkillStep.skill_id == skill_id)
        )
        for step in existing.scalars().all():
            await self.db.delete(step)

        # Cria novas etapas
        new_steps = []
        for order, item in enumerate(items, start=1):
            if not item.title.strip():
                continue
            step = SkillStep(
                skill_id=skill_id,
                order=order,
                title=item.title,
                instruction=item.instruction,
                expected_output=item.expected_output,
            )
            self.db.add(step)
            new_steps.append(step)

        skill.updated_at = datetime.now(timezone.utc)

        # Commit único — se falhar, nada é alterado
        await self.db.commit()

        for step in new_steps:
            await self.db.refresh(step)
        return new_steps

    # --- Criteria ---

    async def sync_criteria(self, skill_id: int, items: list[CriterionSyncItem]) -> list[SkillCriterion]:
        """Substitui todos os critérios de uma skill atomicamente."""
        skill = await self.get_by_id(skill_id)

        # Remove critérios existentes
        existing = await self.db.execute(
            select(SkillCriterion).where(SkillCriterion.skill_id == skill_id)
        )
        for crit in existing.scalars().all():
            await self.db.delete(crit)

        # Cria novos critérios
        new_criteria = []
        for order, item in enumerate(items, start=1):
            if not item.nome.strip():
                continue
            criterion = SkillCriterion(
                skill_id=skill_id,
                order=order,
                nome=item.nome,
                tipo=item.tipo,
                config_json=item.config_json,
                is_active=item.is_active,
            )
            self.db.add(criterion)
            new_criteria.append(criterion)

        skill.updated_at = datetime.now(timezone.utc)
        await self.db.commit()

        for c in new_criteria:
            await self.db.refresh(c)
        return new_criteria

    # --- Examples ---

    async def add_example(
        self, skill_id: int, file: UploadFile, description: str
    ) -> SkillExample:
        await self.get_by_id(skill_id)
        # Salva arquivo em disco
        example_dir = EXAMPLES_DIR / str(skill_id)
        example_dir.mkdir(parents=True, exist_ok=True)
        file_path = example_dir / file.filename
        content = await file.read()
        file_path.write_bytes(content)

        example = SkillExample(
            skill_id=skill_id,
            filename=file.filename,
            file_path=str(file_path),
            description=description,
            mime_type=file.content_type or "application/octet-stream",
        )
        self.db.add(example)
        await self.db.commit()
        await self.db.refresh(example)
        return example

    async def delete_example(self, skill_id: int, example_id: int) -> None:
        example = await self.db.get(SkillExample, example_id)
        if not example or example.skill_id != skill_id:
            raise NotFoundError(404, f"Example {example_id} não encontrado")
        # Remove arquivo do disco
        try:
            os.remove(example.file_path)
        except FileNotFoundError:
            pass
        await self.db.delete(example)
        await self.db.commit()

    # --- Export / Import ---

    async def export_skill(self, skill_id: int) -> tuple[io.BytesIO, str]:
        """Exporta skill como ZIP (skill.json + examples/).

        Returns (zip_buffer, suggested_filename).
        """
        skill = await self.get_by_id(skill_id)

        # Monta JSON sem IDs internos
        data = {
            "version": 1,
            "skill": {
                "name": skill.name,
                "description": skill.description,
                "icon": skill.icon,
                "color": skill.color,
                "macro_instruction": skill.macro_instruction,
                "execution_mode": skill.execution_mode,
                "is_active": skill.is_active,
                "gosati_sections": skill.gosati_sections,
                "gosati_filters": skill.gosati_filters,
            },
            "steps": [
                {
                    "order": s.order,
                    "title": s.title,
                    "instruction": s.instruction,
                    "expected_output": s.expected_output,
                }
                for s in sorted(skill.steps, key=lambda s: s.order)
            ],
            "examples": [
                {
                    "filename": ex.filename,
                    "description": ex.description,
                    "mime_type": ex.mime_type,
                }
                for ex in skill.examples
            ],
            "criteria": [
                {
                    "order": c.order,
                    "nome": c.nome,
                    "tipo": c.tipo,
                    "config_json": c.config_json,
                    "is_active": c.is_active,
                }
                for c in sorted(skill.criteria, key=lambda c: c.order)
            ],
        }

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("skill.json", json.dumps(data, ensure_ascii=False, indent=2))
            for ex in skill.examples:
                file_path = Path(ex.file_path)
                if file_path.exists():
                    zf.write(file_path, f"examples/{ex.filename}")
        buf.seek(0)

        safe_name = re.sub(r'[^\w\-]', '_', skill.name)[:30].strip('_')
        filename = f"skill_{safe_name or 'export'}.zip"
        return buf, filename

    async def import_skill(self, zip_bytes: bytes) -> Skill:
        """Importa skill de um arquivo ZIP.

        Cria nova skill com steps e examples.
        """
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile:
            raise NotFoundError(400, "Arquivo ZIP inválido")

        if "skill.json" not in zf.namelist():
            raise NotFoundError(400, "ZIP não contém skill.json")

        try:
            raw = json.loads(zf.read("skill.json"))
        except json.JSONDecodeError:
            raise NotFoundError(400, "skill.json contém JSON inválido")

        skill_data = raw.get("skill", {})
        steps_data = raw.get("steps", [])
        examples_data = raw.get("examples", [])
        criteria_data = raw.get("criteria", [])

        if not skill_data.get("name"):
            raise NotFoundError(400, "skill.json: campo 'name' obrigatório")

        # Verificar nome duplicado (com dedup recursivo)
        name = skill_data["name"]
        while True:
            existing = await self.db.execute(select(Skill).where(Skill.name == name))
            if not existing.scalars().first():
                break
            if "(importado" in name:
                # Incrementa sufixo: "(importado)" → "(importado 2)" → "(importado 3)"
                m = re.search(r'\(importado(?:\s+(\d+))?\)$', name)
                if m:
                    n = int(m.group(1) or 1) + 1
                    name = re.sub(r'\(importado(?:\s+\d+)?\)$', f'(importado {n})', name)
                else:
                    name = f"{name} (importado)"
            else:
                name = f"{name} (importado)"

        skill = Skill(
            name=name,
            description=skill_data.get("description", ""),
            icon=skill_data.get("icon", "\U0001f4cb"),
            color=skill_data.get("color", "#6366f1"),
            macro_instruction=skill_data.get("macro_instruction", ""),
            execution_mode=skill_data.get("execution_mode", "chat"),
            is_active=skill_data.get("is_active", True),
            gosati_sections=skill_data.get("gosati_sections"),
            gosati_filters=skill_data.get("gosati_filters"),
        )
        self.db.add(skill)
        await self.db.flush()  # Gera skill.id sem commit

        # Steps
        for step_data in steps_data:
            if not step_data.get("title", "").strip():
                continue
            step = SkillStep(
                skill_id=skill.id,
                order=step_data.get("order", 1),
                title=step_data["title"],
                instruction=step_data.get("instruction", ""),
                expected_output=step_data.get("expected_output"),
            )
            self.db.add(step)

        # Criteria
        for crit_data in criteria_data:
            if not crit_data.get("nome", "").strip():
                continue
            criterion = SkillCriterion(
                skill_id=skill.id,
                order=crit_data.get("order", 1),
                nome=crit_data["nome"],
                tipo=crit_data.get("tipo", "presenca_documento"),
                config_json=crit_data.get("config_json", "{}"),
                is_active=crit_data.get("is_active", True),
            )
            self.db.add(criterion)

        # Examples — com sanitização de filename contra path traversal
        example_dir = EXAMPLES_DIR / str(skill.id)
        for ex_data in examples_data:
            fname = ex_data.get("filename", "")
            zip_path = f"examples/{fname}"
            if not fname or zip_path not in zf.namelist():
                continue
            # Sanitiza: usa apenas o nome base, sem componentes de path
            safe_fname = Path(fname).name
            if not safe_fname or safe_fname.startswith('.'):
                continue
            # Salva arquivo em disco
            example_dir.mkdir(parents=True, exist_ok=True)
            file_path = example_dir / safe_fname
            file_path.write_bytes(zf.read(zip_path))
            # Cria registro no banco
            example = SkillExample(
                skill_id=skill.id,
                filename=safe_fname,
                file_path=str(file_path),
                description=ex_data.get("description", ""),
                mime_type=ex_data.get("mime_type", "application/octet-stream"),
            )
            self.db.add(example)

        try:
            await self.db.commit()
        except Exception:
            # Cleanup: remove arquivos salvos em disco se commit falhar
            if example_dir.exists():
                shutil.rmtree(example_dir, ignore_errors=True)
            raise

        await self.db.refresh(skill, ["steps", "examples", "criteria"])
        return skill

    # --- Prompt Builder ---

    async def build_prompt(self, skill_id: int) -> str:
        """Monta o prompt completo da skill para o Gemini."""
        skill = await self.get_by_id(skill_id)

        # Injeta data atual para o modelo não alucinar datas
        meses = [
            "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
        ]
        hoje = datetime.now()
        data_str = f"{hoje.day} de {meses[hoje.month]} de {hoje.year}"
        parts = [
            f"Data atual: {data_str}. Use esta data como 'Data da conferência' quando solicitado.\n",
            skill.macro_instruction,
        ]

        if skill.steps:
            parts.append("\n## Etapas de Análise\n")
            for step in sorted(skill.steps, key=lambda s: s.order):
                parts.append(f"### Etapa {step.order}: {step.title}")
                parts.append(step.instruction)
                if step.expected_output:
                    parts.append(f"**Output esperado:** {step.expected_output}")
                parts.append("")

        if skill.examples:
            parts.append("\n## Arquivos de Referência\n")
            for ex in skill.examples:
                parts.append(f"- **{ex.filename}**: {ex.description}")

        return "\n".join(parts)
