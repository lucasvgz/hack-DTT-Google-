# Contrat d'API front ↔ back — Tickmark

Le front n'appelle le back-end que depuis **`js/api.js`**. Pour brancher l'API, renseigner `API_BASE_URL` dans `js/config.js` (ou ajouter `?api=https://mon-service.run.app` à l'URL, pour une session).

Tant que `API_BASE_URL` est vide, le front utilise son **moteur local** (`js/diff-engine.js`), qui renvoie **exactement** le format ci-dessous. Le back-end peut donc reprendre ce format tel quel, et l'UI fonctionnera sans modification.

Tous les appels utilisent `credentials: "include"` : la session est portée par un cookie `HttpOnly; Secure; SameSite=Strict` posé par le back-end (SSO). Le back-end doit autoriser l'origine GitHub Pages en CORS, avec `Access-Control-Allow-Credentials: true`.

---

## 1. `POST /api/v1/comparisons` : lancer l'analyse

`multipart/form-data`

| Champ | Type | Description |
|---|---|---|
| `clientId` | string | `bnp`, `loreal`, `orange`, `socgen`, `kering` (cf. `js/data.js`) |
| `before` | file (PDF) | Version précédente (N-1) |
| `after` | file (PDF) | Nouvelle version (N) |
| `beforeSha256` / `afterSha256` | string | Empreintes calculées côté navigateur. **Le back-end doit les recalculer et rejeter la requête (409) en cas de différence.** |

### Réponse `200`

```json
{
  "id": "cmp_8f3k2",
  "engine": "gemini-2.5-pro+rules-v1",
  "documents": {
    "before": { "text": "…texte intégral, pages séparées par \\f…", "pageCount": 2 },
    "after":  { "text": "…", "pageCount": 2 }
  },
  "differences": [
    {
      "id": "d004",
      "category": "chiffres",
      "subtype": "Montant / donnée chiffrée",
      "severity": "elevee",
      "before": "7 412",
      "after": "7 421",
      "beforeRange": [812, 817],
      "afterRange": [811, 816],
      "page": 1,
      "section": "§2 Chiffres clés consolidés",
      "context": "…Résultat net part du Groupe ……… 7 421 Endettement…",
      "rationale": "La donnée chiffrée change (7 412 → 7 421). À rapprocher de la balance.",
      "confidence": 0.98
    }
  ]
}
```

**Optionnel : `documents.before.layout` / `documents.after.layout`.** Si cette carte de positions est fournie, l'UI affiche les vraies pages PDF avec les écarts surlignés par-dessus ; sinon, elle affiche le texte. Format : `{ "pages": [ { "w": 595.3, "h": 841.9, "f": [[début, fin, x, y, largeur, corps], …] } ] }`, avec `début`/`fin` = offsets dans `text`, `x`/`y` = position de la ligne de base en points PDF (origine en bas à gauche). C'est exactement ce que produit `js/pdf-extract.js`.

**Règles importantes pour le surlignage**

- `beforeRange` / `afterRange` sont des **offsets de caractères `[début, fin)`** dans `documents.before.text` / `documents.after.text`. Le front surligne `text.slice(début, fin)`.
- Pour un **ajout**, `beforeRange` est vide (`[n, n]`) : le front affiche un curseur à cette position dans N-1. Même chose pour une **suppression** côté N.
- Les pages sont séparées par le caractère `\f` (form feed) dans `text`. Le front pagine sur ce caractère.
- `before === text.slice(...beforeRange)` doit être vrai (même chose pour `after`).
- Les écarts doivent être triés dans l'ordre du document et ne pas se chevaucher.

**Valeurs autorisées**

| Champ | Valeurs |
|---|---|
| `category` | `chiffres` · `formulation` · `ajout_suppression` · `orthographe` · `ponctuation` · `mise_en_forme` |
| `severity` | `elevee` · `moyenne` · `faible` · `info` |
| `confidence` | 0 → 1 |

**Critères objectifs de catégorisation** (appliqués dans cet ordre par le moteur local ; l'agent IA doit les respecter, voir `categorize()` dans `js/diff-engine.js`) :

1. `mise_en_forme` : identique une fois tous les blancs retirés (espaces, retours à la ligne)
2. `ponctuation` : identique une fois la ponctuation et les blancs retirés
3. `ajout_suppression` : texte présent d'un seul côté (sévérité `elevee` s'il contient des chiffres)
4. `chiffres` : les nombres (montants, %, dates, effectifs) diffèrent
5. `orthographe` : même nombre de mots, chaque mot à 2 caractères près au plus (lettre, accent, casse)
6. `formulation` : tout le reste

L'IA apporte de la valeur au-delà de ces règles sur les points suivants : `rationale` (justification lisible), détection d'**incohérences croisées** (ex. dividende 4,60 € dans les chiffres clés contre 4,50 € dans les perspectives), extraction fidèle des PDF complexes (tableaux, colonnes, OCR).

### Erreurs

`4xx` / `5xx` avec un corps `{ "error": { "message": "…" } }`. Le message est affiché tel quel à l'auditeur.

---

## 2. `PUT /api/v1/comparisons/{id}/review` : sauvegarder la revue

Appelé après chaque décision (validation, écartement, réouverture) et à la finalisation.

```json
{ "differences": [ { "id": "d004", "status": "confirmed", "note": "Erreur relative à la note 2 — corriger", "reviewedBy": "Lucas Giovinazzo", "reviewedAt": "2026-11-18T14:12:03.120Z" } ] }
```

`status` : `pending` · `confirmed` (erreur à reporter) · `dismissed` (pas une erreur). Réponse : `204`.

---

## 3. `POST /api/v1/comparisons/{id}/send` : envoyer au portail client

Le corps est le rapport : `id, sessionId, clientId, sentAt, sentBy, files{before,after}{name,size,sha256}, documents, stats{detected,errors}, errors[]`. **Seules les erreurs confirmées sont envoyées** (principe du besoin d'en connaître). Réponse : `200` avec le rapport enregistré.

---

## Exigences de sécurité côté back-end (à présenter au jury)

| Exigence | Où |
|---|---|
| Authentification SSO (Entra ID / Google Identity) et cookie `HttpOnly` | Back |
| Contrôle d'accès par dossier client (un auditeur ne voit que ses missions, un client que ses rapports) | Back |
| Recalcul des SHA-256 et rejet en cas de différence | Back |
| Chiffrement au repos (CMEK / Cloud KMS) et hébergement UE (`europe-west9`, Paris) | Infra GCP |
| Aucune réutilisation ni rétention des PDF par le modèle (configuration Vertex AI à vérifier), aucun contenu dans les logs | Back |
| Masquage des données personnelles avant l'envoi au LLM (Cloud DLP) si nécessaire | Back |
| Journal d'audit immuable (le front envoie déjà chaque événement) | Back |
| Défense contre l'injection de prompt : le texte des PDF est traité comme une donnée, sortie JSON validée par un schéma | Back |

Déjà en place côté front : CSP stricte (aucun script ni CDN tiers), vérification de la signature `%PDF-`, plafond de taille, empreintes SHA-256, journal horodaté, attestation avant finalisation et avant envoi, partage limité aux erreurs confirmées, verrouillage après inactivité, mode local sans aucune transmission.
