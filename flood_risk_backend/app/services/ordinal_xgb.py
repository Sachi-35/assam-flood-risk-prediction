"""XGBoost wrapper that accepts string class names and tolerates classes missing from the training data (xgboost needs 0..k-1)."""
import numpy as np

from app.features import CLASS_ORDER


class OrdinalXGB:
    def __init__(self, **params):
        self.params = params

    def fit(self, X, y):
        from xgboost import XGBClassifier
        self.classes_ = np.array([c for c in CLASS_ORDER if (np.asarray(y) == c).any()])
        idx = {c: i for i, c in enumerate(self.classes_)}
        self.model_ = XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=42,
                                    objective="multi:softprob", **self.params)
        self.model_.fit(X, np.array([idx[c] for c in np.asarray(y)]))
        return self

    def predict_proba(self, X):
        return self.model_.predict_proba(X)

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(axis=1)]
