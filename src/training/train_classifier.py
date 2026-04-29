"""
VALMO L1 Agent - Training Pipeline
Trains the issue classification model from historical ticket data.
Uses scikit-learn TF-IDF + Logistic Regression.
The trained model is saved to disk and loaded at runtime by TicketIngestionService.

Usage:
  python -m src.training.train_classifier \
    --data data/historical_tickets.jsonl \
    --output models/

Training data format (JSONL):
  {"ticket_id": "T001", "subject": "...", "body": "...", "issue_type": "payment_not_received"}
"""

import argparse
import json
import logging
import pickle
from pathlib import Path
from typing import List, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────

def load_training_data(path: str) -> Tuple[List[str], List[str]]:
    """Loads JSONL training data → (texts, labels)."""
    texts, labels = [], []
    with open(path) as f:
        for line in f:
            record = json.loads(line.strip())
            text = f"{record.get('subject', '')} {record.get('body', '')}"
            label = record.get("issue_type", "unknown")
            texts.append(text)
            labels.append(label)
    logger.info(f"Loaded {len(texts)} training examples.")
    return texts, labels


def generate_synthetic_training_data() -> Tuple[List[str], List[str]]:
    """
    Generates a minimal synthetic dataset for bootstrapping the model.
    In production, replace with real historical ticket data.
    """
    samples = [
        # shortage_loss_dispute
        ("shortage loss dispute AWB AB123456789",
         "I have not received full delivery. There is a shortage loss for AWB AB123456789.",
         "shortage_loss_dispute"),
        ("missing shipment shortage claim",
         "Partner is claiming shortage loss for multiple AWBs. Please investigate.",
         "shortage_loss_dispute"),

        # hardstop_loss_dispute
        ("hardstop loss query",
         "We have a hardstop loss dispute for AWB XY987654321 at BOM hub.",
         "hardstop_loss_dispute"),

        # payment_not_received
        ("payment not received for cycle Jan 2024",
         "We have not received payment for billing cycle 2024-01. Amount INR 45000.",
         "payment_not_received"),
        ("amount not credited",
         "The payment for last month has not been credited to our account.",
         "payment_not_received"),

        # invoice_not_generated
        ("invoice not generated",
         "Our invoice for the current billing cycle has not been generated yet.",
         "invoice_not_generated"),
        ("no invoice raised",
         "Invoice not raised for February cycle. Please check.",
         "invoice_not_generated"),

        # shipment_count_mismatch
        ("shipment count mismatch",
         "There is a discrepancy in the shipment count for last week. Manifest shows 150 but only 148 scanned.",
         "shipment_count_mismatch"),

        # debit_clarification
        ("debit clarification needed",
         "We received a debit of INR 1200 for AWB AB123456789. Please explain the reason.",
         "debit_clarification"),

        # debit_reversal
        ("debit reversal request",
         "We are requesting reversal of the debit applied on AWB XY987654321.",
         "debit_reversal"),

        # drop_in_load_volume
        ("drop in load volume",
         "Our load volume has dropped significantly over the past 2 weeks. Please clarify.",
         "drop_in_load_volume"),
        ("load reduction noticed",
         "We are seeing a consistent decline in loads manifested from DEL hub.",
         "drop_in_load_volume"),

        # fluctuating_load_volume
        ("fluctuating load volume",
         "Load volumes are inconsistent and fluctuating week over week.",
         "fluctuating_load_volume"),

        # cod_not_reflecting
        ("cod not reflecting",
         "COD deposits collected last week are not reflecting in our account.",
         "cod_not_reflecting"),
        ("cod pendency query",
         "We have a COD pendency balance that has not been remitted.",
         "cod_not_reflecting"),
    ]

    texts = [f"{subj} {body}" for subj, body, _ in samples]
    labels = [label for _, _, label in samples]
    return texts, labels


# ─────────────────────────────────────────────
# TRAINING
# ─────────────────────────────────────────────

def train(texts: List[str], labels: List[str], output_dir: str):
    """Train TF-IDF + Logistic Regression classifier and save to disk."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.pipeline import Pipeline

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    logger.info("Fitting TF-IDF vectorizer...")
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        max_features=10000,
        sublinear_tf=True,
        min_df=1,
    )
    X = vectorizer.fit_transform(texts)

    logger.info("Training Logistic Regression classifier...")
    clf = LogisticRegression(
        max_iter=1000,
        C=5.0,
        class_weight="balanced",
        solver="lbfgs",
        
    )
    clf.fit(X, labels)

    # Cross-validation
    pipeline = Pipeline([("tfidf", vectorizer), ("clf", clf)])
    scores = cross_val_score(pipeline, texts, labels, cv=2, scoring="accuracy")
    logger.info(f"CV Accuracy: {scores.mean():.3f} ± {scores.std():.3f}")

    # Save
    clf_path = output_path / "issue_classifier.pkl"
    vec_path = output_path / "issue_vectorizer.pkl"
    with open(clf_path, "wb") as f:
        pickle.dump(clf, f)
    with open(vec_path, "wb") as f:
        pickle.dump(vectorizer, f)

    logger.info(f"Model saved to {clf_path}")
    logger.info(f"Vectorizer saved to {vec_path}")

    # Save class list for reference
    classes_path = output_path / "classes.json"
    with open(classes_path, "w") as f:
        json.dump(list(clf.classes_), f, indent=2)

    return clf, vectorizer


# ─────────────────────────────────────────────
# ESCALATION PREDICTOR TRAINING
# ─────────────────────────────────────────────

def train_escalation_predictor(historical_data_path: str, output_dir: str):
    """
    Trains a secondary model to predict whether a ticket is likely to escalate.
    This allows the system to flag high-risk tickets early for pre-emptive routing.

    Training data format (JSONL):
      {"text": "...", "escalated": true}
    """
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        logger.warning("scikit-learn not available. Skipping escalation predictor training.")
        return

    texts, labels = [], []
    with open(historical_data_path) as f:
        for line in f:
            record = json.loads(line.strip())
            texts.append(record.get("text", ""))
            labels.append(1 if record.get("escalated") else 0)

    if len(set(labels)) < 2:
        logger.warning("Escalation predictor needs both positive and negative examples. Skipping.")
        return

    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import cross_val_score

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=5000)
    clf = LogisticRegression(max_iter=500, class_weight="balanced")
    pipeline = Pipeline([("tfidf", vectorizer), ("clf", clf)])
    pipeline.fit(texts, labels)

    scores = cross_val_score(pipeline, texts, labels, cv=min(5, len(texts)), scoring="roc_auc")
    logger.info(f"Escalation Predictor AUC: {scores.mean():.3f} ± {scores.std():.3f}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with open(output_path / "escalation_predictor.pkl", "wb") as f:
        pickle.dump(pipeline, f)
    logger.info("Escalation predictor saved.")


# ─────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Train VALMO L1 Agent classifiers")
    parser.add_argument("--data", type=str, default=None,
                        help="Path to JSONL training data. Uses synthetic if not provided.")
    parser.add_argument("--output", type=str, default="models/",
                        help="Output directory for trained models.")
    args = parser.parse_args()

    if args.data:
        texts, labels = load_training_data(args.data)
    else:
        logger.info("No data file provided. Using synthetic training data.")
        texts, labels = generate_synthetic_training_data()

    train(texts, labels, args.output)
