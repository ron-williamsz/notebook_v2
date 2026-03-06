# Integração API BD FOR ALL - Condomínios

**Base URL:** `https://bdforall.grupozangari.com.br` (produção) ou `http://localhost:8383` (local)

---

## 1. Autenticação

Todas as rotas de condomínios exigem **token JWT** no header.

### Login

```
POST /api/auth/login?email={email}&senha={senha}
```

**Parâmetros (query string):**
| Parâmetro | Tipo   | Obrigatório | Descrição            |
|-----------|--------|-------------|----------------------|
| email     | string | sim         | Email do usuário     |
| senha     | string | sim         | Senha do usuário     |

**Resposta (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "senha_temporaria": false,
  "user": {
    "id": 1,
    "email": "usuario@email.com",
    "nome": "Nome do Usuário",
    "is_admin": true,
    "perfis": ["Administrador"],
    "perfil_principal": "Administrador"
  }
}
```

> **IMPORTANTE:** Se `senha_temporaria: true`, o usuário precisa trocar a senha antes de usar o sistema. Veja a seção "Reset de Senha" abaixo.

### Usar o token

Todas as requisições autenticadas devem incluir o header:

```
Authorization: Bearer {access_token}
```

---

## 2. Listar Condomínios

```
GET /api/condominios
```

**Header obrigatório:**
```
Authorization: Bearer {access_token}
```

**Parâmetros (query string, todos opcionais):**
| Parâmetro | Tipo   | Padrão | Descrição                              |
|-----------|--------|--------|----------------------------------------|
| skip      | int    | 0      | Registros para pular (paginação)       |
| limit     | int    | 100    | Máximo de registros (1 a 500)          |
| gerente   | string | -      | Filtrar por nome do gerente            |
| status    | string | -      | Filtrar por status (ativo/inativo)     |
| busca     | string | -      | Buscar por nome, código ou CNPJ        |

**Resposta (200):**
```json
{
  "total": 250,
  "skip": 0,
  "limit": 100,
  "data": [
    {
      "codigo_ahreas": "001234",
      "nome": "Condomínio Residencial Exemplo",
      "cnpj": "12.345.678/0001-90",
      "endereco": "Rua Exemplo",
      "numero": "100",
      "bairro": "Centro",
      "cidade": "São Paulo",
      "uf": "SP",
      "cep": "01000-000",
      "total_unidades": 120,
      "email": "cond@email.com",
      "telefone": "(11) 1234-5678",
      "gerente_nome": "João Silva",
      "nome_sindico": "Maria Santos",
      "email_sindico": "sindico@email.com",
      "telefone_sindico": "(11) 9876-5432",
      "status": "ativo",
      "ativo": 1,
      "data_ultima_sync_api": "2026-02-05 10:00:00",
      "data_ultima_sinc_soap": "2026-02-05 10:00:00"
    }
  ]
}
```

**Os campos que você precisa são:**
| Campo          | Tipo   | Descrição                  |
|----------------|--------|----------------------------|
| codigo_ahreas  | string | Código único do condomínio  |
| nome           | string | Nome do condomínio          |

---

## 3. Exemplos Práticos

### JavaScript (fetch)

```javascript
// 1. Login
const loginResponse = await fetch('http://localhost:8383/api/auth/login?email=usuario@email.com&senha=minhasenha', {
  method: 'POST'
});
const { access_token, senha_temporaria } = await loginResponse.json();

// 2. Verificar se precisa trocar senha
if (senha_temporaria) {
  // Abrir tela de troca de senha obrigatória
  return;
}

// 3. Buscar condomínios (código + nome)
const response = await fetch('http://localhost:8383/api/condominios?limit=500', {
  headers: {
    'Authorization': `Bearer ${access_token}`
  }
});
const { data } = await response.json();

// 4. Extrair apenas código e nome
const condominios = data.map(c => ({
  codigo: c.codigo_ahreas,
  nome: c.nome
}));

console.log(condominios);
// [{ codigo: "001234", nome: "Cond. Residencial Exemplo" }, ...]
```

### Python (requests)

```python
import requests

BASE_URL = "http://localhost:8383"

# 1. Login
login = requests.post(f"{BASE_URL}/api/auth/login", params={
    "email": "usuario@email.com",
    "senha": "minhasenha"
})
token = login.json()["access_token"]

# 2. Buscar condomínios
headers = {"Authorization": f"Bearer {token}"}
resp = requests.get(f"{BASE_URL}/api/condominios", params={"limit": 500}, headers=headers)

# 3. Extrair código e nome
condominios = [
    {"codigo": c["codigo_ahreas"], "nome": c["nome"]}
    for c in resp.json()["data"]
]
```

### cURL

```bash
# Login
TOKEN=$(curl -s -X POST "http://localhost:8383/api/auth/login?email=usuario@email.com&senha=minhasenha" | jq -r '.access_token')

# Listar condomínios
curl -s "http://localhost:8383/api/condominios?limit=500" \
  -H "Authorization: Bearer $TOKEN" | jq '.data[] | {codigo: .codigo_ahreas, nome: .nome}'
```

---

## 4. Reset de Senha (para o frontend implementar)

### Fluxo

```
Usuário esqueceu senha
    → POST /api/auth/forgot-password {"email": "..."}
    → Recebe código de 4 dígitos no email
    → Faz login com email + código de 4 dígitos
    → Resposta vem com senha_temporaria: true
    → Frontend abre tela obrigatória de troca
    → PATCH /api/usuarios/{id}/senha {"nova_senha": "..."}
    → Pronto
```

### Solicitar reset

```
POST /api/auth/forgot-password
Content-Type: application/json

{"email": "usuario@email.com"}
```

**Resposta (200):** sempre genérica por segurança
```json
{"success": true, "message": "Se o email estiver cadastrado, você receberá uma senha temporária"}
```

**Resposta (429):** rate limit (2 min entre tentativas)
```json
{"detail": "Aguarde 2 minutos antes de solicitar outro reset de senha"}
```

### Alterar senha

```
PATCH /api/usuarios/{id}/senha
Authorization: Bearer {access_token}
Content-Type: application/json

{"nova_senha": "novaSenhaSegura123"}
```

**Resposta (200):**
```json
{"success": true, "message": "Senha do usuário usuario@email.com alterada com sucesso"}
```

---

## 5. Códigos de Erro

| HTTP  | Significado                           |
|-------|---------------------------------------|
| 200   | Sucesso                               |
| 401   | Token inválido/expirado ou credenciais erradas |
| 403   | Sem permissão                         |
| 404   | Recurso não encontrado                |
| 422   | Parâmetros inválidos                  |
| 429   | Muitas tentativas (rate limit)        |
| 500   | Erro interno do servidor              |

---

## 6. Resumo Rápido

| O que preciso fazer?       | Endpoint                          | Auth?  |
|----------------------------|-----------------------------------|--------|
| Fazer login                | `POST /api/auth/login`            | Não    |
| Listar condomínios         | `GET /api/condominios`            | Sim    |
| Esqueci minha senha        | `POST /api/auth/forgot-password`  | Não    |
| Alterar senha              | `PATCH /api/usuarios/{id}/senha`  | Sim    |
