"""Conferencia (audit verification) service for condominium expense receipts."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

from google import genai
from google.genai import types as genai_types
from google.genai.types import Content, GenerateContentConfig, Part

from app.core.config import Settings
from app.schemas.conferencia import (
    ConferenciaBatchResult,
    ConferenciaProgressEvent,
    ConferenciaStatus,
)
from app.services.gosati_service import GoSatiService
from doc_analizer.bridge import enriquecer_lancamento, gerar_checklist_lancamento

logger = logging.getLogger(__name__)

CONFERENCIA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "conferencias"

# ============================================================================
# Pré-agrupamento fiscal — mantém DARF/FGTS/GPS/folha no mesmo batch
# ============================================================================

_TIPO_FISCAL_PATTERNS = [
    (re.compile(r"DARF|IRRF|CSLL|COFINS|PIS\s+S/", re.I), "darf"),
    (re.compile(r"FGTS|SEFIP|GFD", re.I), "fgts"),
    (re.compile(r"GPS\s*[-/]|INSS\s*[-/]|INSS\s+EMPRESA", re.I), "gps"),
    (re.compile(r"FOLHA|SALARIO|ADIANTAMENTO\s+(?:QUINZ|SALAR)", re.I), "folha"),
]


def _classificar_grupo_fiscal(despesa: dict) -> str:
    """Retorna grupo fiscal ou 'geral' para batching inteligente."""
    texto = f"{despesa.get('historico', '')} {despesa.get('nome_conta', '')}".upper()
    for padrao, grupo in _TIPO_FISCAL_PATTERNS:
        if padrao.search(texto):
            return grupo
    return "geral"


def _agrupar_despesas_em_batches(
    despesas: list[dict], batch_size: int = 5
) -> list[list[dict]]:
    """Agrupa despesas mantendo lançamentos fiscais relacionados juntos.

    DARF, FGTS, GPS e folha de pagamento nunca são separados entre batches.
    """
    grupos: dict[str, list[dict]] = {}
    for d in despesas:
        grupo = _classificar_grupo_fiscal(d)
        grupos.setdefault(grupo, []).append(d)

    batches: list[list[dict]] = []
    batch_atual: list[dict] = []

    # Primeiro: inserir grupos fiscais completos
    for grupo_nome in ("darf", "fgts", "gps", "folha"):
        grupo = grupos.pop(grupo_nome, [])
        if not grupo:
            continue
        if len(batch_atual) + len(grupo) <= batch_size:
            batch_atual.extend(grupo)
        else:
            if batch_atual:
                batches.append(batch_atual)
                batch_atual = []
            if len(grupo) > batch_size:
                for i in range(0, len(grupo), batch_size):
                    batches.append(grupo[i : i + batch_size])
            else:
                batch_atual = grupo

    # Depois: preencher com despesas gerais
    for d in grupos.get("geral", []):
        batch_atual.append(d)
        if len(batch_atual) >= batch_size:
            batches.append(batch_atual)
            batch_atual = []

    if batch_atual:
        batches.append(batch_atual)

    return batches

CONFERENCIA_SYSTEM_INSTRUCTION = """\
Voce e um auditor contabil senior especializado em conferencia de comprovantes de \
despesas de condominios brasileiros. Sua funcao e analisar documentos de comprovantes \
(imagens de comprovantes de pagamento, notas fiscais, boletos) e verificar sua \
conformidade com os dados lancados na prestacao de contas.

## GUIA DE RECONHECIMENTO DE DOCUMENTOS
IMPORTANTE: Cada lancamento pode conter MULTIPLAS imagens/paginas. Antes de concluir \
que um documento esta ausente, examine TODAS as imagens associadas ao lancamento. \
Os documentos podem aparecer em qualquer ordem. Aprenda a reconhecer cada tipo:

### Faturas de Concessionarias (Enel/Eletropaulo, Sabesp, Gas, etc.)
- **ENEL/ELETROPAULO**: Fatura de energia. Contem logo Enel, numero da instalacao, \
consumo em kWh, valores de distribuicao/geracao, bandeira tarifaria, codigo de barras. \
Titulo tipico: "Conta de Energia" ou "Fatura de Energia Eletrica". Pode ter layout \
com graficos de consumo mensal.
- **SABESP**: Fatura de agua/esgoto. Contem logo Sabesp, "Fatura de Servicos de Agua \
e/ou Esgotos", numero do fornecimento/RGI, consumo em M3, tabela de tarifas, \
codigo de barras. Cliente pode aparecer como "CDM ED..." (condominio).
- **GAS (Comgas/Naturgy)**: Contem consumo em M3, numero da instalacao, codigo de barras.
- SE a imagem mostrar qualquer um desses elementos, reconheca como FATURA DE CONSUMO \
PRESENTE, mesmo que o layout seja diferente do habitual.

### Relacao Bancaria
Documento com titulo "RELACAO BANCARIA" (pode estar em maiusculas). Contem:
- Cabecalho com EMPRESA, ESTABELECIMENTO, CNPJ
- "Relacao de Pagamento referente: FOLHA DE PAGAMENTO" ou "ADIANTAMENTO QUINZ."
- Tabela com colunas: Cod.Func., Nome, Agencia, Conta Corrente, CPF, Valor (R$)
- Totais por estabelecimento e empresa
- Este documento comprova a transferencia bancaria para funcionarios.

### Folha de Pagamento da Rotina (Analitico)
Documento com titulo "Folha de Pagamento da Rotina:" seguido do tipo (ex: "ADIANTAMENTO QUINZ.").
Contem:
- Mes Base, Empresa, Estabelecimento, CNPJ
- Dados do colaborador: nome, cargo, admissao, CPF
- Secoes: VENCIMENTOS, DESCONTOS, BASES
- Codigos como 0051 ADIANTAMENTO QUINZENAL, 0300 SALARIO BASE, 0350 LIQUIDO
- Este e o analitico da folha de pagamento.

### Comprovante de Pagamento Bancario
- Pag-For, TED, DOC, PIX, boleto pago: mostra valor, beneficiario, data, banco.
- DARF: guia de recolhimento de tributos federais (IRRF, CSLL, PIS, COFINS, INSS).
- GPS: guia de recolhimento previdenciario.

### Nota Fiscal
- NFe, NFS-e, NFTS: contem CNPJ emissor, numero da NF, descricao do servico, valor.
- Boleto de pagamento NAO substitui Nota Fiscal para servicos.

Aplique rigorosamente as seguintes regras de auditoria:

## 1. REGRAS GERAIS DOS LANCAMENTOS
- Todo lancamento (exceto negativos e tarifas bancarias) DEVE possuir documento comprovatorio.
- O historico do lancamento DEVE conter o numero da Nota Fiscal correspondente.
- Toda pendencia encontrada DEVE obrigatoriamente mencionar o numero do lancamento.
- Pagamentos de SERVICOS que possuam APENAS boleto bancario, SEM nota fiscal anexa, \
devem ser sinalizados como PENDENCIA com "Ausencia de Nota Fiscal" \
(boleto NAO substitui Nota Fiscal para servicos).
- "Nota de Reembolso de Despesas" da administradora e documento valido. NAO pontuar \
como ausencia de NF quando Nota de Reembolso estiver presente.

## 2. COMPROVANTE DE PAGAMENTO
Verificar:
- Possui linha digitavel? Se sim, o boleto esta anexado?
- O valor pago confere com o valor do lancamento?
- O favorecido/beneficiario confere com o emissor da Nota Fiscal?
- Em caso de divergencia, indicar o numero do lancamento.

## 3. NOTA FISCAL
Conferir:
- Razao social / nome da empresa
- CNPJ do emissor
- Numero da NF
- Descricao do servico compativel com o historico do lancamento
- Se e segunda via (sinalizar se necessario)
- Referencia do servico (se nao consta na NFe mas consta no historico, ou vice-versa, apontar)
- Valor da NF confere com o lancamento
- Numero da NF consta no historico contabil
- Data de pagamento confere com vencimento do boleto
- Se NF ausente para servicos, indicar o numero do lancamento. \
ATENCAO: Boleto NAO substitui Nota Fiscal para pagamentos de servicos.

## 4. NOTAS FORA DO MUNICIPIO DE SAO PAULO
Se a NF nao for do municipio de Sao Paulo:
- Possui NFTS (Nota Fiscal Tomador de Servico)?
- Valor da NFTS confere com a NF?
- Numero da NF consta na NFTS?
- Impostos retidos conferem?
- Se irregular, indicar o numero do lancamento.

## 5. SIMPLES NACIONAL
Se a empresa for optante do Simples Nacional:
- A consulta pertence a empresa correta?
- A consulta e valida na data da emissao?
- Se ausente, indicar o numero do lancamento correspondente.

## 6. E-MAILS ANEXOS
- Contem informacao relevante?
- Ha informacao desnecessaria?
- Se houver problema, indicar o numero do lancamento.

## 7. SINDIFICIOS
- Deve conter a referencia no historico.
- Alem do boleto, deve conter a Relacao de Contribuicao Assistencial.
- Se ausente, indicar o numero do lancamento.

## 8. REEMBOLSOS
- "Nota de Reembolso de Despesas" emitida pela administradora e um documento valido e \
suficiente. NAO pontuar como pendencia lancamentos que possuam Nota de Reembolso.
- Soma dos valores confere?
- Cupons legiveis? Caso nao, apontar nas divergencias.
- Segunda via necessaria?
- Documento comprobatorio anexado?
- Divergencia, indicar o numero do lancamento.

## 9. FATURAS DE CONSUMO (Energia, Agua, Gas)
ATENCAO: Examine TODAS as imagens do lancamento antes de concluir que a fatura esta ausente.
Faturas de concessionarias (Enel, Sabesp, Comgas) tem layouts proprios - procure por logos, \
numero de instalacao/fornecimento/RGI, consumo (kWh ou M3), codigo de barras.
- Fatura anexada? (Examine cuidadosamente TODAS as paginas/imagens)
- Conferir consumo.
- Conferir referencia.
Regras especificas:
- Sabesp nao possui referencia formal. Caso tenha, classifique nos itens com divergencia.
- Ausencia de fatura, indicar o numero do lancamento.
- O numero de consumo no historico nao deve ter virgula.
- Faturas de consumo que nao estiverem em anexo poderao ser liberadas apenas com a apresentacao do comprovante.
{regra_tipo_conta}

## 10. IMPOSTOS
REGRA CRITICA - DARF e FGTS CONSOLIDADOS:
Guias DARF e de FGTS sao pagas em um UNICO pagamento e desmembradas em varios \
lancamentos na prestacao de contas. Por exemplo, um DARF de R$ 12.000 pode gerar \
lancamentos separados de IRRF (R$ 500), CSLL (R$ 200), PIS (R$ 100), etc.
ANTES de pontuar divergencia de valor em DARF ou FGTS:
1. Identifique TODOS os lancamentos do lote que se referem ao mesmo tipo de guia
2. SOME os valores de todos esses lancamentos
3. Compare o TOTAL SOMADO com o valor da guia
4. Se o total somado confere com a guia, NAO pontuar divergencia em nenhum deles
5. Se o total somado NAO confere, pontuar divergencia indicando o valor esperado vs encontrado
- Guia anexada?
- Comprovante anexado?
- FGTS: possui SEFIP? A ordem de lancamentos do FGTS deve ser: Comprovante, Guia, SEFIP. \
Caso nao esteja nessa ordem, deve ser pontuada em divergencias.
- GPS: possui relatorio de autonomos se necessario?
- Pendencia, indicar o numero do lancamento.

## 11. SALARIOS E ADIANTAMENTOS
ATENCAO: Examine TODAS as imagens do lancamento. A relacao bancaria e a folha analitica \
podem estar entre as paginas - procure por documentos com titulo "RELACAO BANCARIA" \
(tabela com Cod.Func., Nome, Agencia, Conta, CPF, Valor) e "Folha de Pagamento da Rotina" \
(secoes VENCIMENTOS, DESCONTOS, BASES).
APENAS no primeiro lancamento de FOLHA DE PAGAMENTO e ADIANTAMENTO SALARIAL:
- Relacao bancaria anexada? (documento com titulo "RELACAO BANCARIA" contendo dados bancarios dos funcionarios)
- Valor total confere?
No ultimo lancamento de FOLHA DE PAGAMENTO e ADIANTAMENTO SALARIAL:
- Analitico anexado? (documento "Folha de Pagamento da Rotina" com VENCIMENTOS, DESCONTOS, BASES, LIQUIDO)
- Valor de GPS no analitico confere com GPS paga?
- Se divergente, relatorio de autonomos anexado?
- Pendencia, indicar o numero do lancamento correspondente.

## Formato de Resposta
Para cada lancamento analisado, produza:
- **Lancamento [N]**: [historico resumido] - R$ [valor]
  - **Status**: OK | PENDENCIA | DIVERGENCIA
  - **Detalhes**: verificacoes realizadas e documentos identificados nas imagens
  - **Pendencias**: problemas encontrados (se houver)

Seja objetivo, preciso e sempre referencie o numero do lancamento.
Responda em portugues brasileiro.
"""

CONFERENCIA_BATCH_PROMPT = """\
## Conferencia de Comprovantes - Lote {batch_num} de {total_batches}

Analise os {despesas_count} lancamentos abaixo e seus respectivos comprovantes (imagens).

Para cada lancamento, aplique TODAS as regras de auditoria: regras gerais, \
comprovante de pagamento, nota fiscal, NFTS (se aplicavel), simples nacional (se aplicavel), \
faturas de consumo, impostos, salarios/adiantamentos, reembolsos, sindificios.

### Dados dos Lancamentos:

{metadata}

### Instrucoes:
1. Para cada lancamento, examine TODAS as imagens correspondentes com ATENCAO
2. PRIMEIRO: Identifique o TIPO de cada documento nas imagens (comprovante de pagamento, \
nota fiscal, boleto, fatura de consumo, relacao bancaria, folha analitica, DARF, GPS, SEFIP, etc.)
3. DEPOIS: Aplique as regras de auditoria verificando valores, CNPJ, numero da NF, favorecido
4. Compare o historico do lancamento com a descricao da NF
5. NAO conclua que um documento esta ausente sem examinar TODAS as paginas/imagens do lancamento. \
Faturas de concessionarias (Enel, Sabesp) e relacoes bancarias podem ter layouts nao convencionais.
6. Para pagamentos de SERVICOS que contem apenas boleto sem Nota Fiscal, sinalize como PENDENCIA.
7. Para CADA pendencia encontrada, inclua OBRIGATORIAMENTE:
   - O **N. Lancto** (numero do lancamento conforme informado acima)
   - A **descricao clara** do problema encontrado
8. Se a imagem estiver ilegivel ou ausente, registre como pendencia
9. Quando uma classificacao automatica de tipo de documento for fornecida junto ao \
lancamento, USE-A como guia para verificar os campos criticos indicados. Se a \
classificacao parecer incorreta com base na sua analise visual, IGNORE-A e classifique \
por conta propria.
10. CADA lancamento que possui CHECKLIST DE VERIFICACAO OBRIGATORIA deve ser respondido \
item a item. NAO pule nenhum item do checklist. Use o formato:
    - [OK] Descricao do item
    - [PENDENCIA] Descricao do item — motivo
    - [DIVERGENCIA] Descricao do item — esperado X, encontrado Y

Use o formato EXATO para cada lancamento:
- **Lancto. [N. Lancto]**: [historico] - R$ [valor]
  - Status: OK | PENDENCIA | DIVERGENCIA
  - Documentos identificados: [lista dos tipos de documento encontrados nas imagens]
  - Checklist: [respostas item a item, se checklist fornecido]
  - Pendencias: [descricao do problema]

Produza o resultado em Markdown estruturado. Inclua TODOS os lancamentos — nao omita nenhum.
"""

CONFERENCIA_CONSOLIDATION_PROMPT = """\
## Consolidacao do Relatorio de Conferencia de Comprovantes

Gere o relatorio final FOCANDO apenas nos lancamentos com problemas.

# Relatorio de Conferencia de Comprovantes
**Condominio**: {condominio_nome} (Codigo: {condominio})
**Periodo de Referencia**: {mes:02d}/{ano}
**Data da Conferencia**: (data atual)
**Total de Lancamentos Analisados**: {total_despesas} (em {total_batches} lotes)

Secoes OBRIGATORIAS:

1. **Resumo**: Total analisados, total OK, total com pendencias, total com divergencias (apenas numeros).

2. **Pendencias e Divergencias**: Liste SOMENTE lancamentos com status PENDENCIA ou DIVERGENCIA.
   Para CADA lancamento com problema, mostre:
   - **Lancto. [N]** — Historico — Valor
     - Problema encontrado (descricao clara e objetiva)
   NAO liste lancamentos com status OK.

3. **Observacoes Gerais**: Apenas se houver padroes relevantes (maximo 3 linhas).

### Resultados por Lote:
{batch_findings}

REGRAS:
- TODA pendencia DEVE conter o N. Lancto (numero do lancamento, ex: Lancto. 3800524)
- NAO repita lancamentos que estao OK — eles ja foram conferidos
- Seja CONCISO: descreva o problema em 1-2 linhas por lancamento
- Se TODOS estiverem OK, diga apenas: "Nenhuma pendencia ou divergencia encontrada."

---
IMPORTANTE: Ao final, inclua um bloco JSON com as pendencias:
```json
[{{"lancamento": "3800524", "pendencia": "Descricao da pendencia"}}]
```
Inclua APENAS lancamentos com problemas. Se nao houver, retorne: []
"""


class ConferenciaService:
    def __init__(self, settings: Settings):
        self.settings = settings
        # GoSatiService: db=None since conferencia only uses SOAP/HTTP methods
        self.gosati = GoSatiService(db=None, settings=settings)
        # Gemini client with retry
        self.client = genai.Client(
            vertexai=True,
            project=settings.gcp_project_id,
            location=settings.gemini_location,
            http_options=genai_types.HttpOptions(
                timeout=180_000,
                retry_options=genai_types.HttpRetryOptions(
                    attempts=5,
                    initial_delay=2.0,
                    max_delay=60.0,
                    http_status_codes=[408, 429, 500, 502, 503, 504],
                ),
            ),
        )

    async def run_conferencia(
        self,
        condominio: int,
        mes: int,
        ano: int,
        batch_size: int = 5,
        tipo_conta: str = "propria",
    ) -> AsyncGenerator[ConferenciaProgressEvent, None]:
        """Main orchestrator. Yields progress events for SSE streaming."""

        # Phase 1: Fetch prestacao data
        yield ConferenciaProgressEvent(
            status=ConferenciaStatus.PENDING,
            message="Buscando dados de prestacao de contas...",
        )

        try:
            prestacao_data = await self.gosati.consultar_prestacao_contas(
                condominio, mes, ano
            )
        except Exception as e:
            yield ConferenciaProgressEvent(
                status=ConferenciaStatus.ERROR,
                message="Erro ao buscar prestacao de contas",
                error=str(e),
            )
            return

        if not prestacao_data:
            yield ConferenciaProgressEvent(
                status=ConferenciaStatus.ERROR,
                message="Nenhum dado de prestacao de contas encontrado",
                error="API retornou vazio",
            )
            return

        condominio_nome = self._extract_condominio_nome(prestacao_data)

        # Build system instruction with tipo_conta rule
        if tipo_conta == "pool":
            regra_tipo_conta = (
                "- IMPORTANTE: Este condominio e conta POOL. "
                "Obrigatoriamente precisa comprovante para faturas de consumo."
            )
        else:
            regra_tipo_conta = (
                "- IMPORTANTE: Este condominio e conta PROPRIA. "
                "Comprovante nao e obrigatorio para faturas de consumo, "
                "mas saldo deve estar refletido no extrato."
            )
        self._system_instruction = CONFERENCIA_SYSTEM_INSTRUCTION.format(
            regra_tipo_conta=regra_tipo_conta,
        )

        despesas_raw = self.gosati.extrair_despesas_com_comprovante(prestacao_data)
        if not despesas_raw:
            yield ConferenciaProgressEvent(
                status=ConferenciaStatus.ERROR,
                message="Nenhuma despesa com comprovante encontrada",
                error="Sem despesas com link_docto",
            )
            return

        total_despesas = len(despesas_raw)

        # Pré-agrupamento: mantém DARF/FGTS/GPS/folha no mesmo batch
        batches = _agrupar_despesas_em_batches(despesas_raw, batch_size)
        total_batches = len(batches)

        yield ConferenciaProgressEvent(
            status=ConferenciaStatus.DOWNLOADING,
            message=f"{total_despesas} despesas com comprovante. Iniciando...",
            batch_total=total_batches,
        )

        # Phase 2: Download + Analyze in batches
        all_batch_results: list[ConferenciaBatchResult] = []

        for batch_idx, batch_despesas in enumerate(batches):

            # Download
            yield ConferenciaProgressEvent(
                status=ConferenciaStatus.DOWNLOADING,
                message=f"Baixando lote {batch_idx + 1}/{total_batches} ({len(batch_despesas)} despesas)...",
                batch_current=batch_idx + 1,
                batch_total=total_batches,
                percent=int((batch_idx / total_batches) * 100),
            )

            batch_images = await self._download_batch(batch_despesas)

            # Analyze
            yield ConferenciaProgressEvent(
                status=ConferenciaStatus.ANALYZING,
                message=f"Analisando lote {batch_idx + 1}/{total_batches}...",
                batch_current=batch_idx + 1,
                batch_total=total_batches,
                percent=int(((batch_idx + 0.5) / total_batches) * 100),
            )

            try:
                findings = await self._analyze_batch(
                    batch_despesas, batch_images, batch_idx + 1, total_batches,
                )
            except Exception as e:
                logger.error("Error analyzing batch %d: %s", batch_idx + 1, e)
                findings = f"**ERRO no lote {batch_idx + 1}**: {e}"

            batch_result = ConferenciaBatchResult(
                batch_index=batch_idx + 1,
                despesas_count=len(batch_despesas),
                findings=findings,
            )
            all_batch_results.append(batch_result)

            yield ConferenciaProgressEvent(
                status=ConferenciaStatus.ANALYZING,
                message=f"Lote {batch_idx + 1}/{total_batches} concluido.",
                batch_current=batch_idx + 1,
                batch_total=total_batches,
                percent=int(((batch_idx + 1) / total_batches) * 100),
                batch_result=batch_result,
            )

        # Phase 3: Consolidation
        yield ConferenciaProgressEvent(
            status=ConferenciaStatus.CONSOLIDATING,
            message="Consolidando resultados...",
            batch_current=total_batches,
            batch_total=total_batches,
            percent=95,
        )

        try:
            final_report, pendencias = await self._consolidate_results(
                all_batch_results, condominio, condominio_nome,
                mes, ano, total_despesas,
            )
        except Exception as e:
            logger.error("Error consolidating: %s", e)
            final_report = self._fallback_consolidation(
                all_batch_results, condominio, condominio_nome, mes, ano
            )
            pendencias = None

        yield ConferenciaProgressEvent(
            status=ConferenciaStatus.COMPLETED,
            message="Conferencia concluida!",
            batch_current=total_batches,
            batch_total=total_batches,
            percent=100,
            final_report=final_report,
            condominio_nome=condominio_nome,
            condominio_codigo=condominio,
            pendencias=pendencias,
        )

    async def _download_batch(
        self, despesas: list[dict]
    ) -> list[list[tuple[bytes, str]]]:
        """Download comprovante documents for a batch.

        Returns list of document lists, each item is (data_bytes, mime_type).
        """
        results = []
        for d in despesas:
            docs = await self.gosati.baixar_comprovante(d["link_docto"])
            results.append(docs)
        return results

    async def _analyze_batch(
        self,
        despesas: list[dict],
        batch_images: list[list[tuple[bytes, str]]],
        batch_num: int,
        total_batches: int,
    ) -> str:
        """Send a batch to Gemini with images/PDFs and metadata."""
        parts: list[Part] = []
        metadata_lines = []

        for desp, documents in zip(despesas, batch_images):
            num_lancto = desp.get("numero_lancamento", "?")

            # Classificar documentos para enriquecer o contexto do Gemini
            enrichment = None
            try:
                enrichment = enriquecer_lancamento(documents, desp)
                if enrichment:
                    tipos = enrichment.get("tipos_encontrados", [])
                    n_docs = len(documents)
                    mimes = [m for _, m in documents]
                    logger.info(
                        "Lancto %s: %d docs (mimes=%s) -> tipos=%s, dica=%s",
                        num_lancto, n_docs, mimes, tipos,
                        "SIM" if enrichment.get("dica_consolidada") else "NAO",
                    )
            except Exception as e:
                logger.warning("Classificacao falhou para lancto %s: %s", num_lancto, e)

            meta = (
                f"### Lancto. {num_lancto}\n"
                f"- **N. Lancto**: {num_lancto}\n"
                f"- **Historico**: {desp.get('historico', '')}\n"
                f"- **Valor**: R$ {desp.get('valor', '0')}\n"
                f"- **Data**: {desp.get('data', '')}\n"
                f"- **Conta**: {desp.get('nome_conta', '')}\n"
                f"- **Sub-conta**: {desp.get('nome_sub_conta', '')}\n"
                f"- **Documentos**: {len(documents)} pagina(s)\n"
            )

            if enrichment and enrichment["dica_consolidada"]:
                meta += (
                    f"\n**Classificacao automatica dos documentos:**\n"
                    f"{enrichment['dica_consolidada']}\n"
                )

            # Checklist forçado por tipo — Gemini deve responder item a item
            if enrichment and enrichment.get("tipos_encontrados"):
                checklist = gerar_checklist_lancamento(
                    desp, enrichment["tipos_encontrados"]
                )
                if checklist:
                    meta += f"\n{checklist}\n"

            metadata_lines.append(meta)

            for j, (doc_bytes, mime_type) in enumerate(documents):
                doc_label = "PDF" if "pdf" in mime_type else "Imagem"

                # Dica de tipo por página quando disponível
                page_hint = ""
                if enrichment and j < len(enrichment["classificacoes"]):
                    pc = enrichment["classificacoes"][j]
                    if pc["tipo"] != "nao_identificado":
                        page_hint = f" | Tipo provavel: {pc['nome_tipo']}"

                parts.append(
                    Part.from_bytes(data=doc_bytes, mime_type=mime_type)
                )
                parts.append(
                    Part.from_text(
                        text=f"[{doc_label} acima: Lancto. {num_lancto}, Pagina {j + 1} de {len(documents)}{page_hint}]"
                    )
                )

        prompt = CONFERENCIA_BATCH_PROMPT.format(
            batch_num=batch_num,
            total_batches=total_batches,
            despesas_count=len(despesas),
            metadata="\n".join(metadata_lines),
        )
        parts.append(Part.from_text(text=prompt))

        contents_initial = [Content(role="user", parts=parts)]

        response = await self.client.aio.models.generate_content(
            model=self.settings.gemini_model,
            contents=contents_initial,
            config=GenerateContentConfig(
                system_instruction=self._system_instruction,
                max_output_tokens=self.settings.gemini_max_output_tokens,
                temperature=0.1,
            ),
        )
        text = response.text.strip() if response.text else ""
        text = re.sub(r"\n{4,}", "\n\n\n", text)

        # Validação: todos os lançamentos cobertos?
        ok, faltando = self._validar_resposta_batch(text, despesas)
        if not ok and faltando:
            ids_faltando = [
                str(d.get("numero_lancamento", "?")) for d in faltando
            ]
            logger.info(
                "Retry para %d lancamentos faltando no batch %d: %s",
                len(faltando), batch_num, ids_faltando,
            )
            retry_prompt = (
                f"Na sua analise anterior, os seguintes lancamentos NAO foram "
                f"analisados: {', '.join(ids_faltando)}. "
                f"Analise-os agora aplicando TODAS as regras de auditoria e "
                f"o checklist de verificacao, se fornecido. "
                f"Use o mesmo formato de resposta."
            )
            retry_response = await self.client.aio.models.generate_content(
                model=self.settings.gemini_model,
                contents=[
                    *contents_initial,
                    Content(role="model", parts=[Part.from_text(text=text)]),
                    Content(
                        role="user",
                        parts=[Part.from_text(text=retry_prompt)],
                    ),
                ],
                config=GenerateContentConfig(
                    system_instruction=self._system_instruction,
                    max_output_tokens=self.settings.gemini_max_output_tokens,
                    temperature=0.1,
                ),
            )
            retry_text = (
                retry_response.text.strip() if retry_response.text else ""
            )
            if retry_text:
                text += (
                    f"\n\n### Complemento (lancamentos faltantes)\n{retry_text}"
                )

        return text

    @staticmethod
    def _validar_resposta_batch(
        resposta: str, despesas: list[dict]
    ) -> tuple[bool, list[dict]]:
        """Valida se todos os lançamentos foram cobertos na resposta.

        Retorna (ok, lista_de_despesas_faltando).
        """
        ids_enviados: set[str] = set()
        despesas_por_id: dict[str, dict] = {}
        for d in despesas:
            num = str(d.get("numero_lancamento", "")).strip()
            if num:
                ids_enviados.add(num)
                despesas_por_id[num] = d

        ids_encontrados: set[str] = set()
        for match in re.finditer(
            r"Lanc(?:to|amento)\.?\s*(\d+)", resposta, re.I
        ):
            ids_encontrados.add(match.group(1))

        faltando = ids_enviados - ids_encontrados
        if not faltando:
            return True, []

        logger.warning(
            "Batch com %d lancamentos faltando na resposta: %s",
            len(faltando),
            faltando,
        )
        return False, [
            despesas_por_id[nid] for nid in faltando if nid in despesas_por_id
        ]

    async def _consolidate_results(
        self,
        batch_results: list[ConferenciaBatchResult],
        condominio: int,
        condominio_nome: str,
        mes: int,
        ano: int,
        total_despesas: int,
    ) -> tuple[str, list[dict] | None]:
        """Consolidate all batch findings into a final report.

        Returns (markdown_report, pendencias_list).
        """
        combined = ""
        for br in batch_results:
            combined += (
                f"\n\n---\n## Lote {br.batch_index} "
                f"({br.despesas_count} despesas)\n{br.findings}\n"
            )

        prompt = CONFERENCIA_CONSOLIDATION_PROMPT.format(
            condominio=condominio,
            condominio_nome=condominio_nome,
            mes=mes,
            ano=ano,
            total_despesas=total_despesas,
            total_batches=len(batch_results),
            batch_findings=combined,
        )

        # Consolidação precisa de mais tokens que batches individuais (relatório completo)
        consolidation_max_tokens = max(self.settings.gemini_max_output_tokens, 32768)

        response = await self.client.aio.models.generate_content(
            model=self.settings.gemini_model,
            contents=[Content(role="user", parts=[Part.from_text(text=prompt)])],
            config=GenerateContentConfig(
                system_instruction=self._system_instruction,
                max_output_tokens=consolidation_max_tokens,
                temperature=0.1,
            ),
        )

        report_text = response.text.strip() if response.text else ""
        pendencias = self._parse_pendencias_json(report_text)

        # Remove the JSON block from the markdown report
        clean_report = re.sub(
            r"\n---\s*\n.*?```json.*?```",
            "",
            report_text,
            flags=re.DOTALL,
        ).strip()

        # Strip excessive whitespace lines that Gemini sometimes produces
        clean_report = re.sub(r"\n{4,}", "\n\n\n", clean_report)

        return clean_report, pendencias

    @staticmethod
    def _fallback_consolidation(
        batch_results: list[ConferenciaBatchResult],
        condominio: int,
        condominio_nome: str,
        mes: int,
        ano: int,
    ) -> str:
        """Simple concatenation if Gemini consolidation fails."""
        parts = [
            f"# Relatorio de Conferencia de Comprovantes\n",
            f"**Condominio**: {condominio_nome} (Codigo: {condominio}) | "
            f"**Periodo**: {mes:02d}/{ano}\n\n",
        ]
        for br in batch_results:
            parts.append(f"## Lote {br.batch_index}\n{br.findings}\n\n---\n")
        return "\n".join(parts)

    @staticmethod
    def _extract_condominio_nome(prestacao_data: dict) -> str:
        """Extract condominium name from prestacao de contas data."""
        try:
            diffgram = prestacao_data.get("diffgram", {})
            prestacao = diffgram.get("PrestacaoContas", {})
            condominios = prestacao.get("Condominios", {})
            if isinstance(condominios, list):
                condominios = condominios[0] if condominios else {}
            nome = condominios.get("nome", "")
            if nome:
                return nome
        except (KeyError, TypeError, IndexError):
            pass
        return ""

    @staticmethod
    def _parse_pendencias_json(text: str) -> list[dict] | None:
        """Extract JSON pendencias block from Gemini response."""
        match = re.search(r"```json\s*\n(.*?)\n\s*```", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse pendencias JSON from consolidation")
        return None

    @staticmethod
    def save_result(
        session_id: str,
        report: str,
        pendencias: list[dict] | None,
        batch_results: list[ConferenciaBatchResult],
        condominio_nome: str,
        condominio_codigo: int,
        mes: int,
        ano: int,
    ) -> None:
        """Persist conferencia result to disk as JSON."""
        CONFERENCIA_DIR.mkdir(parents=True, exist_ok=True)
        filepath = CONFERENCIA_DIR / f"{session_id}.json"
        data = {
            "session_id": session_id,
            "report": report,
            "pendencias": pendencias,
            "batch_results": [br.model_dump() for br in batch_results],
            "condominio_nome": condominio_nome,
            "condominio_codigo": condominio_codigo,
            "mes": mes,
            "ano": ano,
            "created_at": datetime.now().isoformat(),
        }
        filepath.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def get_result(session_id: str) -> dict[str, Any] | None:
        """Load conferencia result from disk."""
        filepath = CONFERENCIA_DIR / f"{session_id}.json"
        if not filepath.exists():
            return None
        try:
            return json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
