"""
Configuração central dos tipos de documentos condominiais.
Cada tipo define:
  - keywords para classificação automática
  - campos obrigatórios a extrair (baseado nos grifos dos modelos de referência)
  - pontos de atenção para a LLM verificar
  - alertas automáticos
"""

from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# TIPOS DE DOCUMENTOS E SEUS CAMPOS CRÍTICOS (GRIFADOS NOS MODELOS)
# ============================================================================

DOCUMENT_TYPES = {

    # ---- 1. FATURA SABESP (ÁGUA/ESGOTO) ----
    "fatura_sabesp": {
        "nome": "Fatura Sabesp (Água/Esgoto)",
        "prefixo_arquivo": "1",
        "keywords_alta": ["sabesp", "saneamento básico", "hidrômetro"],
        "keywords_media": ["água", "esgoto", "consumo m³", "tarifa de água",
                           "coleta de esgoto", "rgi",
                           # metadados GoSati
                           "agua e esgoto", "consumo de agua"],
        "campos_grifados": {
            "numero_rgi": "Número RGI / código do cliente",
            "endereco": "Endereço completo do imóvel",
            "referencia": "Mês/ano de referência da fatura",
            "vencimento": "Data de vencimento",
            "valor_total": "Valor total a pagar (R$)",
            "consumo_m3": "Consumo medido em m³",
            "valor_agua": "Valor cobrado pela água",
            "valor_esgoto": "Valor cobrado pelo esgoto",
            "categoria": "Categoria tarifária (residencial/comercial/industrial)",
            "numero_hidrometro": "Número do hidrômetro",
            "leitura_anterior": "Leitura anterior do hidrômetro",
            "leitura_atual": "Leitura atual do hidrômetro",
            "multa_juros": "Multa e/ou juros (se houver)",
        },
        "verificacoes": [
            "Consumo muito acima ou abaixo da média pode indicar vazamento ou erro de leitura",
            "Verificar se a categoria tarifária está correta para o tipo de imóvel",
            "Conferir se há cobrança mínima sendo aplicada",
            "Verificar proporcionalidade água x esgoto (geralmente esgoto = 100% da água)",
        ],
    },

    # ---- 2. FATURA ENEL / ELETROPAULO (ENERGIA) ----
    "fatura_enel": {
        "nome": "Fatura Enel/Eletropaulo (Energia Elétrica)",
        "prefixo_arquivo": "2",
        "keywords_alta": ["enel", "eletropaulo", "distribuidora de energia"],
        "keywords_media": ["kwh", "consumo kwh", "bandeira tarifária", "iluminação pública",
                           "energia elétrica", "tusd", "te ", "icms energia",
                           "classe de fornecimento",
                           # metadados GoSati
                           "consumo energia", "energia eletrica"],
        "campos_grifados": {
            "numero_instalacao": "Número da instalação / unidade consumidora",
            "numero_cliente": "Número do cliente",
            "endereco": "Endereço da unidade consumidora",
            "referencia": "Mês/ano de referência",
            "vencimento": "Data de vencimento",
            "valor_total": "Valor total a pagar (R$)",
            "consumo_kwh": "Consumo em kWh no período",
            "tarifa_kwh": "Valor da tarifa por kWh",
            "bandeira_tarifaria": "Bandeira tarifária vigente (verde/amarela/vermelha)",
            "valor_tusd": "Valor TUSD (Tarifa de Uso do Sistema de Distribuição)",
            "valor_te": "Valor TE (Tarifa de Energia)",
            "cosip": "Contribuição de Iluminação Pública (COSIP/CIP)",
            "icms": "Valor do ICMS",
            "pis_cofins": "Valores de PIS e COFINS",
            "tipo_fornecimento": "Tipo (monofásico/bifásico/trifásico)",
            "leitura_anterior": "Leitura anterior do medidor",
            "leitura_atual": "Leitura atual do medidor",
            "demanda_contratada": "Demanda contratada (se aplicável)",
            "multa_juros": "Multa e/ou juros (se houver)",
        },
        "verificacoes": [
            "Consumo kWh: variação acima de 20% do mês anterior requer atenção",
            "Verificar bandeira tarifária — custo extra pode ser significativo",
            "Conferir se COSIP está correto para o porte do condomínio",
            "Verificar se há demanda contratada e se está adequada ao consumo",
            "ICMS e PIS/COFINS devem estar discriminados — verificar alíquotas",
        ],
    },

    # ---- 3. NOTA FISCAL DE SERVIÇO SP ----
    "nota_fiscal_sp": {
        "nome": "Nota Fiscal de Serviço (Município de SP)",
        "prefixo_arquivo": "3",
        "keywords_alta": ["nfs-e", "nota fiscal de serviço", "prefeitura de são paulo",
                          "prefeitura do município de são paulo"],
        "keywords_media": ["iss", "prestador", "tomador", "código de verificação",
                           "imposto sobre serviço", "são paulo", "cnpj prestador",
                           # metadados GoSati (historico contém "NFE NNNNN" ou "NF.: NNNNN")
                           "nfe ", "nf.:", "serv."],
        "campos_grifados": {
            "numero_nf": "Número da Nota Fiscal",
            "data_emissao": "Data de emissão",
            "codigo_verificacao": "Código de verificação da NFS-e",
            "prestador_razao": "Razão social do prestador",
            "prestador_cnpj": "CNPJ do prestador",
            "prestador_inscricao": "Inscrição municipal do prestador",
            "tomador_razao": "Razão social do tomador (condomínio)",
            "tomador_cnpj": "CNPJ do tomador",
            "descricao_servico": "Descrição detalhada do serviço prestado",
            "codigo_servico": "Código do serviço (CNAE ou código municipal)",
            "valor_servico": "Valor total do serviço (R$)",
            "base_calculo": "Base de cálculo do ISS",
            "aliquota_iss": "Alíquota do ISS (%)",
            "valor_iss": "Valor do ISS",
            "iss_retido": "ISS retido na fonte? (sim/não)",
            "valor_deducoes": "Valor de deduções (se houver)",
            "valor_liquido": "Valor líquido da NF",
            "ir_retido": "IR retido na fonte (se aplicável)",
            "inss_retido": "INSS retido (se aplicável)",
        },
        "verificacoes": [
            "Conferir se o CNPJ do tomador corresponde ao condomínio correto",
            "Verificar se o ISS foi retido quando deveria (serviços de SP para SP)",
            "Validar código de verificação se possível",
            "Verificar se a alíquota de ISS está correta para o tipo de serviço",
            "Conferir se há retenções federais (IR, INSS, PIS/COFINS/CSLL)",
            "Descrição do serviço deve ser detalhada e corresponder ao contrato",
        ],
    },

    # ---- 4A. NOTA FISCAL FORA DE SP ----
    "nota_fiscal_fora_sp": {
        "nome": "Nota Fiscal de Serviço (Fora de SP)",
        "prefixo_arquivo": "4",
        "keywords_alta": ["nota fiscal", "nfs-e"],
        "keywords_media": ["prestador", "tomador", "iss", "serviço"],
        "keywords_negativos": ["são paulo", "prefeitura de são paulo", "prefeitura do município de são paulo"],
        "campos_grifados": {
            "numero_nf": "Número da Nota Fiscal",
            "data_emissao": "Data de emissão",
            "municipio_emissao": "Município de emissão (CRÍTICO: deve ser fora de SP)",
            "uf_emissao": "UF do município de emissão",
            "prestador_razao": "Razão social do prestador",
            "prestador_cnpj": "CNPJ do prestador",
            "prestador_municipio": "Município do prestador",
            "tomador_razao": "Razão social do tomador",
            "tomador_cnpj": "CNPJ do tomador",
            "descricao_servico": "Descrição do serviço",
            "valor_servico": "Valor do serviço (R$)",
            "aliquota_iss": "Alíquota ISS do município de origem",
            "valor_iss": "Valor do ISS",
            "iss_retido": "ISS retido na fonte?",
            "local_prestacao": "Local onde o serviço foi efetivamente prestado",
            "valor_liquido": "Valor líquido",
        },
        "verificacoes": [
            "CRÍTICO: Confirmar que o município de emissão é realmente fora de SP",
            "Verificar onde o serviço foi PRESTADO (pode haver incidência de ISS em SP)",
            "Se serviço prestado em SP por empresa de fora, pode haver retenção de ISS pelo tomador",
            "Conferir se há necessidade de emitir NFTS (Nota Fiscal do Tomador)",
            "Verificar alíquota de ISS do município — varia entre 2% e 5%",
        ],
    },

    # ---- 4B. MODELO NFTS ----
    "modelo_nfts": {
        "nome": "NFTS - Nota Fiscal Tomador de Serviço",
        "prefixo_arquivo": "4",
        "keywords_alta": ["nfts", "nota fiscal tomador", "nota do tomador"],
        "keywords_media": ["tomador de serviço", "serviço tomado", "retenção iss",
                           "declaração de serviço"],
        "campos_grifados": {
            "numero_nfts": "Número da NFTS",
            "data_emissao": "Data de emissão da NFTS",
            "prestador_razao": "Razão social do prestador (de fora de SP)",
            "prestador_cnpj": "CNPJ do prestador",
            "prestador_municipio": "Município do prestador",
            "tomador_razao": "Razão social do tomador (condomínio)",
            "tomador_cnpj": "CNPJ do tomador",
            "nf_origem_numero": "Número da NF de origem (do prestador)",
            "descricao_servico": "Descrição do serviço tomado",
            "codigo_servico": "Código do serviço",
            "valor_servico": "Valor do serviço (R$)",
            "aliquota_iss": "Alíquota do ISS retido",
            "valor_iss_retido": "Valor do ISS retido na fonte",
        },
        "verificacoes": [
            "NFTS deve existir quando há NF de prestador de fora de SP",
            "Valor do serviço na NFTS deve bater com a NF de origem",
            "ISS retido deve estar correto conforme código do serviço",
            "Verificar se o código de serviço está correto",
            "Cruzar NFTS com a NF de origem correspondente",
        ],
    },

    # ---- 5. DESPESA COM CÓPIAS ----
    "despesa_copias": {
        "nome": "Despesa com Cópias/Impressões",
        "prefixo_arquivo": "5",
        "keywords_alta": ["cópia", "cópias", "impressão", "reprografia"],
        "keywords_media": ["xerox", "quantidade de cópias", "locação de equipamento",
                           "impressões", "multifuncional", "copiadora",
                           # metadados GoSati
                           "despesa com copias", "copias e impressoes"],
        "campos_grifados": {
            "fornecedor": "Nome/Razão social do fornecedor",
            "cnpj_fornecedor": "CNPJ do fornecedor",
            "data_documento": "Data do documento/fatura",
            "periodo_referencia": "Período de referência",
            "qtd_copias_pb": "Quantidade de cópias P&B",
            "valor_unitario_pb": "Valor unitário cópia P&B",
            "qtd_copias_color": "Quantidade de cópias coloridas",
            "valor_unitario_color": "Valor unitário cópia colorida",
            "valor_locacao": "Valor de locação do equipamento (se houver)",
            "valor_excedente": "Valor de excedente (se houver)",
            "valor_total": "Valor total (R$)",
            "equipamento": "Modelo do equipamento",
            "numero_serie": "Número de série",
            "leitura_anterior": "Contador/leitura anterior",
            "leitura_atual": "Contador/leitura atual",
        },
        "verificacoes": [
            "Verificar se quantidade de cópias está dentro da franquia contratada",
            "Conferir se o valor unitário corresponde ao contrato vigente",
            "Calcular se (leitura_atual - leitura_anterior) = quantidade cobrada",
            "Verificar se há cobrança de excedente e se está correta",
        ],
    },

    # ---- 6A. BALANCETE / PRESTAÇÃO DE CONTAS ----
    "balancete": {
        "nome": "Balancete / Prestação de Contas",
        "prefixo_arquivo": "6",
        "keywords_alta": ["balancete", "prestação de contas", "demonstrativo financeiro"],
        "keywords_media": ["demonstrativo", "receitas", "despesas", "saldo",
                           "previsão orçamentária", "fundo reserva", "inadimplência",
                           "ordinária", "extraordinária"],
        "keywords_negativos": ["folha de pagamento da rotina", "vencimentos", "descontos",
                               "salario base", "adiantamento quinz"],
        "campos_grifados": {
            "condominio": "Nome do condomínio",
            "cnpj": "CNPJ do condomínio",
            "competencia": "Mês/ano de competência",
            "receita_ordinaria": "Total de receitas ordinárias (R$)",
            "receita_extraordinaria": "Total de receitas extraordinárias (R$)",
            "receita_total": "Receita total (R$)",
            "despesa_total": "Despesa total (R$)",
            "saldo_periodo": "Saldo do período (receita - despesa)",
            "saldo_anterior": "Saldo do período anterior",
            "saldo_acumulado": "Saldo acumulado final",
            "fundo_reserva_saldo": "Saldo do fundo de reserva",
            "inadimplencia_valor": "Valor total de inadimplência (R$)",
            "inadimplencia_percentual": "Percentual de inadimplência (%)",
            "categorias_despesa": "Detalhamento por categoria de despesa",
            "previsao_orcamentaria": "Previsão orçamentária vs realizado",
        },
        "verificacoes": [
            "Saldo final deve bater: saldo_anterior + receitas - despesas",
            "Inadimplência acima de 15% é alerta vermelho",
            "Comparar despesa realizada vs previsão orçamentária",
            "Verificar se fundo de reserva está sendo alimentado corretamente",
            "Cada categoria de despesa deve ter comprovante correspondente",
        ],
    },

    # ---- 6B. FOLHA ANALÍTICA (MODELO ANALÍTICO DE PAGAMENTO) ----
    "folha_analitica": {
        "nome": "Folha de Pagamento Analítica (Modelo Analítico)",
        "prefixo_arquivo": "6",
        "keywords_alta": ["folha de pagamento da rotina", "modelo analitico",
                          "modelo analítico"],
        "keywords_media": ["adiantamento quinz", "vencimentos", "descontos", "bases",
                           "salario base", "salário base", "cod.func", "admissao",
                           "admissão", "liquido", "líquido", "inss", "fgts", "irrf",
                           "pis a recolher", "gps a recolher"],
        "keywords_negativos": ["balancete", "receitas ordinárias", "fundo reserva",
                               "inadimplência"],
        "campos_grifados": {
            "empresa_codigo": "Código da empresa/condomínio",
            "empresa_nome": "Nome do edifício/condomínio",
            "cnpj": "CNPJ do condomínio",
            "mes_base": "Mês base / competência",
            "tipo_folha": "Tipo (mensal, adiantamento quinz., 13° 1ª parcela, 13° 2ª parcela)",
            "funcionarios": "Lista de funcionários com detalhes individuais",
            "total_vencimentos": "Soma total de vencimentos brutos",
            "total_descontos": "Soma total de descontos",
            "total_liquido": "Soma total líquido a pagar",
        },
        "campos_por_funcionario": {
            "nome": "Nome completo do colaborador",
            "cargo": "Cargo/função",
            "admissao": "Data de admissão",
            "salario_base": "Salário base (R$)",
            "vencimentos": "Total de vencimentos",
            "descontos": "Total de descontos",
            "liquido": "Valor líquido",
            "inss": "INSS descontado",
            "irrf": "IRRF retido",
            "fgts": "FGTS (base + valor)",
            "base_inss": "Base de cálculo INSS",
            "base_fgts": "Base de cálculo FGTS",
            "base_irrf": "Base de cálculo IRRF",
        },
        "verificacoes": [
            "Total líquido = total vencimentos - total descontos",
            "Para cada funcionário: líquido = vencimentos - descontos",
            "Verificar consistência com relação bancária (mesmo período, mesmos valores)",
            "Valor total deve conferir com lançamento na prestação de contas",
            "Valor de GPS no analítico deve conferir com GPS paga",
        ],
    },

    # ---- 6C. RELAÇÃO BANCÁRIA (DISTRIBUIÇÃO DE FOLHA) ----
    "relacao_bancaria": {
        "nome": "Relação Bancária / Distribuição de Pagamento",
        "prefixo_arquivo": "6",
        "keywords_alta": ["relação bancária", "relacao bancaria",
                          "relação de pagamento", "relacao de pagamento"],
        "keywords_media": ["cod.func", "agência", "agencia", "conta corrente",
                           "cpf", "total por estabelecimento", "total por empresa",
                           "folha de pagamento", "adiantamento quinz"],
        "campos_grifados": {
            "empresa": "Nome da empresa/condomínio",
            "cnpj": "CNPJ do condomínio",
            "referencia": "Mês de referência do pagamento",
            "tipo_pagamento": "Tipo (Folha de Pagamento, Adiantamento Quinz., etc.)",
            "funcionarios": "Lista de funcionários com dados bancários",
            "total_geral": "Valor total da relação (R$)",
        },
        "campos_por_funcionario": {
            "codigo": "Código do funcionário",
            "nome": "Nome completo",
            "cpf": "CPF do funcionário",
            "agencia": "Número da agência bancária",
            "conta_corrente": "Número da conta corrente",
            "valor": "Valor a ser creditado (R$)",
        },
        "verificacoes": [
            "Total da relação deve conferir com total líquido da folha analítica",
            "Cada funcionário da folha deve constar na relação bancária",
            "Valores individuais devem bater com líquido da folha analítica",
            "Verificar se CPFs são válidos",
            "Conferir se dados bancários estão completos (agência + conta)",
        ],
    },

    # ---- 7. FOLHA DE PAGAMENTO ----
    "folha_pagamento": {
        "nome": "Folha de Pagamento",
        "prefixo_arquivo": "7",
        "keywords_alta": ["folha de pagamento", "folha pagamento rotina",
                          "segunda parcela 13o", "primeira parcela 13o"],
        "keywords_media": ["vencimentos", "descontos", "salário", "salario",
                           "inss", "fgts", "irrf", "décimo terceiro", "13o salario",
                           "holerite", "contracheque", "pis a recolher",
                           "base inss", "líquido", "liquido",
                           # metadados GoSati
                           "salarios", "adiantamento salarial",
                           "adiantamento quinzenal", "salarios e ordenados"],
        "campos_grifados": {
            "empresa_codigo": "Código da empresa/condomínio",
            "empresa_nome": "Nome do edifício/condomínio",
            "cnpj": "CNPJ do condomínio",
            "competencia": "Mês base / competência",
            "tipo_folha": "Tipo da folha (mensal, 13° 1ª parcela, 13° 2ª parcela, férias, rescisão)",
            "total_funcionarios": "Quantidade de funcionários na folha",
            "total_vencimentos": "Soma total de vencimentos brutos",
            "total_descontos": "Soma total de descontos",
            "total_liquido": "Soma total líquido a pagar",
            "total_inss_empresa": "Total INSS patronal",
            "total_fgts": "Total FGTS a recolher",
            "total_irrf": "Total IRRF retido",
            "total_pis": "Total PIS a recolher",
            "funcionarios": "Lista de funcionários com detalhes individuais",
        },
        "campos_por_funcionario": {
            "matricula": "Código/matrícula do colaborador",
            "nome": "Nome completo",
            "cargo": "Cargo/função",
            "nivel": "Nível/categoria",
            "admissao": "Data de admissão",
            "salario_base": "Salário base (R$)",
            "vencimentos_bruto": "Total de vencimentos brutos",
            "descontos_total": "Total de descontos",
            "liquido": "Valor líquido",
            "inss_funcionario": "INSS descontado do funcionário",
            "irrf": "IRRF retido",
            "fgts": "FGTS (base + valor)",
            "base_inss": "Base de cálculo INSS",
            "base_fgts": "Base de cálculo FGTS",
            "base_irrf": "Base de cálculo IRRF",
            "pis_recolher": "PIS a recolher",
            "gps_recolher": "GPS a recolher",
        },
        "verificacoes": [
            "Total líquido = total vencimentos - total descontos",
            "Para cada funcionário: líquido = vencimentos - descontos",
            "Verificar se INSS está na alíquota correta conforme faixa salarial",
            "FGTS deve ser 8% do salário bruto (conferir base)",
            "13° salário: 1ª parcela = 50% do salário; 2ª parcela = salário - 1ª parcela - descontos",
            "Verificar se há funcionários admitidos/demitidos no período",
            "Conferir se cargo/nível corresponde ao salário (piso da categoria)",
        ],
    },

    # ---- 8. DARF (GUIA DE TRIBUTOS FEDERAIS) ----
    "darf": {
        "nome": "DARF - Documento de Arrecadação de Receitas Federais",
        "prefixo_arquivo": "",
        "keywords_alta": ["darf", "documento de arrecadação de receitas federais"],
        "keywords_media": ["receita federal", "código de receita", "período de apuração",
                           # metadados GoSati
                           "irrf s/ nfs", "irrf s/ nf", "csll/cofins/pis",
                           "csll", "cofins", "pis s/", "irrf"],
        "keywords_negativos": ["sabesp", "enel", "folha de pagamento"],
        "campos_grifados": {
            "periodo_apuracao": "Período de apuração",
            "codigo_receita": "Código da receita",
            "valor_principal": "Valor principal (R$)",
            "multa": "Multa (se houver)",
            "juros": "Juros (se houver)",
            "valor_total": "Valor total (R$)",
            "cnpj": "CNPJ do contribuinte",
            "data_vencimento": "Data de vencimento",
        },
        "verificacoes": [
            "Código da receita deve corresponder ao tributo correto",
            "Valor deve conferir com o lançamento na prestação de contas",
            "Período de apuração deve ser consistente com a competência",
        ],
    },

    # ---- 9. GPS (GUIA DA PREVIDÊNCIA SOCIAL) ----
    "gps": {
        "nome": "GPS - Guia da Previdência Social",
        "prefixo_arquivo": "",
        "keywords_alta": ["gps", "guia da previdência social", "previdência social"],
        "keywords_media": ["inss patronal", "contribuição previdenciária",
                           "código de pagamento",
                           # metadados GoSati
                           "gps -", "inss s/", "inss -", "inss empresa"],
        "keywords_negativos": ["sabesp", "enel"],
        "campos_grifados": {
            "competencia": "Mês/ano de competência",
            "codigo_pagamento": "Código de pagamento",
            "valor_inss": "Valor INSS (R$)",
            "outras_entidades": "Outras entidades (R$)",
            "multa_juros": "Multa e juros (se houver)",
            "valor_total": "Valor total (R$)",
            "cnpj": "CNPJ do contribuinte",
        },
        "verificacoes": [
            "Valor deve corresponder ao total de INSS da folha analítica",
            "Se GPS diverge da folha, verificar se há relatório de autônomos",
            "Competência deve bater com o período da folha de pagamento",
        ],
    },

    # ---- 10. GUIA FGTS / SEFIP ----
    "guia_fgts": {
        "nome": "Guia FGTS / SEFIP / GFD",
        "prefixo_arquivo": "",
        "keywords_alta": ["sefip", "guia fgts", "fgts digital", "gfd"],
        "keywords_media": ["fundo de garantia", "fgts a recolher",
                           # metadados GoSati
                           "fgts -", "fgts comp", "recolhimento fgts"],
        "keywords_negativos": ["sabesp", "enel", "folha de pagamento da rotina"],
        "campos_grifados": {
            "competencia": "Mês/ano de competência",
            "valor_fgts": "Valor FGTS a recolher (R$)",
            "num_funcionarios": "Número de funcionários",
            "cnpj": "CNPJ do empregador",
        },
        "verificacoes": [
            "Valor deve ser 8% do total de salários brutos da folha",
            "A ordem dos documentos deve ser: Comprovante, Guia, SEFIP",
            "Conferir se número de funcionários bate com a folha analítica",
        ],
    },

    # ---- 11. DAMSP (ARRECADAÇÃO MUNICIPAL SP / ISS) ----
    "damsp": {
        "nome": "DAMSP - Documento de Arrecadação Municipal SP",
        "prefixo_arquivo": "",
        "keywords_alta": ["damsp", "documento de arrecadação do município"],
        "keywords_media": ["arrecadação municipal", "iss retido",
                           # metadados GoSati
                           "iss - nf", "iss s/ nf", "iss -"],
        "keywords_negativos": ["sabesp", "enel", "darf"],
        "campos_grifados": {
            "numero_nf": "Número da NF referente",
            "valor_iss": "Valor do ISS (R$)",
            "cnpj_prestador": "CNPJ do prestador",
            "competencia": "Período de competência",
        },
        "verificacoes": [
            "Valor do ISS deve conferir com retenção da NF correspondente",
            "Verificar se o ISS corresponde à alíquota correta do serviço",
        ],
    },

    # ---- 12. COMPROVANTE DE PAGAMENTO BANCÁRIO ----
    "comprovante_bancario": {
        "nome": "Comprovante de Pagamento Bancário",
        "prefixo_arquivo": "",
        "keywords_alta": ["comprovante de pagamento", "pag-for", "pagamento eletrônico"],
        "keywords_media": ["ted", "pix", "doc", "transferência bancária",
                           "internet banking", "beneficiário", "favorecido",
                           # metadados GoSati
                           "pagamentos on line", "pgto on line", "pagto"],
        "keywords_negativos": ["sabesp", "enel", "nota fiscal de serviço",
                               "folha de pagamento da rotina"],
        "campos_grifados": {
            "tipo_pagamento": "Tipo (TED, PIX, DOC, boleto, Pag-For)",
            "valor": "Valor pago (R$)",
            "data_pagamento": "Data do pagamento",
            "beneficiario": "Nome/razão social do beneficiário",
            "cnpj_beneficiario": "CNPJ/CPF do beneficiário",
            "banco_destino": "Banco de destino",
        },
        "verificacoes": [
            "Valor pago deve conferir com o valor do lançamento",
            "Beneficiário deve corresponder ao emissor da NF",
            "Data de pagamento deve ser compatível com o vencimento",
        ],
    },

    # ---- 13. CONTRIBUIÇÃO SINDICAL / SINDIFICIOS ----
    "sindificios": {
        "nome": "Contribuição Sindical / Sindificios",
        "prefixo_arquivo": "",
        "keywords_alta": ["sindificios", "sindicato", "contribuição sindical"],
        "keywords_media": ["contribuição assistencial", "relação de contribuição",
                           # metadados GoSati
                           "contrib. assistencial", "contrib sindical",
                           "taxa sindical"],
        "campos_grifados": {
            "referencia": "Período de referência",
            "valor_total": "Valor total da contribuição (R$)",
            "entidade_sindical": "Nome da entidade sindical",
        },
        "verificacoes": [
            "Deve conter a referência no histórico do lançamento",
            "Além do boleto, deve conter a Relação de Contribuição Assistencial",
            "Verificar se o valor confere com o número de funcionários",
        ],
    },
}


# Ordem de prioridade na classificação (mais específico primeiro)
CLASSIFICACAO_PRIORIDADE = [
    "fatura_sabesp",
    "fatura_enel",
    "modelo_nfts",        # antes de nota_fiscal para não confundir
    "damsp",              # ISS municipal, antes de nota_fiscal
    "nota_fiscal_sp",
    "nota_fiscal_fora_sp",
    "despesa_copias",
    "sindificios",
    "guia_fgts",          # antes de darf (mais específico)
    "gps",                # antes de darf
    "darf",
    "folha_analitica",    # antes de folha_pagamento (mais específico)
    "relacao_bancaria",   # antes de folha_pagamento (mais específico)
    "folha_pagamento",
    "comprovante_bancario",  # genérico, por último
    "balancete",
]


# Pré-calcular score máximo teórico de cada tipo para normalização de confiança
for _tipo_id, _config in DOCUMENT_TYPES.items():
    _config["score_maximo"] = (
        len(_config.get("keywords_alta", [])) * 3.0
        + len(_config.get("keywords_media", [])) * 1.0
    )
