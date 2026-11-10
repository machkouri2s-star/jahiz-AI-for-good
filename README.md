# Jahiz

Prototype multi-agents pour la préparation fonctionnelle de pèlerins âgés au Hajj.
Tout le profil et les scénarios sont synthétiques. Le système ne fait ni validation
clinique, ni diagnostic, ni fatwa; le statut « prêt » n'est pas une aptitude médicale.

## Structure

- `agents/` : Coordinator, Policy & Legal Adviser, DPA Agent et messages typés.
- `rules/` : moteur déterministe R1-R6, sans dépendance au LLM.
- `kb/` : notes TXT de démonstration et sources PDF/TXT ajoutées pour l'ingestion.
- `audit/` : journal JSONL et lecture avec signalement des lignes invalides.
- `data/` : profil fictif et programme synthétique de 14 jours.
- `app.py` : simulateur pèlerin, tableau superviseur, vue agence et stages de démo.
- `demo_scenarios.py` : rejoue les quatre scénarios en console.
- `tests/` : tests pytest des règles, de la gouvernance, du RAG et des scénarios.

## Installation

Python 3.11 est recommandé. Depuis ce dossier :

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Le dossier `kb/` contient des notes de démonstration non autoritatives. Ajoutez-y des
fichiers PDF ou TXT validés; l'ingestion Chroma conserve les références de document,
d'article ou de page. Les fichiers persistants sont créés dans `runtime/` par défaut.
`JAHIZ_DATA_DIR` permet de choisir un autre emplacement.

## Lancement

```powershell
$env:ANTHROPIC_API_KEY = "votre-cle"
# Facultatif : $env:ANTHROPIC_MODEL = "claude-haiku-5-5"
streamlit run app.py
```

Sans clé Anthropic, l'adviser renvoie des extraits de la KB avec leurs citations. Les
règles de sécurité restent déterministes et n'appellent jamais le LLM. Avec une clé,
Claude ne peut sélectionner que des citations exactes; le prototype valide le JSON et
vérifie chaque citation par correspondance littérale avant de l'afficher.

Rejouer les quatre scénarios en console :

```powershell
python demo_scenarios.py
```

## Tests

```powershell
pytest -q
```

Les agents et l'interface journalisent les actions dans `runtime/audit.jsonl`.
Le superviseur humain valide toute augmentation de charge; la vue agence ne montre
que des indicateurs agrégés, avec suppression des petits groupes.
