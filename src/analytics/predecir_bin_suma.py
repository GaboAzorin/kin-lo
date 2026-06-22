"""
predecir_bin_suma.py
Proyecta el rango de suma (bin) al que pertenecerá el SORTEO SIGUIENTE, usando
modelos del mundo ML/DL (red neuronal MLP + LSTM en PyTorch) y los compara,
honestamente, contra líneas base triviales.

Premisa científica
-------------------
La suma de un sorteo justo es la suma de una muestra sin reemplazo de un pool
fijo. Cada sorteo es independiente del anterior. Por tanto NINGÚN modelo puede
predecir el bin de t+1 mejor que la distribución marginal de los bins. Una red
neuronal, bien entrenada, *converge* a esa marginal: ignora el pasado porque el
pasado no aporta información. Este script existe para DEMOSTRARLO con números,
no para afirmarlo.

Qué mide
--------
  - Baseline MODAL      : predecir siempre el bin más frecuente (train).
  - Baseline MARGINAL   : muestrear según frecuencias (acc esperada = Σ p_i²).
  - Baseline PERSISTENCIA: predecir el mismo bin que el sorteo anterior.
  - Regresión logística : multinomial sobre features de lags (sklearn).
  - Red MLP             : feed-forward sobre features de lags (PyTorch).
  - Red LSTM            : secuencia de las últimas K sumas (PyTorch).
  - Control PERMUTACIÓN : barajar el orden temporal y reentrenar. Si la red da
                          la MISMA accuracy con el tiempo destruido, entonces no
                          estaba usando ninguna señal temporal (solo la marginal).

Split temporal: se entrena con el pasado y se evalúa con el futuro (sin fuga).

Uso:
    python src/analytics/predecir_bin_suma.py --game kino
    python src/analytics/predecir_bin_suma.py --game loto --bins 5 --binning quantile
    python src/analytics/predecir_bin_suma.py --game kino --binning fixed --bins 7
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]

GAMES = {
    "kino": {
        "csv": REPO_ROOT / "data" / "loteria_historial.csv",
        "prefix": "KINO_n",
        "nums": 14,
        "pool": 25,
    },
    "loto": {
        "csv": REPO_ROOT / "data" / "polla_historial.csv",
        "prefix": "LOTO_n",
        "nums": 6,
        "pool": 41,
    },
}


# --------------------------------------------------------------------------- #
# Datos
# --------------------------------------------------------------------------- #
def cargar_sumas(game: str) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (sorteos, sumas) en orden cronológico para el juego dado."""
    cfg = GAMES[game]
    filas: list[tuple[int, int]] = []
    with open(cfg["csv"], "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nums, ok = [], True
            for i in range(1, cfg["nums"] + 1):
                v = (row.get(f"{cfg['prefix']}{i}") or "").strip()
                if not v:
                    ok = False
                    break
                nums.append(int(float(v)))
            if not (ok and len(nums) == cfg["nums"]):
                continue
            try:
                sorteo = int(float((row.get("sorteo") or "0").strip()))
            except ValueError:
                continue
            filas.append((sorteo, sum(nums)))
    filas.sort(key=lambda r: r[0])
    sorteos = np.array([r[0] for r in filas], dtype=np.int64)
    sumas = np.array([r[1] for r in filas], dtype=np.float64)
    return sorteos, sumas


def hacer_bins(sumas: np.ndarray, n_bins: int, modo: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Asigna cada suma a un bin. Devuelve (labels, edges).
    - quantile : bins de igual frecuencia (clases balanceadas → baseline modal ≈ 1/k).
    - fixed    : bins de igual ancho (el bin central domina → baseline modal alto).
    """
    if modo == "quantile":
        qs = np.linspace(0, 1, n_bins + 1)
        edges = np.unique(np.quantile(sumas, qs))
    else:
        edges = np.linspace(sumas.min(), sumas.max(), n_bins + 1)
    # np.digitize con el borde derecho incluido en el último bin
    labels = np.digitize(sumas, edges[1:-1], right=False)
    labels = np.clip(labels, 0, len(edges) - 2)
    return labels.astype(np.int64), edges


# --------------------------------------------------------------------------- #
# Features (lags) y secuencias
# --------------------------------------------------------------------------- #
def construir_features(sumas: np.ndarray, labels: np.ndarray, n_bins: int, K: int):
    """
    Para predecir bin(t) usando solo informacion de t-1..t-K.
    X_feat : [sumas normalizadas de los K lags, media movil, std movil, one-hot del bin t-1]
    X_seq  : secuencia (K,1) de sumas normalizadas (para LSTM)
    y      : bin(t)
    """
    mu, sd = sumas.mean(), sumas.std() + 1e-9
    z = (sumas - mu) / sd
    X_feat, X_seq, y = [], [], []
    for t in range(K, len(sumas)):
        lags = z[t - K:t][::-1]                       # [t-1, t-2, ..., t-K]
        roll_mean = z[t - K:t].mean()
        roll_std = z[t - K:t].std()
        onehot_prev = np.zeros(n_bins)
        onehot_prev[labels[t - 1]] = 1.0
        X_feat.append(np.concatenate([lags, [roll_mean, roll_std], onehot_prev]))
        X_seq.append(z[t - K:t].reshape(K, 1))        # cronológico para el LSTM
        y.append(labels[t])
    return (np.array(X_feat, dtype=np.float32),
            np.array(X_seq, dtype=np.float32),
            np.array(y, dtype=np.int64))


# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #
def acc(pred: np.ndarray, true: np.ndarray) -> float:
    return float((pred == true).mean())


def baseline_modal(y_tr, y_te, n_bins):
    modal = np.bincount(y_tr, minlength=n_bins).argmax()
    return acc(np.full_like(y_te, modal), y_te), int(modal)


def baseline_marginal_esperado(y_tr):
    p = np.bincount(y_tr) / len(y_tr)
    return float((p ** 2).sum())  # acc esperada al muestrear i.i.d. de la marginal


def baseline_persistencia(labels, idx_te):
    # predecir bin(t) = bin(t-1); idx_te son indices ABSOLUTOS en `labels`
    pred = labels[idx_te - 1]
    return acc(pred, labels[idx_te])


# --------------------------------------------------------------------------- #
# Modelos PyTorch
# --------------------------------------------------------------------------- #
def entrenar_torch(modelo_fn, Xtr, ytr, Xte, yte, n_bins, epochs=150, lr=1e-3, seed=0):
    import torch
    torch.manual_seed(seed)
    np.random.seed(seed)

    Xtr_t = torch.tensor(Xtr)
    ytr_t = torch.tensor(ytr)
    Xte_t = torch.tensor(Xte)

    model = modelo_fn()
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    lossf = torch.nn.CrossEntropyLoss()

    n = len(Xtr_t)
    bs = 64
    model.train()
    for _ in range(epochs):
        perm = torch.randperm(n)
        for i in range(0, n, bs):
            j = perm[i:i + bs]
            opt.zero_grad()
            out = model(Xtr_t[j])
            loss = lossf(out, ytr_t[j])
            loss.backward()
            opt.step()
    model.eval()
    with torch.no_grad():
        logits = model(Xte_t)
        pred = logits.argmax(1).numpy()
        # distribucion de probabilidad para la proyeccion del siguiente sorteo
        proba_last = torch.softmax(logits[-1:], dim=1).numpy()[0]
    return pred, proba_last, model


def mlp_factory(in_dim, n_bins):
    import torch.nn as nn

    def fn():
        return nn.Sequential(
            nn.Linear(in_dim, 64), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(64, 32), nn.ReLU(),
            nn.Linear(32, n_bins),
        )
    return fn


def lstm_factory(n_bins, hidden=32):
    import torch
    import torch.nn as nn

    class LSTMClf(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(input_size=1, hidden_size=hidden, batch_first=True)
            self.head = nn.Linear(hidden, n_bins)

        def forward(self, x):
            out, (h, _) = self.lstm(x)
            return self.head(h[-1])

    return LSTMClf


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def run(game: str, n_bins: int, binning: str, K: int, epochs: int, seed: int):
    sorteos, sumas = cargar_sumas(game)
    labels, edges = hacer_bins(sumas, n_bins, binning)
    n_bins_real = len(edges) - 1

    Xf, Xs, y = construir_features(sumas, labels, n_bins_real, K)
    # idx absolutos en `labels` correspondientes a cada muestra (t = K..len-1)
    idx_abs = np.arange(K, len(sumas))

    # split temporal 80/20
    n = len(y)
    cut = int(n * 0.8)
    Xf_tr, Xf_te = Xf[:cut], Xf[cut:]
    Xs_tr, Xs_te = Xs[:cut], Xs[cut:]
    y_tr, y_te = y[:cut], y[cut:]
    idx_te = idx_abs[cut:]

    rep = {
        "game": game,
        "n_sorteos": int(len(sumas)),
        "n_muestras": int(n),
        "n_bins": int(n_bins_real),
        "binning": binning,
        "K_lags": K,
        "edges": [round(float(e), 1) for e in edges],
        "test_size": int(len(y_te)),
        "suma_media": round(float(sumas.mean()), 2),
        "suma_desv": round(float(sumas.std()), 2),
    }

    # ---- baselines ----
    acc_modal, modal = baseline_modal(y_tr, y_te, n_bins_real)
    acc_marg = baseline_marginal_esperado(y_tr)
    acc_pers = baseline_persistencia(labels, idx_te)
    rep["baselines"] = {
        "modal": round(acc_modal, 4),
        "modal_bin": modal,
        "marginal_esperada": round(acc_marg, 4),
        "persistencia": round(acc_pers, 4),
    }

    # ---- regresion logistica ----
    from sklearn.linear_model import LogisticRegression
    logreg = LogisticRegression(max_iter=2000, C=1.0)
    logreg.fit(Xf_tr, y_tr)
    acc_lr = acc(logreg.predict(Xf_te), y_te)

    # ---- MLP ----
    pred_mlp, proba_mlp, _ = entrenar_torch(
        mlp_factory(Xf.shape[1], n_bins_real), Xf_tr, y_tr, Xf_te, y_te,
        n_bins_real, epochs=epochs, seed=seed)
    acc_mlp = acc(pred_mlp, y_te)

    # ---- LSTM ----
    pred_lstm, proba_lstm, _ = entrenar_torch(
        lstm_factory(n_bins_real), Xs_tr, y_tr, Xs_te, y_te,
        n_bins_real, epochs=epochs, seed=seed)
    acc_lstm = acc(pred_lstm, y_te)

    rep["modelos"] = {
        "logistica": round(acc_lr, 4),
        "mlp": round(acc_mlp, 4),
        "lstm": round(acc_lstm, 4),
    }

    # ---- control de permutacion: barajar y_tr y reentrenar el MLP ----
    rng = np.random.default_rng(seed)
    y_tr_shuf = y_tr.copy()
    rng.shuffle(y_tr_shuf)
    pred_perm, _, _ = entrenar_torch(
        mlp_factory(Xf.shape[1], n_bins_real), Xf_tr, y_tr_shuf, Xf_te, y_te,
        n_bins_real, epochs=epochs, seed=seed)
    acc_perm = acc(pred_perm, y_te)
    rep["control_permutacion_mlp"] = round(acc_perm, 4)

    # ---- proyeccion del SORTEO SIGUIENTE ----
    # se usa la ultima secuencia/feature disponible (la mas reciente del CSV)
    bin_pred_mlp = int(np.argmax(proba_mlp))
    bin_pred_lstm = int(np.argmax(proba_lstm))
    ult_sorteo = int(sorteos[-1])

    def rango_txt(b):
        return f"[{edges[b]:.0f} – {edges[b + 1]:.0f}]"

    rep["proyeccion_siguiente"] = {
        "ultimo_sorteo_en_csv": ult_sorteo,
        "proximo_sorteo": ult_sorteo + 1,
        "mlp_bin": bin_pred_mlp,
        "mlp_rango_suma": rango_txt(bin_pred_mlp),
        "mlp_proba": [round(float(p), 3) for p in proba_mlp],
        "lstm_bin": bin_pred_lstm,
        "lstm_rango_suma": rango_txt(bin_pred_lstm),
        "lstm_proba": [round(float(p), 3) for p in proba_lstm],
        "marginal_proba": [round(float(p), 3)
                           for p in (np.bincount(y, minlength=n_bins_real) / len(y))],
    }

    rep["veredicto"] = _veredicto(rep)
    return rep, edges


def _veredicto(rep: dict) -> str:
    b = rep["baselines"]
    m = rep["modelos"]
    mejor_base = max(b["modal"], b["marginal_esperada"], b["persistencia"])
    mejor_modelo = max(m.values())
    delta = mejor_modelo - mejor_base
    # margen de error binomial aprox (1 sigma) sobre el test
    n = rep["test_size"]
    se = (mejor_base * (1 - mejor_base) / n) ** 0.5
    if delta <= se:
        return (f"NULO: el mejor modelo ({mejor_modelo:.3f}) NO supera a la mejor "
                f"linea base ({mejor_base:.3f}) mas alla del ruido (±{se:.3f}). "
                f"Como se esperaba, la red converge a la marginal: el sorteo no "
                f"tiene memoria explotable.")
    return (f"SEÑAL APARENTE: el mejor modelo ({mejor_modelo:.3f}) supera la base "
            f"({mejor_base:.3f}) por {delta:.3f} (> ±{se:.3f}). Revisar antes de "
            f"creerlo: probar otra semilla, otro split y mas sorteos.")


# --------------------------------------------------------------------------- #
def imprimir(rep: dict):
    print(f"\n=== Proyección de bin de suma — {rep['game'].upper()} ===")
    print(f"sorteos={rep['n_sorteos']}  muestras={rep['n_muestras']}  "
          f"bins={rep['n_bins']} ({rep['binning']})  K_lags={rep['K_lags']}  "
          f"test={rep['test_size']}")
    print(f"suma media={rep['suma_media']} σ={rep['suma_desv']}  edges={rep['edges']}")
    b, m = rep["baselines"], rep["modelos"]
    print("\n-- Líneas base --")
    print(f"  modal (siempre bin {b['modal_bin']}) : {b['modal']:.3f}")
    print(f"  marginal (esperada)        : {b['marginal_esperada']:.3f}")
    print(f"  persistencia (= anterior)  : {b['persistencia']:.3f}")
    print("\n-- Modelos ML/DL --")
    print(f"  regresión logística : {m['logistica']:.3f}")
    print(f"  red MLP             : {m['mlp']:.3f}")
    print(f"  red LSTM            : {m['lstm']:.3f}")
    print(f"  control permutación : {rep['control_permutacion_mlp']:.3f}  "
          f"(MLP con el tiempo barajado)")
    p = rep["proyeccion_siguiente"]
    print(f"\n-- Proyección sorteo {p['proximo_sorteo']} --")
    print(f"  MLP  → bin {p['mlp_bin']} suma {p['mlp_rango_suma']}  "
          f"proba={p['mlp_proba']}")
    print(f"  LSTM → bin {p['lstm_bin']} suma {p['lstm_rango_suma']}  "
          f"proba={p['lstm_proba']}")
    print(f"  marginal histórica  proba={p['marginal_proba']}")
    print(f"\n>>> {rep['veredicto']}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", choices=list(GAMES), default="kino")
    ap.add_argument("--bins", type=int, default=5)
    ap.add_argument("--binning", choices=["quantile", "fixed"], default="quantile")
    ap.add_argument("--lags", type=int, default=10)
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json-out", type=str, default="")
    args = ap.parse_args()

    rep, _ = run(args.game, args.bins, args.binning, args.lags, args.epochs, args.seed)
    rep["generado"] = datetime.now(timezone.utc).isoformat()
    imprimir(rep)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print(f"JSON -> {out}")


if __name__ == "__main__":
    main()
