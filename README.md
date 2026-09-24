**# AI Email Threat Detection**

AI-powered email security platform combining machine learning, BERT-based phishing detection, and rule-based security assessment.

**---**

**## 1. Project Overview**

Traditional spam filters answer one question: *\*is this message unwanted?\** That question is not the same as *\*is this message trying to steal something?\** A well-crafted credential-harvesting email is often written to look exactly like ordinary correspondence — it is not bulk, not promotional, and a spam filter has little reason to flag it.

This project therefore runs **\*\*two independent detection pipelines\*\*** over every email:

\| Pipeline | Question it answers | Technique |

\|---|---|---|

\| Spam detection | Is this unwanted bulk mail? | CountVectorizer + Multinomial Naive Bayes |

\| Phishing detection | Is this an attempt to deceive the recipient? | Fine-tuned \`bert-base-uncased\` |

Their outputs are then combined by a **\*\*rule-based security assessment engine\*\*** which produces a single \`LOW\` / \`MEDIUM\` / \`HIGH\` risk level.

**### Critical semantic: the two classifiers are independent**

This distinction is enforced throughout the data model, the API and the UI:

\- **\*\*Spam detection ≠ phishing detection.\*\*** They are trained on different data, answer different questions, and can disagree.

\- **\*\*HAM does not imply LEGITIMATE.\*\*** A targeted phishing email is usually *\*not\** spam.

\- **\*\*SPAM does not imply PHISHING.\*\*** A marketing blast is unwanted but harmless.

All four combinations are valid and are represented distinctly:

\| Spam verdict | Phishing verdict | Example |

\|---|---|---|

\| HAM | LEGITIMATE | Ordinary work correspondence |

\| SPAM | LEGITIMATE | Retail marketing blast |

\| HAM | PHISHING | Targeted credential harvesting |

\| SPAM | PHISHING | Mass-mailed fraud campaign |

Nowhere in the system is one verdict inferred from the other.

**---**

**## 2. Key Features**

\| Capability | Technology |

\|---|---|

\| Spam detection | CountVectorizer + Multinomial Naive Bayes (scikit-learn) |

\| Phishing detection | Fine-tuned \`bert-base-uncased\` (PyTorch + Transformers) |

\| Risk assessment | Deterministic rule engine (not ML) |

\| Backend API | FastAPI |

\| Frontend | React 18 + Vite |

\| Backend testing | pytest |

\| Frontend testing | Offline component render checks (\`npm run smoke\`) |

\| API documentation | OpenAPI / Swagger (auto-generated) |

\| Model evaluation | Precision, recall, F1, F2, ROC AUC, confusion matrix |

\| Message storage | CSV-backed mailbox store (no external database) |

**---**

**## 3. System Architecture**

\`\`\`mermaid

flowchart TD

    A[Email Input] --> B[FastAPI POST /predict]

    B --> C[Spam Detector]

    B --> D[Phishing Detector]

    C --> C1[Text cleaning\<br/>CountVectorizer\<br/>Multinomial Naive Bayes]

    D --> D1[WordPiece tokenizer\<br/>Fine-tuned BERT\<br/>max_length 512]

    C1 --> C2[SPAM / HAM]

    D1 --> D2[PHISHING / LEGITIMATE]

    C2 --> E[Rule-Based Risk Engine]

    D2 --> E

    E --> F[LOW / MEDIUM / HIGH]

    F --> G[Combined JSON response]

    C2 --> G

    D2 --> G

    G --> H[Message Store\<br/>quarantine / inbox CSV]

    G --> I[React Dashboard]

    I --> J[Analyzer]

    I --> K[Overview]

    I --> L[Quarantine]

    I --> M[System Status]

\`\`\`

**---**

**## 4. End-to-End Pipeline**

\| # | Stage | What happens |

\|---|---|---|

\| 1 | Submission | Analyst submits subject + body in the Analyzer; the frontend joins them as \`subject\n\nbody\` |

\| 2 | Validation | FastAPI validates via Pydantic: non-empty, â‰¤ 20,000 characters |

\| 3 | Spam detection | Text is cleaned, vectorised against the fitted vocabulary, scored by Naive Bayes |

\| 4 | Phishing detection | Text is tokenised with WordPiece and classified by the fine-tuned BERT model |

\| 5 | Combination | Both verdicts are attached to the response as separate blocks |

\| 6 | Risk assessment | A deterministic lookup over the two booleans yields the risk level |

\| 7 | Response | FastAPI returns one structured JSON payload |

\| 8 | Storage | The message plus both verdicts is filed to the quarantine or inbox CSV |

\| 9 | Presentation | React renders the verdicts; Overview aggregates them; Quarantine lists items needing review |

Both models are loaded **\*\*once\*\*** during FastAPI startup (\`lifespan\`), not per request.

**---**

**## 5. Spam Detection**

**\*\*Model:\*\*** \`models/spam_model.pkl\` (Multinomial Naive Bayes, \`alpha=1.0\`)

**\*\*Vectorizer:\*\*** \`models/count_vectorizer.pkl\` (CountVectorizer, 5,000 features, unigrams + bigrams)

**\*\*Prediction path:\*\***

\`\`\`

raw text → clean_text() → vectorizer.transform() → model.predict()

\`\`\`

Text cleaning lowercases, strips URLs and non-alphabetic characters, then applies spaCy tokenisation, stop-word removal and lemmatisation. If the \`en_core_web_sm\` model is unavailable the service falls back to a reduced cleaner and reports the degradation through \`/health\` rather than failing.

**\*\*Outputs:\*\*** the predicted class (\`spam\` / \`ham\`), per-class probabilities from \`predict_proba\`, and **\*\*top signals\*\*** — the tokens in the message with the largest Naive Bayes log-probability gap between the two classes, weighted by frequency. These are genuine model internals, not a heuristic.

**---**

**## 6. Phishing Detection**

**\*\*Base model:\*\*** \`bert-base-uncased\`

**\*\*Fine-tuned model:\*\*** \`models/phishing_bert/\`

\| Label | Meaning |

\|---|---|

\| \`0\` | LEGITIMATE |

\| \`1\` | PHISHING |

**### Dataset**

Six public corpora (CEAS 2008, Enron, Ling, Nazario, Nigerian Fraud, SpamAssassin) were consolidated into a single balanced dataset. A seventh file, \`phishing_email.csv\`, was **\*\*excluded\*\***: its row and label counts matched the sum of the other six exactly, and its text had already been lowercased and stop-word stripped — destructive for a WordPiece tokenizer.

\| Stage | Records |

\|---|---|

\| Consolidated and deduplicated | 70,000 (35,000 / 35,000) |

\| After preprocessing | 69,974 |

\| After pre-split leakage audit | 65,525 |

\| Train / Validation / Test | 52,420 / 6,552 / 6,553 |

**\*\*Leakage control.\*\*** Three duplicate-detection layers were applied *\*before\** splitting: exact normalised text, a 200-character normalised prefix, and a rare-token signature. The third layer removed a further 4,449 near-duplicates that the first two missed — pairs whose opening lines differ but whose bodies are near-identical. Post-split verification confirmed zero overlap across all three layers.

**### Training configuration**

\| Parameter | Value |

\|---|---|

\| Max sequence length | 512 tokens (head truncation) |

\| Batch size | 8, with 4 gradient accumulation steps (effective 32) |

\| Learning rate | 2e-5, linear schedule, 10% warm-up |

\| Epochs completed | 1 (1,639 optimiser steps) |

\| Model selection | Best validation F1 |

\| Random seed | 42 |

\| Device | CPU |

Approximately 19% of emails exceed 512 tokens and are head-truncated. The full cleaned text is preserved in the dataset so an alternative truncation strategy can be evaluated later.

**---**

**## 7. Model Evaluation**

All figures below are read directly from \`reports/\`.

**### Validation results (during training, step 1,639)**

\| Metric | Value |

\|---|---|

\| Accuracy | 0.9928 |

\| Precision (phishing) | 0.9947 |

\| Recall (phishing) | 0.9906 |

\| F1 (phishing) | 0.9926 |

\| Loss | 0.0330 |

**### Final test results (held-out set, 6,553 emails)**

The test set was used **\*\*once\*\***, after training and model selection were complete.

\`\`\`

              precision    recall  f1-score   support

  LEGITIMATE     0.9882    0.9961    0.9921      3362

    PHISHING     0.9959    0.9875    0.9917      3191

    accuracy                         0.9919      6553

   macro avg     0.9920    0.9918    0.9919      6553

weighted avg     0.9919    0.9919    0.9919      6553

\`\`\`

\| Metric | Value |

\|---|---|

\| Accuracy | 0.9919 |

\| Macro F1 | 0.9919 |

\| Phishing precision | 0.9959 |

\| Phishing recall | 0.9875 |

\| Phishing F2 | 0.9891 |

\| ROC AUC | 0.9997 |

**### Confusion matrix**

\|  | Predicted LEGITIMATE | Predicted PHISHING |

\|---|---|---|

\| **\*\*Actual LEGITIMATE\*\*** | 3,349 | 13 |

\| **\*\*Actual PHISHING\*\*** | 40 | 3,151 |

![Confusion matrix]\(reports/phishing_confusion_matrix.png)

**\*\*Reading these numbers.\*\*** The two error types are not equally costly. The 40 **\*\*false negatives\*\*** (1.25% of phishing) are phishing emails delivered to the inbox — the expensive error, since one click can mean credential theft. The 13 **\*\*false positives\*\*** (0.39% of legitimate) are legitimate emails quarantined — recoverable, but at scale they erode trust in the filter. F2 is reported alongside F1 because it weights recall twice as heavily, matching that asymmetry.

\> **\*\*Important:\*\*** the fine-tuned classifier achieved **\*\*99.19% accuracy on this project's held-out test set\*\***. That is not a claim about real-world phishing detection. The test set is roughly 50/50 phishing to legitimate, whereas real inbound mail is overwhelmingly legitimate — at a realistic base rate the same model produces far more false positives per true catch. The source corpora also date largely from 2002–2008. Benchmark performance does not transfer directly to production traffic.

**---**

**## 8. Security Risk Assessment**

The risk level is produced by a **\*\*deterministic lookup table\*\***, not a model. It has no probability, no training data and no accuracy figure.

\| Spam verdict | Phishing verdict | Risk | Rationale |

\|---|---|---|---|

\| HAM | LEGITIMATE | \`LOW\` | Neither detector flagged the email |

\| SPAM | LEGITIMATE | \`MEDIUM\` | Unwanted bulk mail; no credential risk identified |

\| HAM | PHISHING | \`HIGH\` | Resembles a credential-harvesting or fraud attempt |

\| SPAM | PHISHING | \`HIGH\` | Both detectors agree the email is hostile |

The rules live in \`RISK_RULES\` in \`email_threat_service.py\`; changing the policy means editing that table and nothing else.

Every response marks this explicitly:

\`\`\`json

"security_assessment": {

  "risk_level": "HIGH",

  "method": "rule-based",

  "is_ml_prediction": false

}

\`\`\`

If one detector is unavailable, the assessment still resolves and is flagged \`"degraded": true\`.

**---**

**## 9. Web Application**

**### Analyzer**

Subject and body inputs with a live character counter against the backend's 20,000-character limit. Results show the phishing verdict first (badged *\*Primary\**), then spam, then the risk assessment, a compact three-row summary, and a "Why was this flagged?" panel. That panel renders the Naive Bayes explanation and top signals when present, and hides entirely when the backend returned neither.

**### Overview**

Aggregate statistics across both mailboxes: messages analysed, spam, ham, manual corrections, then a **\*\*separate\*\*** phishing section (flagged as phishing, non-phishing, high risk, not analysed). Two deliberately separate charts — *\*Spam vs Ham\** and *\*Phishing vs Legitimate\** — because combining them would imply a relationship that does not exist.

**### Quarantine**

Messages requiring security review, filterable by \`All\` / \`Spam\` / \`Phishing\` / \`High Risk\` with live counts. A single message may match several filters. Each row carries independent \`[SPAM]\` \`[PHISHING]\` \`[HIGH RISK]\` badges; expanding shows a per-detector breakdown naming Naive Bayes, BERT and the rule engine. Messages stored before phishing detection existed display *\*"Phishing analysis unavailable for this message"\** rather than a fabricated verdict.

**### System Status**

Live \`/health\` polling showing API reachability, spam model state, phishing model state and the inference device. Degraded and unhealthy states surface as explicit warnings.

**---**

**## 10. API**

Interactive documentation: \`http\://127.0.0.1:8000/docs\`

\| Method | Endpoint | Purpose |

\|---|---|---|

\| \`GET\` | \`/\` | Service metadata and endpoint list |

\| \`GET\` | \`/health\` | Model load state and service status |

\| \`GET\` | \`/metrics\` | Reported evaluation figures for both models |

\| \`POST\` | \`/predict\` | Analyse one email with both detectors |

\| \`GET\` | \`/stats\` | Aggregate counts for the Overview page |

\| \`GET\` | \`/messages?box=\` | List the \`quarantine\` or \`inbox\` mailbox |

\| \`POST\` | \`/messages/{id}/move\` | Move a message between mailboxes and relabel it |

**### \`POST /predict\`**

Request:

\`\`\`json

{

  "text": "Your bank account has been suspended. Click here immediately to verify your identity.",

  "phishing_threshold": 0.5

}

\`\`\`

\`phishing_threshold\` is optional and defaults to \`0.5\`. Lowering it increases recall at the cost of precision.

Response (abbreviated):

\`\`\`json

{

  "spam_detection": {

    "available": true,

    "prediction": "HAM",

    "probability": 0.0412,

    "confidence": 0.9588,

    "model": "Multinomial Naive Bayes + CountVectorizer"

  },

  "phishing_detection": {

    "available": true,

    "prediction": "PHISHING",

    "probability": 0.9982,

    "confidence": 0.9982,

    "model": "Fine-tuned BERT (bert-base-uncased)",

    "truncated": false

  },

  "security_assessment": {

    "risk_level": "HIGH",

    "reason": "Flagged as phishing. The email resembles a credential-harvesting or fraud attempt.",

    "recommended_action": "Quarantine and do not click any links.",

    "method": "rule-based",

    "is_ml_prediction": false,

    "triggered_by": { "spam_detected": false, "phishing_detected": true }

  },

  "label": "ham",

  "confidence": 0.9588,

  "top_signals": [{ "term": "verify", "weight": 3.21, "count": 1 }],

  "explanation": "This message looks legitimate (95.9% confidence)...",

  "box": "quarantine",

  "quarantined": true

}

\`\`\`

\| Block | Meaning |

\|---|---|

\| \`spam_detection\` | Naive Bayes output. \`probability\` is P(spam). **\*\*ML prediction.\*\*** |

\| \`phishing_detection\` | BERT output. \`probability\` is P(phishing). **\*\*ML prediction.\*\*** |

\| \`security_assessment\` | Rule engine output. **\*\*Not an ML prediction.\*\*** |

\| Flat fields | The original spam-only response, retained for backward compatibility |

Note the worked example above: the email is **\*\*HAM and PHISHING simultaneously\*\*** — exactly the case a spam-only filter misses.

Errors return \`{"detail": "..."}\`: \`422\` empty or invalid input, \`413\` over 20,000 characters, \`503\` no detector available. Stack traces are never returned.

**---**

**## 11. Project Structure

```text
AI Email Threat Detection/
├── backend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── app.py                  FastAPI application and routes
│   │   │   └── schemas.py              Pydantic request/response models
│   │   ├── models/
│   │   │   ├── spam_detector.py        Naive Bayes wrapper
│   │   │   └── phishing_detector.py    BERT wrapper
│   │   ├── services/
│   │   │   └── email_threat_service.py Detector orchestration and risk rules
│   │   ├── storage/
│   │   │   └── message_store.py        CSV mailbox storage
│   │   ├── main.py                     Project entry point
│   │   └── paths.py                    Project path resolution
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_api.py
│   │   └── test_message_store.py
│   └── requirements.txt                Backend dependencies
│
├── frontend/
│   ├── src/
│   │   ├── components/                 Dashboard components
│   │   ├── pages/
│   │   ├── api.js                      Single HTTP layer
│   │   ├── App.jsx
│   │   ├── styles.css
│   │   └── smoke-test.jsx
│   ├── package.json
│   └── vite.config.js
│
├── data/
│   ├── raw/                            Source datasets
│   ├── processed/                      Cleaned data and splits
│   ├── inbox/                          Messages allowed through
│   └── quarantine/                     Messages requiring review
│
├── models/
│   ├── spam_model.pkl                  Trained spam classifier
│   ├── count_vectorizer.pkl            Spam feature vectorizer
│   └── phishing_bert/                  Fine-tuned BERT model
│
├── reports/                            Evaluation artifacts
├── scripts/                            Dataset and maintenance utilities
├── requirements.txt                    ML pipeline dependencies
└── README.md
```

| Directory | Contents |
|---|---|
| `backend/` | All Python application code, tests and backend dependencies |
| `frontend/` | React + Vite dashboard. No Python. |
| `data/` | Datasets and runtime mailbox CSVs |
| `models/` | Trained artefacts, loaded at API startup |
| `reports/` | Evaluation output — the source of every metric in this README |

> **Note:** The fine-tuned BERT weights are excluded from Git because `model.safetensors` exceeds GitHub's standard 100 MB file-size limit. The model is generated locally through the training pipeline described in this README.

## 12. Installation

Requires \*\*Python 3.10+\*\* and \*\*Node.js 18+\*\*.

\`\`\`powershell

cd "AI Email Threat Detection"

python -m venv .venv

.venv\Scripts\activate

pip install -r backend\requirements.txt

\# spaCy model used by the spam text cleaner

python -m spacy download en_core_web_sm

cd frontend

npm install

cd ..

\`\`\`

To retrain or rebuild datasets, also install the ML pipeline dependencies:

\`\`\`powershell

pip install -r requirements.txt

\`\`\`

**---**

**## 13. Running the Application**

**\*\*Backend\*\*** — from the project root:

\`\`\`powershell

.venv\Scripts\activate

python -m backend.src.main

\`\`\`

**\*\*Frontend\*\*** — in a second terminal:

\`\`\`powershell

cd frontend

npm run dev

\`\`\`

\| Service | URL |

\|---|---|

\| Frontend | \`http\://localhost:5173\` |

\| Backend API | \`http\://127.0.0.1:8000\` |

\| Swagger UI | \`http\://127.0.0.1:8000/docs\` |

\| Health check | \`http\://127.0.0.1:8000/health\` |

The Vite dev server proxies \`/api/\*\` to the backend, so no CORS configuration is needed in development. CORS is configured on the backend for other origins via the \`ALLOWED_ORIGINS\` environment variable.

Both models load at startup. On CPU, BERT adds noticeable latency to each \`/predict\` call.

**---**

**## 14. Testing**

\`\`\`powershell

\# Backend

python -m pytest backend\tests -q

\# Frontend — offline component checks, no browser or backend required

cd frontend

npm run smoke

\# Frontend production build

npm run build

\`\`\`

Backend coverage spans health, prediction, empty and malformed input, oversized input, spam and phishing verdicts, the combined response shape, the risk rule table, phishing persistence, quarantine routing, legacy CSV schemas, and backward compatibility of every pre-existing response field.

**---**

**## 15. Security Test Scenarios**

\| Scenario | Spam Detector | Phishing Detector | Risk |

\|---|---|---|---|

\| Normal work email | HAM | LEGITIMATE | LOW |

\| Retail promotion | SPAM | Model-dependent | MEDIUM or HIGH |

\| Credential theft attempt | Model-dependent | PHISHING | HIGH |

\| Fake account verification | Model-dependent | PHISHING | HIGH |

\| Mass-mailed fraud | SPAM | PHISHING | HIGH |

\| Legacy stored message | HAM or SPAM | Unavailable | As stored |

Where a detector's output genuinely varies by input, the table says *\*model-dependent\** rather than asserting a fixed result.

**---**

**## 16. Limitations**

\- **\*\*Predictions are signals, not proof.\*\*** Neither model establishes malicious intent; both produce evidence for a human or downstream control to act on.

\- **\*\*Training data is historical.\*\*** The source corpora date largely from 2002–2008. Modern phishing uses different brands, shorter pretexts, cloud-hosted landing pages and LLM-generated prose.

\- **\*\*Evaluation distribution is unrealistic.\*\*** The test set is \~50/50; real inbound mail is overwhelmingly legitimate, so measured precision is optimistic.

\- **\*\*No URL or domain reputation analysis.\*\*** URLs are preserved in the text and seen by the models, but are not extracted, resolved or checked against any reputation source.

\- **\*\*No attachment handling.\*\*** Attachments are not parsed, extracted or scanned for malware.

\- **\*\*No email header analysis.\*\*** SPF, DKIM, DMARC, sender reputation and routing headers are not evaluated.

\- **\*\*Truncation.\*\*** Emails beyond 512 tokens are head-truncated; roughly 19% of the dataset exceeds that. The response reports \`truncated: true\` when it occurs.

\- **\*\*False positives and false negatives occur.\*\*** On the held-out test set, 40 phishing emails were missed and 13 legitimate emails were flagged.

\- **\*\*The risk engine is rule-based.\*\*** Four fixed rules over two booleans — no learning, no adaptation.

\- **\*\*Single-instance, file-backed storage.\*\*** Mailboxes are CSV files guarded by a process-level lock; there is no database and no multi-instance coordination.

\- **\*\*No adversarial testing.\*\*** The model has not been evaluated against inputs crafted to evade it.

**---**

**## 17. Security Considerations**

**### Currently implemented**

\| Control | Implementation |

\|---|---|

\| Input validation | Pydantic schema, non-empty, 20,000-character ceiling |

\| Error handling | Generic error responses; stack traces never returned to clients |

\| CORS | Explicit origin allow-list, configurable via \`ALLOWED_ORIGINS\` |

\| Request timeout | 60s client-side ceiling to prevent indefinite hangs |

\| Graceful degradation | A failed detector is reported via \`/health\`; the service keeps serving |

\| Non-destructive quarantine | Messages are filed, never deleted |

\| Secret hygiene | No credentials in source; \`.env\` files git-ignored |

**### Production considerations — NOT implemented**

\| Control | Status |

\|---|---|

\| Authentication | Not implemented — the API is unauthenticated |

\| Authorization / RBAC | Not implemented |

\| HTTPS / TLS | Not implemented — HTTP only in development |

\| Secrets management | Not implemented — no vault integration |

\| Rate limiting | Not implemented |

\| Audit logging | Not implemented — no tamper-evident trail |

\| PII handling and data retention | Not implemented — email bodies are stored in plaintext CSV indefinitely |

\| Dependency and vulnerability scanning | Not implemented |

\| Model versioning and registry | Not implemented |

\| Model and data drift monitoring | Not implemented |

\| Containerisation and secure deployment | Not implemented |

\> Email content is among the most sensitive data an organisation holds. This system stores analysed message bodies in plaintext CSV files with no encryption, access control or retention policy. That is acceptable for local research; it is **\*\*not\*\*** acceptable for real mail.

**---**

**## 18. Future Improvements**

*\*Roadmap. None of the following is implemented.\**

**### Phase 1 — Advanced Email Intelligence**

Modern phishing datasets · continuous dataset refresh · hard-negative mining · email header analysis (SPF/DKIM/DMARC) · URL extraction · URL and domain reputation · IOC extraction · attachment metadata analysis · attachment malware scanning integration

**### Phase 2 — Threat Intelligence**

Threat intelligence feeds · domain reputation · DNS intelligence · WHOIS intelligence · URL reputation · IOC correlation · enrichment pipeline

**### Phase 3 — Advanced ML**

Evaluate modern transformer architectures · model comparison · decision-threshold calibration · precision/recall optimisation for realistic base rates · class imbalance handling · false-positive reduction · false-negative analysis · explainability (attention or SHAP attribution for BERT) · adversarial robustness testing

**### Phase 4 — Enterprise Security Integration**

Microsoft 365 integration · Google Workspace integration · email gateway integration · SIEM integration · SOC alerting · security orchestration · incident management integration · analyst feedback loops

**### Phase 5 — MLOps**

Dataset versioning · automated retraining · model registry · model version management · CI/CD for models · performance monitoring · data drift monitoring · model drift detection · automated evaluation · rollback

**### Phase 6 — Production Hardening**

Containerisation · cloud deployment · HTTPS/TLS · secrets management · authentication and RBAC · rate limiting · centralised logging · observability · vulnerability scanning · dependency monitoring · infrastructure security

**---**

**## 19. Roadmap**

**\*\*Completed\*\***

\- ✓ Dataset consolidation and leakage-controlled preparation

\- ✓ Spam detection (CountVectorizer + Naive Bayes)

\- ✓ BERT phishing detection (fine-tuned, evaluated)

\- ✓ Model evaluation and reporting

\- ✓ FastAPI backend with both detectors loaded at startup

\- ✓ Rule-based security risk assessment

\- ✓ React dashboard — Analyzer, Overview, Quarantine, System Status

\- ✓ Backend and frontend test suites

**\*\*Next\*\***

\- → Advanced email intelligence (headers, URLs, attachments)

\- → Threat intelligence integration

\- → Enterprise mail platform integrations

\- → MLOps and automated retraining

\- → Production security hardening

**---**

**## 20. Disclaimer**

This project is intended for research, educational, and demonstration purposes. Machine-learning predictions should be treated as security signals rather than definitive proof of malicious intent. Production deployment requires additional validation, monitoring, security controls, privacy protections, and operational testing.